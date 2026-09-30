import test from "node:test";
import assert from "node:assert/strict";
import { VehicleSnapshotState, RuntimeVehicleSnapshotPoller } from "../src/vehicle-snapshot-state.js";
import { QINGLAN_SCENE, RECON_SCENE } from "../src/scene-alignment.js";
import { createParentMessageHandler } from "../src/parent-bridge.js";
import { publicSnapshot } from "./fixtures/public-snapshot.js";

const epoch = Date.parse("2026-09-10T00:00:00Z");
function createState(scene = RECON_SCENE) { return new VehicleSnapshotState({ now: () => epoch, scene }); }

test("public scene NED keeps 0/+8/-8 East offsets and flips Down to Up exactly once", () => {
  const state = createState();
  const raw = publicSnapshot({ time: epoch, positions: [[0,0,0],[0,8,-3],[0,-8,0]] });
  raw.vehicles[1].spawn_offset_m = { x: 0, y: 8, z: 0 };
  state.ingest(raw);
  assert.deepEqual([...state.vehicles.values()].map(v => [v.position.eastM,v.position.northM,v.position.upM]), [[0,0,-0],[8,0,3],[-8,0,-0]]);
  assert.equal(state.getVehicle("UAV-02").attitude.yawDeg, 90);
});

test("scene/version/origin/calibration/rotation mismatches keep LIVE nodes unpositioned", () => {
  const mutations = [
    r => { r.scene_id = QINGLAN_SCENE.scene_id; },
    r => { r.vehicles[0].spatial.map_version = "wrong"; },
    r => { r.vehicles[0].spatial.scene_origin.east_m = 8; },
    r => { r.vehicles[0].spatial.altitude_reference = "AGL"; },
    r => { r.vehicles[0].spatial.units = "cm"; },
    r => { delete r.vehicles[0].spatial.axis_alignment; },
    r => { r.vehicles[0].spatial.axis_alignment = "yaw_rotated"; },
    r => { r.vehicles[0].spatial.frame_transform = { yaw_deg: 90 }; },
    r => { r.vehicles[0].spatial.origin_continuity = "unknown"; },
    r => { r.vehicles[0].spatial.calibration_age_ms = 6000; },
    r => { r.vehicles[0].spatial.public_position_usable = false; },
    r => { r.vehicles[0].spatial.scene_pose.position_m.x = NaN; },
    r => { delete r.vehicles[0].spatial; },
  ];
  for (const mutate of mutations) {
    const raw = publicSnapshot({ time: epoch }); mutate(raw);
    const state = createState(); state.ingest(raw);
    const node = state.getVehicle("UAV-01");
    assert.equal(node.position, null); assert.equal(node.positionUsable, false);
    assert.equal(node.alignment.aligned, false); assert.ok(node.alignment.reason);
    assert.equal(state.mode, "live");
  }
});

test("stale/mismatched B freezes trusted A; fresh C recovers and full state removes absent nodes", () => {
  const state = createState(); state.ingest(publicSnapshot({ time: epoch }));
  const first = state.getVehicle("UAV-02").position;
  const b = publicSnapshot({ time: epoch+1, positions:[[0,0,0],[80,80,-80],[0,-8,0]] });
  b.vehicles[1].spatial.public_position_usable = false; b.vehicles[1].telemetry.stale = true;
  state.ingest(b); assert.deepEqual(state.getVehicle("UAV-02").position, first);
  state.ingest(publicSnapshot({ time:epoch+2, positions:[[0,0,0],[0,8,-3]] }));
  assert.equal(state.getVehicle("UAV-02").position.upM, 3); assert.equal(state.vehicles.has("UAV-03"), false);
});

test("replayed samples do not regain freshness and scene changes discard previous placement", () => {
  const state = createState(); const raw = publicSnapshot({ time: epoch }); state.ingest(raw);
  state.ingest({ ...raw, timestamp_ms: epoch+4000 }, { receivedAtMs: epoch+4000 });
  assert.equal(state.getVehicle("UAV-01").telemetry.stale, true);
  state.setScene(QINGLAN_SCENE); assert.equal(state.vehicles.size, 0);
  state.ingest(publicSnapshot({ time: epoch+4500 }), { receivedAtMs: epoch+4500 });
  assert.equal(state.getVehicle("UAV-01").position, null);
});

test("invalid full state, version and future timestamps cannot take bridge authority", () => {
  for (const overrides of [{full_state:false},{full_state:undefined},{version:"9.0"},{timestamp_ms:epoch+6000}]) {
    const state = createState(); state.ingest(publicSnapshot({time:epoch}));
    assert.throws(() => state.ingest({...publicSnapshot({time:epoch+1}),...overrides}, {transport:"bridge"}));
    assert.equal(state.transport,"runtime"); assert.equal(state.vehicles.size,3);
  }
  const state = createState(); state.ingest(publicSnapshot({time:epoch+2}));
  assert.equal(state.ingest(publicSnapshot({time:epoch+1}),{transport:"parent"}).reason,"out-of-order");
  assert.equal(state.transport,"runtime");
  assert.equal(state.ingest(publicSnapshot({time:epoch+2}),{transport:"parent"}).reason,"duplicate");
  state.ingest(publicSnapshot({time:epoch+3}),{transport:"parent"});
  assert.equal(state.ingest(publicSnapshot({time:epoch+4})).reason,"transport-suppressed");
});

