/**
 * 提案 → 执行计划 转换器。
 *
 * 把算法侧的 Mission Proposal 展开成 Runtime 的 Mission Plan（供
 * POST /api/plans/execute 提交）。
 *
 * 为什么转换器要做全量校验而不是"能转就转"
 * ----------------------------------------
 * 提案是**声明式**的：它只说"谁负责哪个任务、按什么顺序做什么、去哪些航点"。
 * 计划是**可执行**的：每一步都要有具体参数。两者之间有一个展开过程，而展开
 * 过程中最容易出的事是"悄悄少做一件事"——
 *
 *   - 动作名不认识 → 跳过？那计划就少了一步
 *   - 航点 ID 查不到 → 用默认值？那会飞到错误的位置
 *   - 某步没有目标载具 → 拿第一台顶上？那可能飞错飞机
 *
 * 因此这里的原则是：**先全量校验，任一问题就拒绝整份提案**，并指出具体是哪个
 * task / action / waypoint 的问题。绝不静默跳过，也不提交"可执行子集"充当
 * 原任务 —— 那会产生"计划显示完成、实际少做了事"的假成功。
 *
 * 这条原则对本项目不是抽象的：已经踩过两次同类问题（位置设定点的 type_mask
 * 写错导致飞机不动却零报错；收尾误判 RTL 为安全悬停导致动作报 pass 而飞机
 * 在自主返航）。
 *
 * 与 Runtime 的分工
 * -----------------
 * 本转换器只做**离线**校验与展开。真正的执行授权在 Runtime：
 * 每一步仍会过 Policy Gate，且 scene_id / map_version 会与 Runtime 的
 * **当前活动场景**再次核对（见 docs/algorithm_runtime_execution_contract_v0_1.md）。
 * 提案里的 execution_authorized=false 与本转换器的立场一致：提案不是授权。
 */

/** 可展开为 step 的动作。与 Runtime 已实现的端点一一对应。 */
export const EXPANDABLE_ACTIONS = Object.freeze({
  TAKEOFF: "takeoff",
  GOTO: "goto",
  LAND: "land",
  // HOLD / RETURN_HOME 于 2026-09-30 在 Runtime 侧实现（分别对应
  // /api/actions/hold-position 与 /api/actions/return-home）。
  //
  // ⚠️ 它们**能执行**，但本转换器**仍不展开** —— 两者是不同的判断：
  //   * 展开 HOLD 需要知道"保持在哪、保持多久"，那是任务语义，不是提案展开
  //   * 展开 RETURN_HOME 的时机涉及"何时判定任务做完了"，同样超出展开职责
  // 也就是说这不再是"端点没实现"的问题，而是"转换器还没有展开规则"。
  // 因此它们单独归入 CONVERTER_NOT_EXPANDABLE，措辞与"未实现"区分开，
  // 免得调用方以为端点还不存在。
});

/** 已实现端点、但本转换器暂不展开的动作。 */
export const CONVERTER_NOT_EXPANDABLE = Object.freeze([
  "HOLD", "HOLD_POSITION", "RETURN_HOME",
]);

/** 已知但本转换器不展开的动作。列出来是为了给出"未实现"而不是"拼写错误"。 */
export const KNOWN_NOT_EXPANDABLE = Object.freeze([
  "OBSERVE", "HOVER",
  "CAMERA_CAPTURE", "GIMBAL_SET_ANGLE", "LIGHT_SET_STATE", "SPEAKER_PLAY_MESSAGE",
  "HEALTH_QUERY", "REPORT_STATUS", "SENSOR_READ", "LAND_SAFE",
  "REDUCE_SPEED", "MAINTAIN_HEADING",
  // 高风险载荷动作：本执行路径不提供该能力，不是"待实现"。
  "ATTACK", "STRIKE", "DROP", "DEPLOY", "PAYLOAD_RELEASE",
]);

/** 风险等级最高、本路径明确不提供的载荷动作。措辞必须与"未实现"区分。 */
const UNSUPPORTED_PAYLOAD_ACTIONS = Object.freeze([
  "ATTACK", "STRIKE", "DROP", "DEPLOY", "PAYLOAD_RELEASE",
]);

export class ProposalRejected extends Error {
  constructor(code, message, violations = []) {
    super(message);
    this.name = "ProposalRejected";
    this.code = code;
    this.violations = violations;
  }

  toResponse() {
    return {
      result: "blocked",
      failure_reason: this.code,
      message: this.message,
      detail: { violations: this.violations },
    };
  }
}

const nonEmptyString = (v) => typeof v === "string" && v.trim() !== "";
const finiteNumber = (v) => typeof v === "number" && Number.isFinite(v);

/**
 * 把提案展开为可提交的 plan。
 *
 * @param {object} proposal            算法的 mission_proposal（schema 0.1）
 * @param {object} context             与提案同源的输入 context（含 waypoints[]）
 * @param {object} options
 * @param {number} options.takeoffAltitudeM
 *        **必须显式给出**的起飞高度（米，正数）。
 *        刻意不从 context.constraints.min_altitude_m 推断：那是"允许的最低高度"
 *        这种约束，不是任务要求的高度。把约束当任务高度是在臆造指令。
 * @param {string} [options.planId]    计划 ID；缺省由 missionId 派生
 * @returns {{plan: object, notes: string[]}}
 * @throws {ProposalRejected}
 */
