from __future__ import annotations
import json, os, signal, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; DEFAULT=ROOT/'simulation/px4_gazebo/config/three_uav_sitl.json'
class HarnessError(RuntimeError): pass
def load(path=DEFAULT): return json.loads(Path(path).read_text())
def path(v):
 p=Path(os.path.expanduser(v)); return p if p.is_absolute() else ROOT/p
def ned_to_enu(p): return {'x_m':float(p['y_m']),'y_m':float(p['x_m']),'z_m':-float(p['z_m']),'yaw_deg':((90-float(p.get('yaw_deg',0))+180)%360)-180}
def validate(d,resolved=False):
 vs=d.get('vehicles',[])
 if not vs: raise HarnessError('vehicles required')
 for k in ('node_id','px4_instance','system_id','gazebo_model_name','runtime_dir'):
  a=[v[k] for v in vs]
  if len(a)!=len(set(a)): raise HarnessError(f'duplicate {k}')
 if resolved and d.get('discovery_status')!='confirmed_from_local_px4_source': raise HarnessError('PX4 discovery not confirmed')
 if resolved and any(not v.get('command_endpoint') or not v.get('telemetry_endpoint') or not v.get('launch_argv') for v in vs): raise HarnessError('unresolved vehicle binding')
def ticks(pid):
 try:return Path(f'/proc/{pid}/stat').read_text().split()[21]
 except:return None
def alive(r): return ticks(int(r['pid']))==str(r['ticks'])
def stop(d):
 f=path(d['runtime_root'])/'processes.json'
 if not f.exists(): return {'status':'not_running'}
 rs=json.loads(f.read_text())['processes']
 for r in reversed(rs):
  if alive(r):
   try: os.killpg(r['pgid'],signal.SIGTERM)
   except ProcessLookupError: pass
 time.sleep(.5)
 for r in reversed(rs):
  if alive(r):
   try: os.killpg(r['pgid'],signal.SIGKILL)
   except ProcessLookupError: pass
 f.unlink(missing_ok=True); return {'status':'stopped'}
def start(d,headless=False):
 validate(d,True); root=path(d['runtime_root']); root.mkdir(parents=True,exist_ok=True); rs=[]
 cmds=[('gazebo',d['gazebo']['headless_argv' if headless else 'gui_argv'],root)] + [(v['node_id'],v['launch_argv'],path(v['runtime_dir'])) for v in d['vehicles']]
 try:
  for name,argv,cwd in cmds:
   cwd.mkdir(parents=True,exist_ok=True); log=open(cwd/f'{name}.log','ab',buffering=0)
   p=subprocess.Popen(argv,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True); log.close(); time.sleep(.1)
   if p.poll() is not None: raise HarnessError(f'{name} startup failed')
   rs.append({'name':name,'pid':p.pid,'pgid':os.getpgid(p.pid),'ticks':ticks(p.pid)})
  (root/'processes.json').write_text(json.dumps({'processes':rs},indent=2)); return {'status':'started'}
 except: stop({'runtime_root':d['runtime_root']}); raise
