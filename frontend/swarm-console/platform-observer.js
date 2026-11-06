/* Read-only platform v1.0 observer. No task submission, heartbeat or credentials. */
(function attach(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.SwarmPlatformObserver = api;
})(typeof window !== "undefined" ? window : undefined, function createModule() {
  const TASK_STATES = new Set(["accepted", "executing", "succeeded", "failed", "cancelled", "recovery_required"]);
  const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);
  const text = (value) => typeof value === "string" && value.length > 0;
  const sequence = (value) => Number.isSafeInteger(value) && value >= 0;
  function requireField(condition, message) {
    if (!condition) throw new Error(`平台契约：${message}`);
  }
  function taskIdentity(task) {
    return [task.node_id, task.task_id, task.task_version, task.execution_id, task.request_id, task.trace_id].join("\n");
  }
  function validateTask(task, expected) {
    requireField(task && task.contract_version === "1.0" && text(task.node_id)
      && text(task.task_id) && Number.isSafeInteger(task.task_version) && task.task_version > 0
      && text(task.execution_id) && text(task.request_id) && text(task.trace_id)
      && TASK_STATES.has(task.status), "任务身份或状态无效");
    if (expected) requireField(taskIdentity(task) === taskIdentity(expected), "任务版本或执行实例不匹配");
    return task;
  }
  function validateStatus(status) {
    requireField(status && status.contract_version === "1.0" && text(status.node_id)
      && text(status.store_id) && text(status.boot_id) && sequence(status.event_seq)
      && ["fake", "sitl"].includes(status.execution_mode)
      && ["healthy", "lost"].includes(status.ground_link?.state)
      && Object.hasOwn(status, "active_task"), "状态身份、地面链路或检查点无效");
    if (status.active_task !== null) {
      validateTask(status.active_task);
      requireField(status.active_task.node_id === status.node_id, "状态和任务节点不匹配");
    }
    return status;
  }
  function consumePage(draft, page, nodeId) {
    requireField(page && page.contract_version === "1.0" && page.store_id === draft.storeId
      && Array.isArray(page.events) && sequence(page.next_seq) && sequence(page.checkpoint_seq)
      && typeof page.has_more === "boolean" && page.history_gap === false, "事件页身份无效或存在历史缺口");
    const before = draft.cursor;
    let lastInPage = -1;
    for (const event of page.events) {
      requireField(event && event.contract_version === "1.0" && event.store_id === draft.storeId
        && event.node_id === nodeId && sequence(event.seq) && event.seq > 0
        && text(event.event_type) && text(event.task_id) && text(event.execution_id)
        && text(event.request_id) && text(event.trace_id)
        && Number.isSafeInteger(event.task_version) && event.task_version > 0
        && text(event.timestamp) && Number.isFinite(Date.parse(event.timestamp)), "事件字段或来源无效");
      requireField(event.seq >= lastInPage, "事件乱序");
      lastInPage = event.seq;
      // 已提交游标之前的重复页和重复事件不产生新条目。
      if (event.seq <= draft.cursor) continue;
      requireField(event.seq === draft.cursor + 1, "事件序号存在缺口");
      draft.events.push(event);
      draft.cursor = event.seq;
    }
    requireField(page.next_seq === draft.cursor && page.checkpoint_seq >= draft.cursor
      && page.has_more === (draft.cursor < page.checkpoint_seq)
      && (!page.has_more || draft.cursor > before), "事件游标不一致或分页未前进");
    requireField(page.has_more || draft.cursor === page.checkpoint_seq, "事件页遗漏检查点之前的事件");
    draft.events = draft.events.slice(-100); // 窗口不是完整审计历史；游标仍累计。
    draft.hasMore = page.has_more;
  }

  function createObserver(api, { now = () => new Date().toISOString(), pageBudget = 5 } = {}) {
    const state = {
      status: null, task: null, events: [], storeId: null, cursor: 0,
      observation: "unknown", lastReceivedAt: null, error: null,
      hasMore: false, storeChanged: false, restarted: false, previous: null,
    };
    let pending = null;
    let disposed = false;
    function markStale(error) {
      if (disposed) return;
      state.observation = state.status ? "stale" : "unknown";
      state.error = error?.message || "平台观测不可用";
    }
    async function synchronize() {
      try {
        const status = validateStatus(await api.platformStatus());
        if (disposed) return state;
        const changed = state.storeId !== null && state.storeId !== status.store_id;
        requireField(changed || !state.status || state.status.node_id === status.node_id, "同一存储的节点发生变化");
        const sameStore = state.storeId === status.store_id;
        requireField(!sameStore || status.event_seq >= state.cursor, "快照检查点落后已提交游标，不能清零跳过");
        const draft = {
          ...state, status, storeId: status.store_id,
          cursor: sameStore ? state.cursor : 0,
          events: sameStore ? [...state.events] : [],
          task: sameStore ? state.task : null,
          storeChanged: state.storeChanged || changed,
          restarted: sameStore && (state.restarted || state.status?.boot_id !== status.boot_id),
          previous: changed ? {status:state.status,task:state.task,cursor:state.cursor} : state.previous,
        };
        // 从已提交游标补收；首次打开从 0 重建，只读，不播放为新指令。
        for (let page = 0; page < pageBudget; page++) {
          const payload = await api.platformEvents(draft.cursor, draft.storeId);
          if (disposed) return state;
          consumePage(draft, payload, status.node_id);
          if (!draft.hasMore) break;
        }
        const latestEvent = draft.events.at(-1);
        const expected = latestEvent && latestEvent.seq > status.event_seq
          ? latestEvent : status.active_task || latestEvent || draft.task;
        if (expected) {
          const result = await api.platformTask(expected.task_id);
          if (disposed) return state;
          const task = validateTask(result?.task, expected);
          if (draft.task && taskIdentity(task) === taskIdentity(draft.task) && TERMINAL.has(draft.task.status)) {
            requireField(task.status === draft.task.status, "任务终态不能被旧响应回退");
          }
          draft.task = task;
        }
        // task GET 没有 store_id 参数；再核对来源，防止请求期间换库或重启而混入任务。
        const fence = validateStatus(await api.platformStatus());
        if (disposed) return state;
        requireField(fence.store_id === status.store_id && fence.boot_id === status.boot_id
          && fence.node_id === status.node_id && fence.event_seq >= draft.cursor, "对账期间平台来源改变或检查点回退");
        draft.status = fence;
        draft.hasMore = draft.hasMore || draft.cursor < fence.event_seq;
        draft.observation = draft.hasMore ? "syncing" : "live";
        draft.lastReceivedAt = now();
        draft.error = null;
        Object.assign(state, draft);
      } catch (error) {
        // 503、409、404、契约错误都只使观测失效，不改写已确认任务或提交游标。
        markStale(error);
      }
      return state;
    }
    return {
      state, markStale,
      refresh() {
        if (disposed) return Promise.resolve(state);
        if (!pending) pending = synchronize().finally(() => { pending = null; });
        return pending;
      },
      dispose() { disposed = true; },
    };
  }
  return { createObserver, validateStatus, validateTask };
});