export function proposalToPlan(proposal, context, options = {}) {
  const { takeoffAltitudeM, planId } = options;

  if (!Number.isFinite(takeoffAltitudeM) || takeoffAltitudeM <= 0) {
    // 这是调用方的编程错误，不是提案的问题 —— 但仍要拒绝，不能猜一个高度。
    throw new ProposalRejected(
      "takeoff_altitude_required",
      "必须显式提供 takeoffAltitudeM（正数）。不从 constraints.min_altitude_m 推断：" +
        "那是允许的最低高度约束，不是任务要求的高度。",
      [{ field: "takeoffAltitudeM", value: takeoffAltitudeM ?? null }],
    );
  }

  // ---- 1) 结构校验：上下文与提案的基本形态 ------------------------------
  if (!context || typeof context !== "object") {
    throw new ProposalRejected("context_required", "缺少输入 context，无法解析航点。");
  }
  if (!proposal || typeof proposal !== "object") {
    throw new ProposalRejected("proposal_required", "缺少 proposal。");
  }

  const waypoints = buildWaypointIndex(context);
  const violations = [];

  // ---- 2) 场景身份：提案与 context 必须一致 -----------------------------
  //
  // 提案的坐标来自这份 context。若两者的场景身份不一致，说明提案不是基于
  // 这份 context 产生的，坐标的可信度无从谈起。
  for (const field of ["scene_id", "map_version"]) {
    const fromProposal = proposal[field];
    const fromContext = context[field];
    if (!nonEmptyString(fromProposal) || !nonEmptyString(fromContext)) {
      violations.push({
        kind: "scene_identity_missing",
        field,
        proposal_value: fromProposal ?? null,
        context_value: fromContext ?? null,
      });
    } else if (String(fromProposal) !== String(fromContext)) {
      violations.push({
        kind: "scene_identity_conflict",
        field,
        proposal_value: fromProposal,
        context_value: fromContext,
      });
    }
  }

  // ---- 3) assignments 全量校验 -----------------------------------------
  const assignments = Array.isArray(proposal.assignments) ? proposal.assignments : [];
  if (assignments.length === 0) {
    violations.push({ kind: "no_assignments" });
  }

  for (const [index, assignment] of assignments.entries()) {
    const taskId = nonEmptyString(assignment?.task_id) ? assignment.task_id : `#${index}`;
    const nodeId = assignment?.node_id;

    if (!nonEmptyString(nodeId)) {
      // 没有合理的默认载具 —— 猜错等于飞错飞机。
      violations.push({ kind: "missing_target_vehicle", task_id: taskId, node_id: nodeId ?? null });
    }

    const actions = Array.isArray(assignment?.actions) ? assignment.actions : [];
    for (const action of actions) {
      const name = String(action ?? "").toUpperCase();
      if (!Object.prototype.hasOwnProperty.call(EXPANDABLE_ACTIONS, name)) {
        violations.push({
          kind: "action_not_expandable",
          task_id: taskId,
          action: name,
          reason_code: UNSUPPORTED_PAYLOAD_ACTIONS.includes(name)
            ? "action_not_supported"
            : CONVERTER_NOT_EXPANDABLE.includes(name)
              // 端点已存在，只是本转换器还没有展开规则。措辞必须与"未实现"
              // 区分开：否则调用方会以为端点还不存在，去等一个已经有的东西。
              ? "action_no_expansion_rule"
              : "action_endpoint_not_implemented",
        });
      }
    }

    const waypointIds = Array.isArray(assignment?.waypoint_ids) ? assignment.waypoint_ids : [];
    for (const waypointId of waypointIds) {
      if (!waypoints.has(String(waypointId))) {
        violations.push({ kind: "waypoint_not_found", task_id: taskId, waypoint_id: waypointId });
      }
    }

    // 一个 GOTO 至少要有一个航点，否则"飞过去"没有落点。
    const gotoCount = actions.filter((a) => String(a ?? "").toUpperCase() === "GOTO").length;
    if (gotoCount > 0 && waypointIds.length === 0) {
      violations.push({ kind: "goto_without_waypoint", task_id: taskId, goto_count: gotoCount });
    }
  }

  // 任一问题 → 拒绝整份提案。绝不提交可执行子集。
  if (violations.length > 0) {
    throw new ProposalRejected(
      "proposal_not_executable",
      `提案有 ${violations.length} 处无法转换为可执行步骤，已拒绝整份提案（不提交子集）。`,
      violations,
    );
  }

  // ---- 4) 展开 ---------------------------------------------------------
  //
  // 每台的步骤按各自 actions[] 的顺序展开，node_id 复制到每个 step。
  // 多机之间的全局顺序没有调度语义（交接说明明确提到这点），因此这一步只是
  // 按 assignments 的顺序把各机步骤依次排列，不代表任何协同时序。
  //
  // 一个 GOTO 按其 waypoint_ids[] 顺序展开为多个 goto step。
  const steps = [];
  const notes = [];

  for (const assignment of assignments) {
    const nodeId = String(assignment.node_id);
    const taskId = String(assignment.task_id);
    const actions = assignment.actions.map((a) => String(a).toUpperCase());
    const waypointIds = (assignment.waypoint_ids || []).map(String);

    const gotoTotal = actions.filter((a) => a === "GOTO").length;
    // 航点按顺序分配给各次 GOTO：第 i 个 GOTO 用第 i 组航点。
    // 交接说明只保证"有序展开"，未定义多个 GOTO 时航点如何分段，因此这里用
    // 最保守的均分策略，并在 notes 里说明 —— 避免悄悄丢弃或多用航点。
    const waypointGroups = distribute(waypointIds, Math.max(gotoTotal, 1));

    // 步骤编号按"每台自己的动作序号"计数，不用全局 steps.length ——
    // 后者会让编号随其它载具的步骤数跳动，难以阅读和定位。
    let actionIndex = 0;
    let gotoIndex = 0;

    for (const action of actions) {
      actionIndex += 1;
      const stepId = `${taskId}-${nodeId}-${action.toLowerCase()}-${actionIndex}`.toLowerCase();

      if (action === "TAKEOFF") {
        steps.push({
          step_id: stepId,
          action_type: "takeoff",
          node_id: nodeId,
          params: { altitude_m: takeoffAltitudeM },
        });
      } else if (action === "LAND") {
        steps.push({ step_id: stepId, action_type: "land", node_id: nodeId, params: {} });
      } else if (action === "GOTO") {
        const group = waypointGroups[gotoIndex] || [];
        gotoIndex += 1;
        if (group.length === 0) {
          // 前面已全量校验过，这里只为防御
          violations.push({ kind: "goto_without_waypoint", task_id: taskId });
          continue;
        }
        for (const waypointId of group) {
          const position = waypoints.get(waypointId);
          steps.push({
            // 一个 GOTO 展开成多个 step，用航点 ID 区分，保证唯一且可追溯
            step_id: `${stepId}-${waypointId}`.toLowerCase(),
            action_type: "goto",
            node_id: nodeId,
            params: {
              north_m: position.north_m,
              east_m: position.east_m,
              down_m: position.down_m,
            },
          });
        }
      }
    }

    if (gotoTotal > 1) {
      notes.push(
        `task ${taskId} 有 ${gotoTotal} 个 GOTO，${waypointIds.length} 个航点按顺序均分展开` +
          `（交接说明未定义多 GOTO 的分段规则，此处为保守实现）。`,
      );
    }
  }

  if (violations.length > 0) {
    throw new ProposalRejected(
      "proposal_not_executable",
      `展开阶段发现问题，已拒绝整份提案。`,
      violations,
    );
  }

  const plan = {
    plan_id: planId || `plan-${proposal.mission_id || "unnamed"}`,
    intent_id: String(proposal.mission_id || ""),
    mission_type: "flight_validation",
    scene_id: String(proposal.scene_id),
    map_version: String(proposal.map_version),
    explanation:
      "由 proposalToPlan 从算法提案展开。仅含 TAKEOFF/GOTO/LAND；" +
      "不构成巡检完成的声明。",
    steps,
  };

  // 说明文字里的载具数量必须按实际计划算，不能写死。
  //
  // 这里原先是硬编码的"三机"，而算法侧交付的单机提案只有 1 台，
  // 于是输出成"本计划只证明三机起飞"—— 对一份单机计划是错的。
  // 这类文案错误会让人误判计划范围，所以按实际 step 里的 node_id 统计。
  const vehicleIds = [...new Set(steps.map((s) => s.node_id))].sort();
  notes.push(
    `本计划只证明 ${vehicleIds.length} 台载具（${vehicleIds.join("、")}）起飞、按航点飞行、降落。` +
      "它不证明巡检、避障、间距、能源或时序安全。",
  );

  return { plan, notes };
}

function buildWaypointIndex(context) {
  const index = new Map();
  for (const waypoint of Array.isArray(context.waypoints) ? context.waypoints : []) {
    const id = nonEmptyString(waypoint?.waypoint_id) ? String(waypoint.waypoint_id) : null;
    const position = waypoint?.position_m;
    if (!id || !position) continue;
    if (!finiteNumber(position.north_m) || !finiteNumber(position.east_m) || !finiteNumber(position.down_m)) {
      continue;
    }
    index.set(id, {
      north_m: position.north_m,
      east_m: position.east_m,
      down_m: position.down_m,
    });
  }
  return index;
}

/** 把 items 按 count 组分配；多余的全部给最后一组，不足的组为空。 */
function distribute(items, count) {
  const groups = Array.from({ length: count }, () => []);
  if (count === 0) return groups;
  items.forEach((item, i) => {
    groups[Math.min(i, count - 1)].push(item);
  });
  return groups;
}
