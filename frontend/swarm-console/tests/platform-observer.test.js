const test = require("node:test");
const assert = require("node:assert/strict");
const { createObserver, validateTask } = require("../platform-observer.js");
const { createFixture, contract } = require("./fixtures/platform-read-fixture.js");

test("Runtime fixture task statuses and real GET shapes are accepted without inventing task APIs", async () => {
  const fixture = createFixture();
  for (const status of contract.task_states) assert.equal(validateTask({...fixture.task,status}).status, status);
  const observer = createObserver(fixture.api, {now:() => "fixture-local-receive-time"});
  await observer.refresh();
  assert.equal(observer.state.observation, "live");
  assert.equal(observer.state.cursor, 2);
  assert.equal(observer.state.task.execution_id, fixture.task.execution_id);
  assert.equal(observer.state.lastReceivedAt, "fixture-local-receive-time");
  assert.equal(observer.state.status.execution_mode, "fake");
  assert.ok(fixture.calls.every((call) => call.method === "GET"));
});

test("503 preserves task/cursor; reconnection collects missed events once and never POSTs", async () => {
  const f = createFixture();
  const o = createObserver(f.api);
  await o.refresh();
  const lastReceived = o.state.lastReceivedAt;
  f.offline = true;
  await o.refresh();
  assert.equal(o.state.observation, "stale");
  assert.equal(o.state.task.status, "executing");
  assert.equal(o.state.cursor, 2);
  assert.equal(o.state.lastReceivedAt, lastReceived);
  f.offline = false;
  f.task.status = "succeeded";
  f.task.current_step = "land-1";
  f.status.active_task = null;
  f.status.ground_link.state = "lost";
  f.events.push(f.event(3), f.event(4,{event_type:"task_succeeded"}));
  f.status.event_seq = 4;
  await o.refresh();
  await o.refresh();
  assert.equal(o.state.observation, "live");
  assert.equal(o.state.task.status, "succeeded");
  assert.equal(o.state.status.ground_link.state, "lost");
  assert.deepEqual(o.state.events.map((event) => event.seq), [1,2,3,4]);
  assert.ok(f.calls.some((call) => call.path.includes("after_seq=2&store_id=fixture-store-a")));
  assert.ok(f.calls.every((call) => call.method === "GET"));
});

test("boot restart retains the same store cursor and displays recovery_required", async () => {
  const f = createFixture(); const o = createObserver(f.api);
  await o.refresh();
  f.status.boot_id = "fixture-boot-b";
  f.task.status = "recovery_required";
  f.status.active_task = structuredClone(f.task);
  f.events.push(f.event(3,{event_type:"task_recovery_required"}));
  f.status.event_seq = 3;
  f.calls.length = 0;
  await o.refresh();
  assert.equal(o.state.restarted, true);
  assert.equal(o.state.task.status, "recovery_required");
  assert.ok(f.calls.some((call) => call.path.includes("after_seq=2&store_id=fixture-store-a")));
  assert.ok(!f.calls.some((call) => call.path.includes("after_seq=0")));
});

test("store replacement scopes cursor/events and preserves the previous source separately", async () => {
  const f = createFixture(); const o = createObserver(f.api);
  await o.refresh();
  f.status.store_id = "fixture-store-b";
  f.status.boot_id = "fixture-boot-b";
  f.task.execution_id = "fixture-execution-b";
  f.status.active_task = structuredClone(f.task);
  f.events = [f.event(1)]; f.status.event_seq = 1;
  await o.refresh();
  assert.equal(o.state.storeChanged, true);
  assert.equal(o.state.cursor, 1);
  assert.equal(o.state.task.execution_id, "fixture-execution-b");
  assert.equal(o.state.previous.task.execution_id, "fixture-execution-a");
  assert.deepEqual(o.state.events.map((event) => event.store_id), ["fixture-store-b"]);
});

test("bounded pagination remains syncing until the checkpoint is collected", async () => {
  const f = createFixture({count:7,pageSize:2});
  const o = createObserver(f.api,{pageBudget:1});
  for (const cursor of [2,4,6]) {
    await o.refresh();
    assert.equal(o.state.cursor, cursor);
    assert.equal(o.state.observation, "syncing");
  }
  await o.refresh();
  assert.equal(o.state.cursor, 7);
  assert.equal(o.state.observation, "live");
  assert.equal(new Set(o.state.events.map((event) => event.seq)).size, 7);
});

