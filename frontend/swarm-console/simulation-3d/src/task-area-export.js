import { CAMPUS_BUILDINGS, CAMPUS_ROADS } from "./campus-layout.js";
import { QINGLAN_SCENE } from "./scene-alignment.js";

const BOUNDS = [-100,-115,160,145];
const inside = ([xmin,ymin,xmax,ymax]) => xmin >= BOUNDS[0] && ymin >= BOUNDS[1] && xmax <= BOUNDS[2] && ymax <= BOUNDS[3];
const polygon = ([xmin,ymin,xmax,ymax]) => [[xmin,ymin],[xmax,ymin],[xmax,ymax],[xmin,ymax]];

export function exportCampusTaskArea() {
  const excluded = [];
  const buildings = CAMPUS_BUILDINGS.flatMap(({id,dimensions:[x,y,w,d,h]}) => {
    const extent = [x-(w+1.5)/2,y-(d+1.5)/2,x+(w+1.5)/2,y+(d+1.5)/2];
    if (!inside(extent)) { excluded.push({id,reason:"outside_or_crosses_export_boundary"}); return []; }
    return [{id,kind:"building",footprint_enu_m:polygon(extent),base_enu_m:[x,y,0.3],dimensions_m:{width:w,depth:d,height:h},
      yaw_enu_deg:0,collision_suggestion:{shape:"box",center_enu_m:[x,y,(h+1.3)/2],size_m:[w+1.5,d+1.5,h+1.3]},
      visual_asset:{source:"src/campus-layout.js",object_id:id},physics_status:"not_imported"}];
  });
  const roads = CAMPUS_ROADS.flatMap(road => {
    const raw = [road.x-road.width/2,road.y-road.depth/2,road.x+road.width/2,road.y+road.depth/2];
    const clipped = [Math.max(raw[0],BOUNDS[0]),Math.max(raw[1],BOUNDS[1]),Math.min(raw[2],BOUNDS[2]),Math.min(raw[3],BOUNDS[3])];
    if (clipped[0]>=clipped[2] || clipped[1]>=clipped[3]) {excluded.push({id:road.id,reason:"outside_export_boundary"});return [];}
    return [{id:road.id,footprint_enu_m:polygon(clipped),clipped:!inside(raw),surface_z_m:0.35,collision_suggestion:"ground_surface_only",physics_status:"not_imported"}];
  });
  const tower = {id:"qinglan-campus-control-tower",kind:"tower",base_enu_m:[14,18,0],
    collision_suggestion:{shape:"cylinder",center_enu_m:[14,18,24],radius_m:11,height_m:48},
    visual_asset:{source:"src/city-geometry.js",section:"campus control tower"},physics_status:"not_imported"};
  return {
    format:"uavswarm-task-area-proposal",format_version:"0.1",status:"pending_simulation_confirmation",
    scene_id:QINGLAN_SCENE.scene_id,map_version:QINGLAN_SCENE.map_version,task_area_id:"qinglan-campus-east-260",
    scene_origin:structuredClone(QINGLAN_SCENE.scene_origin),local_enu_origin_m:[0,0,0],render_anchor:structuredClone(QINGLAN_SCENE.anchor),
    units:"m",frame:"ENU",axis_convention:{x:"east",y:"north",z:"up",yaw_zero:"east",yaw_positive:"counterclockwise"},
    ground_z_m:0,altitude_reference:"local_scene_ground",boundary_enu_m:polygon(BOUNDS),
    extent_m:{east:260,north:260},physics_status:"not_imported",source_commit:"96e029c",
    coverage:{complete_city:false,complete_physical_map:false,scope:"selected campus buildings, control tower and clipped roads",
      omitted:["city blocks outside the campus","bridges","hills","campus trees","solar arrays","fences","landing-pad artwork","apron surface","facade and roof details except conservative building collision envelope"],excluded_objects:excluded},
    objects:[...buildings,tower],roads,
    takeoff_candidates:[0,8,-8].map((east,i)=>({id:`takeoff-candidate-${i+1}`,suggested_node_id:`UAV-0${i+1}`,position_enu_m:[east,0,0],protected_radius_m:3,status:"proposal_only",visual_pad:false})),
    inspection_candidates:[{id:"inspect-main-south",position_enu_m:[-10,45,5],status:"proposal_only"},{id:"inspect-east-lab",position_enu_m:[95,45,5],status:"proposal_only"}],
    no_fly_candidates:[{id:"nfz-control-tower",shape:"cylinder",center_enu_m:[14,18,0],radius_m:14,min_up_m:0,max_up_m:55,status:"proposal_only"}],
    handoff:{owner:"Simulation",accepted:false,sdf_world:null,existing_simple_recon_modified:false,
      note:"Not a calibrated transform to simple_recon_v0_1. Simulation must review takeoff protection, build collision assets and publish a new scene/map calibration before LIVE alignment."},
  };
}