test("postMessage accepts only the actual parent and approved matching origin", () => {
  const parent = {}, self = {}, calls = [];
  const handler = createParentMessageHandler({ parentWindow:parent, selfWindow:self, allowedOrigins:new Set(["http://localhost:5178","http://localhost:5173"]), expectedOrigin:"http://localhost:5178", onSnapshot:p=>calls.push(p), onMode:m=>calls.push(m), onError:e=>{throw e;} });
  const message = {source:parent,origin:"http://localhost:5178",data:{type:"uav-swarm/vehicle-snapshot",payload:publicSnapshot({time:epoch})}};
  assert.equal(handler({...message, source:{}}),false);
  assert.equal(handler({...message, origin:"http://localhost:5173"}),false);
  assert.equal(handler({...message, origin:"https://unknown.invalid"}),false);
  assert.equal(handler(message),true); assert.equal(calls.length,1);
});

// --- 选择同步（主控制台节点列表 <-> 三维视图）-----------------------------

test("select-vehicle message reaches onSelectVehicle with the node id", () => {
  const parent = {}, self = {}, seen = [];
  const handler = createParentMessageHandler({
    parentWindow:parent, selfWindow:self,
    allowedOrigins:new Set(["http://localhost:5178"]), expectedOrigin:"http://localhost:5178",
    onSnapshot:()=>{}, onMode:()=>{}, onError:e=>{throw e;},
    onSelectVehicle:nodeId=>seen.push(nodeId),
  });
  const message = {source:parent, origin:"http://localhost:5178",
                   data:{type:"uav-swarm/select-vehicle", payload:{nodeId:"UAV-02"}}};

  assert.equal(handler(message), true);
  assert.deepEqual(seen, ["UAV-02"]);
});

test("select-vehicle accepts an explicit null as 'no selection'", () => {
  const parent = {}, self = {}, seen = [];
  const handler = createParentMessageHandler({
    parentWindow:parent, selfWindow:self,
    allowedOrigins:new Set(["http://localhost:5178"]), expectedOrigin:"http://localhost:5178",
    onSnapshot:()=>{}, onMode:()=>{}, onError:e=>{throw e;},
    onSelectVehicle:nodeId=>seen.push(nodeId),
  });
  assert.equal(handler({source:parent, origin:"http://localhost:5178",
                        data:{type:"uav-swarm/select-vehicle", payload:{}}}), true);
  assert.deepEqual(seen, [null], "缺 nodeId 时传 null，而不是 undefined 或空串");
});

test("select-vehicle without a handler is reported as unhandled, not silently accepted", () => {
  // 没有 onSelectVehicle 时返回 false（未处理），这样调用方能发现接线缺失；
  // 若返回 true，会表现为"消息发出去了但选择没同步"，很难排查。
  const parent = {}, self = {};
  const handler = createParentMessageHandler({
    parentWindow:parent, selfWindow:self,
    allowedOrigins:new Set(["http://localhost:5178"]), expectedOrigin:"http://localhost:5178",
    onSnapshot:()=>{}, onMode:()=>{}, onError:e=>{throw e;},
  });
  assert.equal(handler({source:parent, origin:"http://localhost:5178",
                        data:{type:"uav-swarm/select-vehicle", payload:{nodeId:"UAV-01"}}}), false);
});

test("select-vehicle still enforces source and origin checks", () => {
  const parent = {}, self = {}, seen = [];
  const handler = createParentMessageHandler({
    parentWindow:parent, selfWindow:self,
    allowedOrigins:new Set(["http://localhost:5178"]), expectedOrigin:"http://localhost:5178",
    onSnapshot:()=>{}, onMode:()=>{}, onError:e=>{throw e;},
    onSelectVehicle:nodeId=>seen.push(nodeId),
  });
  const base = {origin:"http://localhost:5178",
                data:{type:"uav-swarm/select-vehicle", payload:{nodeId:"UAV-03"}}};
  assert.equal(handler({...base, source:{}}), false, "非父窗口来源必须拒绝");
  assert.equal(handler({...base, origin:"https://unknown.invalid"}), false, "未知来源必须拒绝");
  assert.deepEqual(seen, [], "被拒绝的消息不得触发选择");
});

test("stopped poller's in-flight response cannot replace a parent feed or re-enable LIVE", async () => {
  let resolve, applied=0;
  const poller = new RuntimeVehicleSnapshotPoller({ fetchSnapshot:()=>new Promise(r=>{resolve=r;}), onSnapshot:()=>{applied++;}, onError:()=>{} });
  const pending = poller.pollOnce(); poller.stop(); resolve(publicSnapshot({time:epoch}));
  assert.equal((await pending).reason,"cancelled"); assert.equal(applied,0);
});

test("planned and predicted coordinates do not become public telemetry positions", () => {
  const state = createState(); const raw = publicSnapshot({time:epoch});
  raw.planned_route = [{x:1000,y:1000,z:-1000}]; raw.vehicles[1].predicted_position = {x:100,y:100,z:-100};
  state.ingest(raw);
  assert.equal(state.getVehicle("UAV-02").position.eastM,8); assert.equal(state.getVehicle("UAV-02").position.upM,-0);
});
