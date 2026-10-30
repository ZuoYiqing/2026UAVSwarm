// Consumer-side dynamic responses built from Runtime's supplied contract fixture.
// Synthetic IDs/times, fake mode only: these are not flight evidence.
const contract = require("./platform_autonomy_v1.json");
const clone = (value) => structuredClone(value);

function createFixture({ count = 2, pageSize = 100 } = {}) {
  const calls = [];
  const task = {
    ...clone(contract.task_request), execution_id:"fixture-execution-a", execution_mode:"fake",
    status:"executing", current_step:"hold-1", step_outcomes:[], failure_reason:null,
    created_at:contract.fixture_clock, updated_at:contract.fixture_clock,
  };
  const status = {
    ...contract.status_response_projection,
    boot_id:"fixture-boot-a", store_id:"fixture-store-a", run_id:"fixture-run-a",
    ground_link:{state:"healthy",last_received_at:contract.fixture_clock,age_ms:0},
    active_task:clone(task), event_seq:count,
    platform_observation:{source:"fake",stale:false,sample_timestamp:contract.fixture_clock,armed:true},
    safe_to_stop:false,
  };
  const fixture = {contract,calls,task,status,pageSize,events:[],offline:false};
  fixture.event = (seq, changes = {}) => ({
    contract_version:contract.contract_version, seq, store_id:fixture.status.store_id,
    event_type:"task_executing", timestamp:contract.fixture_clock,
    ...Object.fromEntries(["node_id","task_id","task_version","execution_id","request_id","trace_id"]
      .map((name) => [name,fixture.task[name]])), data:{status:fixture.task.status}, ...changes,
  });
  fixture.events = Array.from({length:count}, (_, index) => fixture.event(index + 1));
  const record = (path) => {
    calls.push({method:"GET",path});
    if (fixture.offline) throw Object.assign(new Error("platform_link_unavailable"), {
      kind:"http",status:503,payload:{error:"platform_link_unavailable",observation_status:"unknown"},
    });
  };
  fixture.api = {
    async platformStatus() { record("/api/platform/status"); return clone(fixture.status); },
    async platformTask(id) {
      record(`/api/platform/tasks/${id}`);
      return {task:clone(fixture.task)};
    },
    async platformEvents(after, store) {
      record(`/api/platform/events?after_seq=${after}&store_id=${store}`);
      if (store !== fixture.status.store_id || after > fixture.status.event_seq) {
        throw Object.assign(new Error("event_store_changed_or_cursor_ahead"), {kind:"http",status:409});
      }
      const events = fixture.events.filter((event) => event.seq > after).slice(0, fixture.pageSize);
      const next = events.at(-1)?.seq ?? after;
      return {contract_version:"1.0",store_id:store,events:clone(events),next_seq:next,
        checkpoint_seq:fixture.status.event_seq,history_gap:false,has_more:next < fixture.status.event_seq};
    },
  };
  return fixture;
}
module.exports = {createFixture,contract};
