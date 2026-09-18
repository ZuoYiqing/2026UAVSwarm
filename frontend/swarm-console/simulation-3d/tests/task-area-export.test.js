import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CAMPUS_BUILDINGS } from "../src/campus-layout.js";
import { exportCampusTaskArea } from "../src/task-area-export.js";

test("bounded task area is reproducible, explicitly partial and preserves the city geometry", () => {
  const area = exportCampusTaskArea();
  assert.deepEqual(area, JSON.parse(readFileSync(new URL("../docs/samples/qinglan-campus-task-area.proposal.json",import.meta.url),"utf8")));
  assert.equal(area.extent_m.east,260); assert.equal(area.coverage.complete_physical_map,false);
  assert.equal(area.handoff.accepted,false); assert.equal(area.handoff.existing_simple_recon_modified,false);
  const ids = area.objects.map(o=>o.id); assert.equal(new Set(ids).size,ids.length);
  for (const object of area.objects.filter(o=>o.kind==="building")) {
    const source = CAMPUS_BUILDINGS.find(b=>b.id===object.id).dimensions;
    assert.deepEqual(object.base_enu_m,[source[0],source[1],0.3]);
    assert.deepEqual(object.dimensions_m,{width:source[2],depth:source[3],height:source[4]});
    for(const [e,n] of object.footprint_enu_m) assert.ok(e>=-100 && e<=160 && n>=-115 && n<=145);
    assert.equal(object.physics_status,"not_imported");
  }
  assert.ok(area.coverage.excluded_objects.length>0);
});

test("candidate takeoff points retain 0/+8/-8 and avoid exported collision envelopes", () => {
  const area=exportCampusTaskArea();
  assert.deepEqual(area.takeoff_candidates.map(p=>p.position_enu_m),[[0,0,0],[8,0,0],[-8,0,0]]);
  for(const pad of area.takeoff_candidates) for(const obj of area.objects) {
    const [e,n]=pad.position_enu_m, c=obj.collision_suggestion, [x,y]=c.center_enu_m;
    const distance=c.shape==="cylinder" ? Math.hypot(e-x,n-y)-c.radius_m : Math.hypot(Math.max(0,Math.abs(e-x)-c.size_m[0]/2),Math.max(0,Math.abs(n-y)-c.size_m[1]/2));
    assert.ok(distance>pad.protected_radius_m,`${pad.id} conflicts with ${obj.id}`);
  }
});
