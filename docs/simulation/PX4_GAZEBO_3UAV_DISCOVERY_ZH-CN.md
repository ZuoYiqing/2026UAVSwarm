# PX4/Gazebo 三机 Discovery

2026-08-10 当前容器中 `~/PX4-Autopilot` 不存在，`gz` 不存在，因此 PX4 commit、Gazebo version、多实例参数、model spawn 和端口规则均为 **NOT TESTED**。不得用记忆猜参数。

目标 WSL 必须执行：
```bash
git -C ~/PX4-Autopilot rev-parse HEAD
gz sim --versions
rg -n "PX4_GZ_MODEL|PX4_GZ_MODEL_POSE|PX4_GZ_WORLD|MAV_SYS_ID|multi.*instance|MAV_.*PORT" ~/PX4-Autopilot
```
确认官方 multi-instance 脚本、instance、sysid、model name/pose、world、UDP、rootfs/work/log 规则后，将 manifest 状态改为 `confirmed_from_local_px4_source` 并填写 argv/endpoints。当前 launcher fail closed。

| node_id | instance | sysid | model | command | telemetry | spawn NED |
|---|---:|---:|---|---|---|---|
|UAV-01|0 待确认|1|x500_UAV_01 待确认|UNRESOLVED|UNRESOLVED|(0,0,0)|
|UAV-02|1 待确认|2|x500_UAV_02 待确认|UNRESOLVED|UNRESOLVED|(0,8,0)|
|UAV-03|2 待确认|3|x500_UAV_03 待确认|UNRESOLVED|UNRESOLVED|(0,-8,0)|
