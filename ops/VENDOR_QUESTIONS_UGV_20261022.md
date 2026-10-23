# 给厂家的技术确认清单（UGV / Scout 底盘）

> **用途**：我方要把自研的控制程序（UAV Runtime）接到这台车上，需要确认接口与协议。
> **背景**：我方做无人机/无人车的任务执行运行时（策略裁决 + 动作执行 + 审计），
> 目前适配层只支持 MAVLink。要接到 Scout 底盘上，需要确认走 ROS 还是走 CAN。

---

## 我们已经在车上看过的东西（不用重复回答）

| 项目 | 我们看到的 |
| --- | --- |
| 平台 | Jetson AGX Orin，Ubuntu 20.04.5，L4T R35.3.1，aarch64 |
| ROS | Noetic，282 个包，`ROS_MASTER_URI=http://localhost:11311` |
| 启动脚本 | `~/outdoor_start.sh` 依次起三个 launch（见下） |
| 工作空间 | `~/catkin_ws/src/swarm_ros` |
| CAN | `can0` UP，500 kbps，抓到的帧例如：`241 [8] BA 00 00 00 00 00 00 3D`（末字节递增）<br>另有 `253 254 251 252 221 311` |
| 磁盘 | 根分区在 eMMC（55G，剩 24G）；`/dev/nvme0n1p1`（477G，ext4）**未挂载** |
| 网络 | `eth2` UP 但**没有 IPv4**；重启后需要重新配 |

`outdoor_start.sh` 内容：

```bash
roslaunch tqr_robot_bringup outdoor_bringup.launch
roslaunch scout_navigation   localization_run.launch
roslaunch mpc_formation      muit_dmpc_with_time_mqtt.launch
```

---

## ⭐ 必答（这三个决定了我们怎么接）

### 1. 底盘是否接受 ROS 速度指令？

`localization_run.launch` 起来后，底盘是否订阅 **`/cmd_vel`**（`geometry_msgs/Twist`）？

* 如果是 → **请告知准确的 topic 名**，以及 `linear.x` / `angular.z` 的单位和取值范围
* 如果不是 → 我们只能走 CAN，请回答问题 2

> **为什么先问这个**：如果 `/cmd_vel` 可用，我们不需要碰 CAN 协议，工作量小很多，
> 也不会和你们现有的导航/编队栈冲突。

### 2. 如果必须直接发 CAN，请提供协议文档

需要的内容：

* 每个报文 ID 的含义（例如 `0x241` 是什么？`0x253`/`0x254`/`0x251`/`0x252`/`0x221`/`0x311` 分别是什么？）
* 每个 ID 的 8 个字节分别代表什么，单位是什么（速度？角度？使能位？）
* 哪些是**控制帧**（我们发），哪些是**反馈帧**（车发）
* **是否需要先发使能帧 / 心跳帧**？周期多少？
* 丢帧或超时的行为

### 3. 安全行为（这条关系到不会撞车）

* 如果控制帧**超时**（例如 1 秒没收到指令），底盘会**自动停车**还是**保持上一次指令继续跑**？
* 有没有**急停**接口（topic / service / CAN 帧 / 物理按钮）？
* 最大允许速度是多少？有没有软件限速？

---

## 次要（知道更好，不影响我们开工）

### 4. 你们的包源码可以看吗

* `tqr_robot_bringup`、`scout_navigation` 是你们提供的吗？
* 可以给我们看 `launch` 文件和 `config` 吗？（我们自己查 topic 名也行，但如果你们直接说更快）

### 5. `swarm_ros` 是做什么的

`~/catkin_ws/src/swarm_ros` 这个包的作用是什么？是你们写的还是之前遗留的？

### 6. MQTT 配置

`mpc_formation/muit_dmpc_with_time_mqtt.launch` 用的是哪个 MQTT broker？

* 地址和端口？
* 是车自己起 broker，还是连外部 broker？
* topic 命名规则？

> 我方如果要做多车协同，可能复用这条通道。

### 7. 底盘型号

是 **AgileX（松灵）Scout** 吗？具体是 Scout 2.0、Scout mini，还是别的？

> 如果是标准 Scout，很多协议是公开的，我们可以自己查，就不麻烦你们了。

### 8. NVMe 磁盘

`/dev/nvme0n1p1`（477G，已格式化为 ext4，未挂载）：

* 里面**有数据吗**？
* 如果没有，我们想把它挂到 `/mnt/nvme` 用来放程序和数据（根分区只剩 24G，eMMC 长期写日志也不合适），可以吗？

### 9. eth2 网口

`eth2` 每次重启都要重新配 IP：

* 这是有意的设计吗（为了安全/隔离）？
* 有没有推荐的固定配置方式？还是希望我们每次手动配？

---

## 如果时间紧，只回答第 1 条也行

> **底盘能不能用 `/cmd_vel` 控制？发到哪个 topic？**

这一条答了，我们就能开工。

---

## 我方会保证的事

* **只读优先**：我们不会改你们现有的 `bringup` / `navigation` / `formation` 包
* **不抢控制权**：默认不接管底盘，只在你们允许的接口上发指令
* **有急停**：我们的动作都经过策略门，且会先确认急停路径可用
* **先台架后实车**：先在架空/低速下验证，不直接上路
