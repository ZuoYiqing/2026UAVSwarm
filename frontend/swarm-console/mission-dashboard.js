(function attachMissionDashboard(root, factory) {
  const coverageGrid = root?.SwarmCoverageGrid
    ?? (typeof module === "object" && module.exports ? require("./coverage-grid.js") : null);
  const dashboard = factory(coverageGrid);
  if (typeof module === "object" && module.exports) module.exports = dashboard;
  if (root) root.SwarmMissionDashboard = dashboard;
})(typeof window === "undefined" ? null : window, function missionDashboard(coverageGrid) {
  const terminal = new Set(["succeeded", "failed", "timed_out", "policy_rejected", "cancelled", "canceled"]);
  const pct = value => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100 ? value : null;
  const nonnegative = value => typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
  const rows = value => Array.isArray(value) ? value.filter(item => item && typeof item === "object") : [];
  const time = value => typeof value === "string" ? Date.parse(value) : NaN;

  function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
    }
    return value;
  }

  function eventClass(type, code, record) {
    if (type === "policy_decision_event") {
      if (code === "allow") return ["允许", "green"];
      if (code === "deny") return ["拒绝", "red"];
      return ["策略裁决", "amber"];
    }
    if (type === "action_result" || type === "action_lifecycle") return ["动作结果", "muted"];
    if (type.startsWith("adapter")) return ["适配器", "violet"];
    if (type === "demo_clear") return ["撤销注入", "blue"];
    if (/recover|restor/.test(type)) return ["恢复", "blue"];
    if (/degrad|health_alert|link_lost|reassign/.test(type)
      || (type === "demo_inject" && record.kind !== "recover")
      || ["warning", "error", "critical"].includes(record.severity)) return ["降级 / 告警", "amber"];
    if (type === "demo_inject" && record.kind === "recover") return ["恢复", "blue"];
    return ["记录", "muted"];
  }

  function timeline({ events, replay, decisions, lifecycle } = {}) {
    const entries = new Map();
    const policies = new Map();
    const results = new Set();

    function add(record, source, envelope = record) {
      const type = String(record.event_type || record.type || envelope.event_type || "runtime_event").toLowerCase();
      const decision = type === "policy_decision_event"
        ? String(record.decision_code || record.decision || "").toLowerCase() : "";
      const timestamp = record.timestamp || envelope.timestamp || record.timestamps?.result_time
        || record.finished_at || record.updated_at || null;
      const node = record.node_id || envelope.node_id || null;
      const action = record.action_type || record.action || null;
      const rule = record.rule_name || record.rule_id || record.policy_rule || null;
      const reason = record.reason || record.explanation || record.primary_reason_code || record.failure_reason || null;
      const fallbackSummary = envelope.summary === `${type} event` ? null : envelope.summary;
      const key = record.event_id ? "event:" + record.event_id : "raw:" + JSON.stringify(canonical(record));
      const decisionKey = record.decision_id ? "id:" + record.decision_id
        : timestamp && record.request_id ? JSON.stringify([timestamp, record.request_id, node, action, decision]) : null;
      const [label, color] = eventClass(type, decision, { ...envelope, ...record });
      const correlation = [record.action_id, record.request_id].filter(Boolean);
      if (type === "action_result") correlation.forEach(id => results.add(id));
      const entry = {
        key, type, timestamp, node, action, decision, rule, reason, color, label, source,
        quality: pct(record.link_quality ?? record.value),
        summary: record.summary || record.message || (typeof reason === "string" ? reason : null)
          || record.completion_state || record.status || fallbackSummary || null,
        raw: record,
      };
      if (entries.has(key)) return;
      entries.set(key, entry);
      if (type === "policy_decision_event") {
        if (decisionKey) policies.set(decisionKey, entry);
        if (timestamp && record.request_id) policies.set(JSON.stringify([timestamp, record.request_id, node, action, decision]), entry);
      }
    }

    for (const event of rows(events)) {
      const raw = event.payload && typeof event.payload === "object" ? event.payload : event;
      add(raw, "/api/events", event);
    }
    for (const event of rows(replay)) add(event, "/api/replay");
    for (const decision of rows(decisions)) {
      const key = JSON.stringify([decision.timestamp, decision.request_id, decision.node_id ?? null,
        decision.action_type ?? decision.action ?? null, String(decision.decision_code || "").toLowerCase()]);
      if ((decision.decision_id && policies.has("id:" + decision.decision_id))
        || (decision.timestamp && decision.request_id && policies.has(key))) continue;
      add(decision, "/api/policy/decisions", { event_type: "policy_decision_event" });
    }
    for (const record of rows(lifecycle)) {
      if (!terminal.has(record.status) || [record.action_id, record.request_id].some(id => results.has(id))) continue;
      add(record, "/api/actions/lifecycle", { event_type: "action_lifecycle" });
    }
    return [...entries.values()].sort((a, b) => {
      const left = time(a.timestamp);
      const right = time(b.timestamp);
      return (Number.isFinite(left) ? left : Infinity) - (Number.isFinite(right) ? right : Infinity);
    });
  }

  function missionProgress(payload) {
    if (!payload || typeof payload.mission_id !== "string" || !payload.mission_id
      || ["unavailable", "stale", "unknown", "waiting", "not_configured", "invalid"].includes(payload.status)) return null;
    const coverage = payload.coverage;
    const coverageRegions = coverage?.regions ?? (coverage?.polygon ? [coverage] : null);
    const map = payload.map ?? (coverageRegions ? {
      scene_id: coverage.scene_id ?? payload.scene_id,
      map_version: coverage.map_version ?? payload.map_version,
      frame: coverage.frame,
      regions: coverageRegions,
    } : null);
    const areaCovered = nonnegative(payload.area_covered_km2);
    const areaTotal = nonnegative(payload.area_total_km2);
    const coveragePercent = areaCovered !== null && areaTotal > 0 && areaCovered <= areaTotal
      ? (areaCovered / areaTotal) * 100 : null;
    return {
      id: payload.mission_id,
      runId: payload.run_id ?? null,
      title: payload.title || payload.mission_name || payload.mission_id,
      completion: pct(payload.completion_pct),
      areaCovered,
      areaTotal,
      coveragePercent,
      coverageGrid: coverageGrid?.parse(coverage, payload) ?? null,
      waypointsReached: Number.isInteger(payload.waypoints_reached) ? nonnegative(payload.waypoints_reached) : null,
      waypointsTotal: Number.isInteger(payload.waypoints_total) ? nonnegative(payload.waypoints_total) : null,
      targetsFound: nonnegative(payload.targets_found),
      targetsTotal: nonnegative(payload.targets_total),
      degraded: typeof payload.degraded === "boolean" ? payload.degraded : null,
      vehiclesActive: nonnegative(payload.vehicles_active),
      safety: payload.safety_margin ?? null,
      map,
      regions: rows(map?.regions ?? payload.regions ?? payload.mission_areas),
      assignments: rows(payload.assignments ?? payload.vehicle_assignments ?? payload.vehicles),
      status: payload.status ?? null,
      mode: payload.mode ?? null,
      completionBasis: payload.completion_basis ?? null,
      timestamp: payload.source_timestamp ?? payload.timestamp ?? payload.updated_at ?? null,
    };
  }

  const executionStates = new Set(["running", "completed", "failed", "blocked"]);
  const hasId = value => typeof value === "string" && value.trim().length > 0;

  function waypointCountsValid({ waypoints_reached: reached, waypoints_total: total }) {
    return Number.isSafeInteger(reached) && Number.isSafeInteger(total) && reached >= 0 && reached <= total;
  }

  function runtimeMissionProgress(payload) {
    if (payload?.contract_version !== "1.0" || payload.source !== "runtime_plan_executor" || payload.mode !== "LIVE"
      || !executionStates.has(payload.status) || !Number.isFinite(time(payload.source_timestamp))
      || ![payload.mission_id, payload.run_id, payload.scene_id, payload.map_version].every(hasId)) return null;

    const verifiedWaypoints = payload.completion_basis === "verified_waypoints"
      && waypointCountsValid(payload) && payload.waypoints_total > 0
      && pct(payload.completion_pct) !== null
      && Math.abs(payload.completion_pct - 100 * payload.waypoints_reached / payload.waypoints_total) <= 0.005001;
    const report = payload.coverage;
    const coverage = report?.scene_id === payload.scene_id && report.map_version === payload.map_version
      && report.frame === "scene_ned" && hasId(report.area_id)
      && (payload.area_id == null || payload.area_id === report.area_id) ? report : null;
    const hasAreaEvidence = coverage && Number.isSafeInteger(coverage.sample_count) && coverage.sample_count > 0
      && coverage.area_total_km2 === payload.area_total_km2 && coverage.area_covered_km2 === payload.area_covered_km2
      && nonnegative(payload.area_covered_km2) !== null && nonnegative(payload.area_total_km2) > 0
      && payload.area_covered_km2 <= payload.area_total_km2;
    const progress = {
      ...missionProgress({
        mission_id: payload.mission_id, run_id: payload.run_id, status: payload.status, mode: payload.mode,
        scene_id: payload.scene_id, map_version: payload.map_version, source_timestamp: payload.source_timestamp,
        completion_basis: verifiedWaypoints ? "verified_waypoints" : null,
        completion_pct: verifiedWaypoints ? payload.completion_pct : null,
        waypoints_reached: verifiedWaypoints ? payload.waypoints_reached : null,
        waypoints_total: verifiedWaypoints ? payload.waypoints_total : null,
        area_total_km2: hasAreaEvidence ? payload.area_total_km2 : null,
        area_covered_km2: hasAreaEvidence ? payload.area_covered_km2 : null,
        coverage: hasAreaEvidence ? coverage : coverage && { ...coverage, grid: null },
        vehicles: rows(payload.vehicles).filter(row => hasId(row.node_id)).map(row => ({
          node_id: row.node_id,
          active: row.active,
          ...(verifiedWaypoints && waypointCountsValid(row)
            ? { waypoints_reached: row.waypoints_reached, waypoints_total: row.waypoints_total } : {}),
        })),
        vehicles_active: payload.vehicles_active, degraded: payload.degraded,
        safety_margin: payload.safety_margin, targets_found: payload.targets_found, targets_total: payload.targets_total,
      }),
      sceneId: payload.scene_id,
      mapVersion: payload.map_version,
    };
    if (progress.coveragePercent !== null) {
      // The Runtime reports unrounded rates. Allow floating-point noise in the area ratio.
      const rates = [payload.coverage_pct, coverage.completion_pct];
      const conflictingRate = rates.some(rate => rate != null
        && (pct(rate) === null || Math.abs(rate - progress.coveragePercent) > 1e-9));
      const invalidGrid = coverage.grid != null && progress.coverageGrid === null;
      if (conflictingRate || invalidGrid) {
        progress.areaTotal = null;
        progress.areaCovered = null;
        progress.coveragePercent = null;
        progress.coverageGrid = null;
      }
    }
    return progress;
  }

  function assignmentProgress(assignment) {
    const direct = pct(assignment?.completion_pct ?? assignment?.progress_pct);
    if (direct !== null) return direct;
    const reached = nonnegative(assignment?.waypoints_reached);
    const total = nonnegative(assignment?.waypoints_total);
    return reached !== null && total > 0 ? pct(100 * reached / total) : null;
  }

  function linkScores(snapshot, telemetry, fleet) {
    const byId = new Map();
    const telemetryById = new Map(rows(telemetry?.nodes).map(node => [node.node_id, node]));
    const snapshotById = new Map(rows(snapshot?.vehicles).map(vehicle => [vehicle.id, vehicle]));
    for (const vehicle of rows(fleet)) {
      if (vehicle.enabled === false) continue;
      const snapshotRow = snapshotById.get(vehicle.id);
      const node = telemetryById.get(vehicle.id);
      const value = pct(snapshotRow?.link_quality ?? snapshotRow?.telemetry?.link_quality)
        ?? pct(node?.link_quality);
      if (value !== null) byId.set(vehicle.id, value);
    }
    return byId;
  }

  function trend(before, after) {
    if (before == null || after == null) return "";
    if (before < after) return "▲";
    if (before > after) return "▼";
    return "→";
  }

  function nedPoint(value) {
    if (Array.isArray(value) && value.length >= 2) {
      const [north, east] = value;
      return Number.isFinite(north) && Number.isFinite(east) ? { north, east } : null;
    }
    const north = value?.north_m ?? value?.x_m ?? value?.x;
    const east = value?.east_m ?? value?.y_m ?? value?.y;
    return Number.isFinite(north) && Number.isFinite(east) ? { north, east } : null;
  }

  function regionPoints(region) {
    const polygon = region.polygon_ned_m ?? region.polygon_m ?? region.polygon ?? region.vertices;
    if (Array.isArray(polygon) && polygon.length >= 3) {
      const points = polygon.map(nedPoint);
      if (points.every(Boolean)) return points;
    }
    const center = nedPoint(region.center);
    if (region.shape !== "circle" || !center || !Number.isFinite(region.radius_m) || region.radius_m <= 0) return null;
    return Array.from({ length: 32 }, (_, i) => {
      const angle = i * 2 * Math.PI / 32;
      return { north: center.north + region.radius_m * Math.cos(angle), east: center.east + region.radius_m * Math.sin(angle) };
    });
  }

  function mapProjection(points, minimumWidth = 1) {
    const northMin = Math.min(...points.map(p => p.north));
    const northMax = Math.max(...points.map(p => p.north));
    const eastMin = Math.min(...points.map(p => p.east));
    const eastMax = Math.max(...points.map(p => p.east));
    // Keep one scale for both axes. The rendering surface uses the same aspect ratio.
    const width = Math.max(eastMax - eastMin, (northMax - northMin) * 1.6, minimumWidth) * 1.20;
    const height = width / 1.6;
    const centerE = (eastMin + eastMax) / 2;
    const centerN = (northMin + northMax) / 2;
    return point => ({ x: 50 + (point.east - centerE) * 100 / width, y: 50 - (point.north - centerN) * 100 / height });
  }

  function sharedVehiclePositions(snapshot, scene) {
    if (!scene || scene !== snapshot?.scene_id) return [];
    return rows(snapshot.vehicles).flatMap(vehicle => {
      const spatial = vehicle.spatial;
      const position = spatial?.scene_pose?.frame === "scene_ned" && nedPoint(spatial.scene_pose.position_m);
      if (!position || spatial.public_position_usable !== true || vehicle.connected !== true
        || vehicle.telemetry?.stale !== false || (spatial.scene_id ?? scene) !== scene || !vehicle.id) return [];
      return [{ id: vehicle.id, position, version: spatial.map_version ?? snapshot.map_version }];
    });
  }

  function fleetMap(snapshot) {
    const scene = snapshot?.scene_id;
    const positions = sharedVehiclePositions(snapshot, scene);
    if (!positions.length) return null;
    const version = positions[0].version;
    if (!version || positions.some(row => row.version !== version)) return null;
    const project = mapProjection(positions.map(row => row.position), 20);
    return { scene, markers: positions.map(({ id, position }) => ({ id, ...project(position) })) };
  }

  function missionMap(progress, snapshot) {
    if (!progress) return null;
    const scene = progress.map?.scene_id;
    const frame = progress.map?.frame;
    const regions = progress.regions
      .filter(region => (region.frame ?? frame) === "scene_ned" || Array.isArray(region.polygon_ned_m))
      .map(region => ({ region, points: regionPoints(region) })).filter(item => item.points);
    if (!regions.length) return null;
    const project = mapProjection(regions.flatMap(item => item.points));
    const vehicles = frame === "scene_ned" ? sharedVehiclePositions(snapshot, scene) : [];
    return {
      regions: regions.map(({ region, points }) => ({ ...region, projected: points.map(project) })),
      coverageGrid: progress.coverageGrid && scene === progress.coverageGrid.sceneId
        && progress.map.map_version === progress.coverageGrid.mapVersion
        && regions.some(({ region }) => region.area_id === progress.coverageGrid.areaId)
        ? coverageGrid.project(progress.coverageGrid, project) : null,
      markers: vehicles.flatMap(({ id, position, version }) => {
        if (progress.map?.map_version && progress.map.map_version !== version) return [];
        const point = project(position);
        return point.x >= 0 && point.x <= 100 && point.y >= 0 && point.y <= 100
          ? [{ id, ...point }] : [];
      }),
    };
  }

  const demoChapters = [
    { start: 0, title: "三机分区", detail: "三架载具分别负责西区、中区和东区。" },
    { start: 18, title: "链路降级与接续", detail: "查看 UAV-02 的策略裁决及其他节点接续中区的记录。" },
    { start: 96, title: "恢复与结果", detail: "查看重新入队的依据，以及演习结束时的覆盖结果。" },
  ];
  const demoChapterSeconds = 20;
  const demoDuration = demoChapterSeconds * demoChapters.length;
  const scriptEnd = 180;

  // Three 20-second chapters play the original offline evidence in order.
  function demoFrame(elapsed) {
    const position = Math.max(0, Math.min(demoDuration, elapsed));
    const chapterIndex = Math.min(demoChapters.length - 1, Math.floor(position / demoChapterSeconds));
    const chapter = demoChapters[chapterIndex];
    const end = demoChapters[chapterIndex + 1]?.start ?? scriptEnd;
    const fraction = (position - chapterIndex * demoChapterSeconds) / demoChapterSeconds;
    const second = Math.min(end - 1, chapter.start + Math.floor((end - chapter.start) * fraction));
    const since = offset => new Date(Date.UTC(2026, 10, 12, 2, 0, offset)).toISOString();
    const progressAt = s => Math.min(88, Math.floor(s < 18 ? 35 * s / 18 : 35 + (s - 18) * 53 / 134));
    const qualityAt = s => s < 18 ? 95 : s < 24 ? 42 : s < 96 ? 18 : 89;
    const ids = ["UAV-01", "UAV-02", "UAV-03"];
    const missionId = "DEMO-RECON-001";
    const regionSpecs = [
      { id:"west", label:"西区", box:[0, 0, 1500, 1500], start:0, end:138 },
      { id:"center", label:"中区", box:[0, 1500, 1500, 3000], start:10, end:152 },
      { id:"east", label:"东区", box:[0, 3000, 1500, 4500], start:0, end:152 },
      { id:"reserve", label:"北侧余区", box:[1500, 0, 1850, 4500], start:112, end:180 },
    ];
    function rect(n0, e0, n1, e1) { return [[n0,e0],[n0,e1],[n1,e1],[n1,e0]]; }
    function regionsAt(s) {
      return regionSpecs.flatMap(({id,label,box,start,end}) => {
        const [n0,e0,n1,e1] = box;
        const span = Math.max(0, Math.min(1, (s-start) / (end-start)));
        const boundary = e0 + (e1-e0) * span;
        const base = {label, area_id:id};
        return [
          ...(span > 0 ? [{...base, area_id:id+"-covered", coverage_status:"covered", polygon_ned_m:rect(n0,e0,n1,boundary)}] : []),
          ...(span < 1 ? [{...base, coverage_status:"uncovered", polygon_ned_m:rect(n0,boundary,n1,e1)}] : []),
        ];
      });
    }
    function audit(at, type, node, data = {}) {
      return { type, event_id:"demo-"+at+"-"+type, timestamp:since(at), mission_id:missionId,
        node_id:node, data_mode:"DEMO", ...data };
    }
    const hold = {request_id:"demo-hold-uav02",action_id:"demo-act-hold",trace_id:"demo-trace-hold",action_type:"hold_position"};
    const eventPairs = [
      [1,audit(1,"mission_started",null,{summary:"区域侦察开始，任务分配给三架载具"})],
      [19,audit(19,"link_degraded","UAV-02",{link_quality:42,summary:"通信质量下降到 42 / 100"})],
      [24,audit(24,"demo_inject","UAV-02",{kind:"link_degraded",value:18,summary:"演习链路读数降到 18 / 100"})],
      [26,audit(26,"policy_decision_event","UAV-02",{...hold,decision_code:"allow",rule_name:"degraded_link_hold",link_quality:18,reason:"链路低于演习阈值，允许保持位置并重新分配任务"})],
      [28,audit(28,"adapter_execution_started","UAV-02",{...hold,adapter:"demo",summary:"演习适配器开始保持位置"})],
      [32,audit(32,"action_result","UAV-02",{...hold,status:"succeeded",completion_state:"demo_hold_completed",summary:"保持位置演习结果已记录"})],
      [41,audit(41,"policy_decision_event","UAV-02",{request_id:"demo-deny-resume",action_type:"resume_assignment",decision_code:"deny",rule_name:"link_rejoin_threshold",reason:"恢复条件尚未满足，拒绝重新入队"})],
      [45,audit(45,"task_reassigned",null,{summary:"中区任务转交 UAV-01 与 UAV-03",assignment_node_ids:["UAV-01","UAV-03"]})],
      [96,audit(96,"demo_recovered","UAV-02",{link_quality:89,summary:"链路读数恢复到 89 / 100"})],
      [101,audit(101,"policy_decision_event","UAV-02",{request_id:"demo-rejoin",action_type:"resume_assignment",decision_code:"allow",rule_name:"link_rejoin_threshold",link_quality:89,reason:"恢复条件满足，允许重新入队"})],
      [152,audit(152,"mission_partial_completion",null,{completion_pct:88,summary:"演习结束，区域部分覆盖，全员状态正常"})],
    ];
    const vehicles = ids.map((id,i) => ({
      id, connected:true, link_quality:i === 1 ? qualityAt(second) : 97-i,
      telemetry:{stale:false}, spatial:{public_position_usable:true,scene_pose:{frame:"scene_ned",
        position_m:{x:350 + Math.min(1100, (i === 1 && second >= 26 && second < 96 ? 26 : second)*8),
          y:480+1500*i+(i !== 1 && second >= 45 && second < 96 ? (i === 0 ? 620 : -620) : 0),z:-20}}}
    }));
    const vehicleSnapshot = {scene_id:"demo-recon",vehicles};
    const assignments = ids.map((node_id,i) => ({
      node_id, region_label: i === 1 && second >= 45 && second < 101 ? "保持位置"
        : i !== 1 && second >= 45 && second < 101 ? regionSpecs[i].label+" / 中区" : regionSpecs[i].label,
      completion_pct: i === 1 && second >= 26 && second < 101 ? progressAt(26) : progressAt(second),
      status:second >= 152 ? "演习结束" : i === 1 && second >= 26 && second < 101 ? "保持位置" : "侦察中",
    }));
    const regions = regionsAt(Math.min(second,152));
    const areaCovered = regions.filter(region => region.coverage_status === "covered").reduce((area,region) => {
      const [first,,third] = region.polygon_ned_m;
      return area + (third[0]-first[0])*(third[1]-first[1])/1e6;
    },0);
    return {
      chapter, chapterIndex, second,
      fleet:ids.map(id => ({id,connected:true,stale:false})), vehicleSnapshot,
      actionCount:second < 152 ? (second >= 26 && second < 32 ? 3 : second >= 32 && second < 101 ? 2 : 3) : 0,
      progress:missionProgress({
        mission_id:missionId,title:"三机区域侦察",status:second >= 152 ? "partially_completed" : "executing",
        completion_pct:progressAt(second),area_covered_km2:areaCovered,area_total_km2:8.325,
        targets_found:Math.min(4,Math.floor(second/31)),targets_total:5,degraded:second >= 19 && second < 96,
        safety_margin:second >= 26 && second < 32 ? "处置中" : "正常",assignments,
        map:{scene_id:"demo-recon",frame:"scene_ned",regions},source_timestamp:since(second),source:"built_in_demo",
      }),
      timeline:timeline({ replay:eventPairs.filter(([at]) => at <= second).map(([,event]) => event) }),
      links:linkScores(vehicleSnapshot, null, ids.map(id => ({id}))),
      linkTrend:second >= 18 && second < 36 ? "▼" : second >= 96 && second < 108 ? "▲" : "",
      progressTrend:second > 0 && second < 152 ? "▲" : "",
      safetyTrend:second >= 26 && second < 32 ? "▼" : second >= 32 && second < 36 ? "▲" : "",
    };
  }

  return { pct, rows, timeline, missionProgress, runtimeMissionProgress, assignmentProgress, linkScores, trend, missionMap, fleetMap,
    demoChapters, demoChapterSeconds, demoDuration, demoFrame };
});
