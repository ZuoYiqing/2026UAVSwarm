import copy
import pytest
from simulation.px4_gazebo.harness import *
def test_mapping_and_coordinates():
 d=load(); validate(d); assert [v['system_id'] for v in d['vehicles']]==[1,2,3]; assert ned_to_enu(d['vehicles'][1]['spawn_ned'])['x_m']==8
def test_unresolved_fails_closed():
 with pytest.raises(HarnessError): validate(load(),True)
def test_duplicate_identity_rejected():
 d=load();d['vehicles'][1]['system_id']=1
 with pytest.raises(HarnessError):validate(d)
