# 三机 Harness Runbook

配置唯一来源：`simulation/px4_gazebo/config/three_uav_sitl.json`。运行目录 `.runtime/px4_gazebo` 已忽略。

```bash
bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless
python simulation/px4_gazebo/scripts/health_three_uav.py --pretty
python simulation/px4_gazebo/scripts/validate_three_uav.py --pretty
bash simulation/px4_gazebo/scripts/stop_three_uav.sh
```

Stopper 只处理 Harness PID/PGID，不使用 pkill/killall。Scene/PX4 为 NED（x North,y East,z Down），Gazebo 为 ENU/Z-up：`GX=NY,GY=NX,GZ=-NZ,yaw_enu=90-yaw_ned`。WGS84 唯一原点来自 scene.json。Runtime 必须按 node_id+endpoint+system_id 绑定，不能按 heartbeat 顺序猜身份。扩展 5/10 架只增加 manifest/scene vehicle，不复制脚本。