test("repeated event pages and duplicate event IDs do not duplicate the display window", async () => {
  const f = createFixture(); const o = createObserver(f.api);
  await o.refresh();
  f.api.platformEvents = async () => ({contract_version:"1.0",store_id:f.status.store_id,
    events:[f.event(1),f.event(2),f.event(2)],next_seq:2,checkpoint_seq:2,history_gap:false,has_more:false});
  await o.refresh();
  assert.equal(o.state.observation, "live");
  assert.deepEqual(o.state.events.map((event) => event.seq), [1,2]);
});

for (const failure of ["history_gap", "sequence_gap", "wrong_store", "wrong_node", "bad_checkpoint", "409", "task_404", "wrong_execution"]) {
  test(`${failure}: retain confirmed task and cursor instead of skipping or declaring failure`, async () => {
    const f = createFixture(); const o = createObserver(f.api);
    await o.refresh();
    const task = o.state.task;
    if (failure === "task_404") f.api.platformTask = async () => { throw Object.assign(new Error("task_not_found"),{status:404}); };
    else if (failure === "wrong_execution") f.task.execution_id = "fixture-unrelated-execution";
    else {
      const original = f.api.platformEvents;
      f.api.platformEvents = async (...args) => {
        if (failure === "409") throw Object.assign(new Error("event_cursor_ahead"),{status:409});
        const page = await original(...args);
        if (failure === "history_gap") page.history_gap = true;
        if (failure === "sequence_gap") { page.events=[f.event(4)];page.next_seq=4;page.checkpoint_seq=4; }
        if (failure === "wrong_store") page.store_id="other-store";
        if (failure === "wrong_node") { page.events=[f.event(3,{node_id:"UAV-01"})];page.next_seq=3;page.checkpoint_seq=3; }
        if (failure === "bad_checkpoint") page.next_seq=999;
        return page;
      };
    }
    await o.refresh();
    assert.equal(o.state.observation, "stale");
    assert.equal(o.state.task, task);
    assert.equal(o.state.task.status, "executing");
    assert.equal(o.state.cursor, 2);
    assert.match(o.state.error, /.+/);
  });
}

test("task terminal state cannot regress on a delayed response", async () => {
  const f = createFixture(); const o = createObserver(f.api);
  f.task.status="succeeded"; f.status.active_task=null;
  await o.refresh();
  f.task.status="executing";
  await o.refresh();
  assert.equal(o.state.task.status,"succeeded");
  assert.equal(o.state.observation,"stale");
});

test("changing store during task lookup cannot commit a task from a different source", async () => {
  const f = createFixture(); const o = createObserver(f.api);
  await o.refresh();
  const original = f.api.platformTask;
  f.api.platformTask = async (...args) => {
    const response = await original(...args);
    f.status.store_id="replacement-during-query";
    return response;
  };
  await o.refresh();
  assert.equal(o.state.storeId,"fixture-store-a");
  assert.equal(o.state.cursor,2);
  assert.equal(o.state.observation,"stale");
});

test("overlapping refreshes coalesce; disposed observer discards late source responses", async () => {
  const f = createFixture(); let complete;
  f.api.platformStatus = () => new Promise((resolve) => {complete=resolve;});
  const o = createObserver(f.api);
  const a=o.refresh(), b=o.refresh();
  assert.equal(a,b);
  o.dispose(); complete(f.status);
  await a;
  assert.equal(o.state.status,null);
  assert.equal(o.state.cursor,0);
});

test("an empty platform store stays distinct from task success and cold 503 stays unknown", async () => {
  const f = createFixture({count:0}); f.status.active_task=null;
  const o = createObserver(f.api);
  await o.refresh();
  assert.equal(o.state.observation,"live");
  assert.equal(o.state.task,null);
  assert.ok(!f.calls.some((call) => call.path.includes("/tasks/")));
  const cold=createObserver({...f.api,platformStatus:async()=>{throw new Error("platform_link_unavailable");}});
  await cold.refresh();
  assert.equal(cold.state.observation,"unknown");
  assert.equal(cold.state.task,null);
});
