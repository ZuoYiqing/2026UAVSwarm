# 三维仿真载具数据契约 1.0

本文定义 Cesium 三维前端接收的数据。前端只负责显示，不把本地演示路径当作权威状态。
真实无人平台、Gazebo/PX4 和其他仿真器应先由运行时后端统一汇聚，再向前端发布完整快照。

机器可读版本位于：

```text
public/contracts/vehicle-snapshot.schema.json
```

## 1. 更新模型

- 推荐频率：5 至 10 Hz；
- 每个消息是一个完整状态快照，`full_state` 设为 `true`；
- `id` 是生命周期内稳定且全局唯一的字符串；
- 完整快照中消失的 `id` 会从场景删除；
- 同一快照不允许出现重复 `id`；
- 位置、姿态和遥测属于平台状态，Agent 意图是独立的可选扩展；
- 前端不通过该接口直接向飞控发命令。

## 2. 完整示例

```json
{
  "version": "1.0",
  "timestamp": "2026-07-28T09:30:00.125Z",
  "full_state": true,
  "source": {
    "id": "runtime-fusion",
    "kind": "hybrid",
    "label": "虚实融合运行时"
  },
  "frame": {
    "type": "ENU"
  },
  "vehicles": [
    {
      "id": "physical-mr-01",
      "display_name": "实机 MR-01",
      "vehicle_type": "multirotor",
      "model": "x500",
      "source": {
        "id": "mavlink-radio-01",
        "kind": "physical",
        "label": "MAVLink 实机链路"
      },
      "connected": true,
      "pose": {
        "frame": "ENU",
        "position_m": {
          "x": 12.4,
          "y": -30.8,
          "z": 48.2
        },
        "attitude_deg": {
          "roll": 1.2,
          "pitch": -2.1,
          "yaw": 86.0
        }
      },
      "velocity_mps": {
        "east": 5.2,
        "north": 0.4,
        "up": -0.1
      },
      "telemetry": {
        "armed": true,
        "mode": "OFFBOARD",
        "battery_percent": 78,
        "link_quality_percent": 93,
        "ground_speed_mps": 5.22
      },
      "agent": {
        "id": "agent-physical-mr-01",
        "status": "executing",
        "intent": "inspect-sector-a"
      }
    },
    {
      "id": "gazebo-fw-01",
      "display_name": "仿真固定翼 FW-01",
      "vehicle_type": "fixed_wing",
      "model": "standard_vtol",
      "source": {
        "id": "gazebo-sitl",
        "kind": "simulation",
        "label": "Gazebo SITL"
      },
      "connected": true,
      "pose": {
        "frame": "NED",
        "position_m": {
          "x": 120.0,
          "y": 45.0,
          "z": -80.0
        },
        "attitude_deg": {
          "roll": 4.0,
          "pitch": 1.5,
          "yaw": 32.0
        }
      },
      "telemetry": {
        "armed": true,
        "mode": "AUTO_MISSION",
        "battery_percent": 91,
        "ground_speed_mps": 19.5
      }
    }
  ]
}
```

## 3. 坐标

前端接受三种坐标：

- `ENU`：`x=East`、`y=North`、`z=Up`；
- `NED`：`x=North`、`y=East`、`z=Down`，前端自动转换；
- `WGS84`：使用 `longitude_deg`、`latitude_deg`、`altitude_m`。

若使用 ENU/NED，所有来源必须共享同一个任务区原点。当前前端原点在
`src/main.js` 的 `SCENE_ANCHOR`。后端应把原点作为任务配置管理，后续不要让不同组件各自
写死一份。

## 4. 平台类型

`vehicle_type` 允许：

```text
multirotor
fixed_wing
vtol
ugv
usv
uuv
unknown
```

## 5. 同窗口集成

三维页面加载后暴露：

```js
window.SwarmSimulationBridge.applyVehicleSnapshot(snapshot);
window.SwarmSimulationBridge.selectVehicle("physical-mr-01");
window.SwarmSimulationBridge.useDemo();
window.SwarmSimulationBridge.getState();
```

首次接入真实数据时直接调用 `applyVehicleSnapshot`，页面会停止两分钟演示并进入 `LIVE`。

## 6. iframe 集成

父页面向三维 iframe 发送：

```js
simulationFrame.contentWindow.postMessage(
  {
    type: "uav-swarm/vehicle-snapshot",
    payload: snapshot
  },
  window.location.origin
);
```

三维 iframe 就绪后向父页面发送：

```js
{
  type: "uav-swarm/simulation-ready",
  payload: {
    contractVersion: "1.0"
  }
}
```

生产环境推荐把控制台与三维页面部署在同一域名下。若必须跨域，应把允许的精确来源做成
部署配置，不要使用任意来源 `*`。

## 7. 后续 WebSocket 建议

浏览器不要直接连接 MAVLink、DDS 或 Gazebo Transport。推荐链路：

```text
实机 / Gazebo / 其他仿真器
        -> 运行时后端状态汇聚
        -> WebSocket JSON 快照
        -> 主前端
        -> SwarmSimulationBridge / postMessage
        -> Cesium 三维显示
```

断线重连、超时、数据节流和控制权限属于主前端/运行时后端职责；三维子应用保持纯显示层。
