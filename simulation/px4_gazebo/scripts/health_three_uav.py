#!/usr/bin/env python3
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from simulation.px4_gazebo.harness import *
def probe(ep,t=2):
 try: from pymavlink import mavutil
 except ImportError:return None
 c=mavutil.mavlink_connection(ep)
 try:
  m=c.wait_heartbeat(timeout=t);return int(m.get_srcSystem()) if m else None
 finally:c.close()
def health(d,fn=probe):
 validate(d); f=path(d['runtime_root'])/'processes.json'; ps={}
 if f.exists(): ps={r['name']:alive(r) for r in json.loads(f.read_text())['processes']}
 rows=[]
 for v in d['vehicles']:
  seen=fn(v['command_endpoint']) if v.get('command_endpoint') else None
  ok=ps.get(v['node_id'],False) and seen==v['system_id']
  rows.append({'node_id':v['node_id'],'expected_system_id':v['system_id'],'observed_system_id':seen,'heartbeat_received':seen is not None,'endpoint':v['command_endpoint'],'model_binding':v['gazebo_model_name'],'process_alive':ps.get(v['node_id'],False),'readiness':'ready' if ok else 'unavailable'})
 ids=[r['observed_system_id'] for r in rows if r['observed_system_id'] is not None]; ok=len(ids)==len(set(ids))==len(rows) and all(r['readiness']=='ready' for r in rows)
 return {'status':'pass' if ok else 'fail','system_ids_unique':len(ids)==len(set(ids))==len(rows),'vehicles':rows}
p=argparse.ArgumentParser();p.add_argument('--config',default=str(DEFAULT));p.add_argument('--pretty',action='store_true');a=p.parse_args();r=health(load(a.config));print(json.dumps(r,indent=2 if a.pretty else None));raise SystemExit(0 if r['status']=='pass' else 1)
