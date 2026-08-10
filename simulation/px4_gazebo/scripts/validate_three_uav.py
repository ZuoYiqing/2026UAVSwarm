#!/usr/bin/env python3
"""Fail-closed SITL validation entry; requires resolved manifest and three-node health."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from simulation.px4_gazebo.harness import *
p=argparse.ArgumentParser();p.add_argument('--config',default=str(DEFAULT));p.add_argument('--pretty',action='store_true');a=p.parse_args()
try: d=load(a.config);validate(d,True);raise HarnessError('real sequential takeoff validation requires target WSL PX4/Gazebo environment')
except Exception as e:r={'status':'fail','error':str(e)}
print(json.dumps(r,indent=2 if a.pretty else None));raise SystemExit(1)
