#!/usr/bin/env python3
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from simulation.px4_gazebo.harness import *
p=argparse.ArgumentParser();p.add_argument('op',choices=['start','stop']);p.add_argument('--config',default=str(DEFAULT));p.add_argument('--headless',action='store_true');a=p.parse_args()
try:d=load(a.config);r=start(d,a.headless) if a.op=='start' else stop(d);print(json.dumps(r));raise SystemExit(0)
except Exception as e:print(json.dumps({'status':'fail','error':str(e)}));raise SystemExit(1)
