# UGV（无人车）环境详情

**机器**：Jetson AGX Orin · 主机名 `nvidia` · 用户 `nvidia`(uid 1000)
**用途**：车端计算单元 + 我方 Runtime 部署目标
**文档版本**：2026-10-22
**维护**：本文件是 UGV 环境的**唯一声明来源**；如与其它文档冲突，以本文件为准

---

## 0. 一页摘要（给同事 / 给 Runtime 负责人）

| 项 | 结论 |
| --- | --- |
| **平台** | Jetson AGX Orin（Tegra t186ref），**aarch64** |
| **系统** | Ubuntu 20.04.5 LTS，内核 `5.10.104-tegra`，L4T **R35.3.1**，glibc 2.31 |
| **Python** | **3.8.10**（系统）/ 3.9.5（另装）→ **不满足 Runtime 的 ≥3.10** |
| **CUDA** | 11.4（`nvcc` 可用，`/usr/local/cuda-11.4`） |
| **ROS** | **Noetic**，282 包，`ROS_MASTER_URI=http://localhost:11311` |
| **底盘** | **Scout 2.0**（厂家确认） |
| **控制接口** | ⭐ **ROS `/cmd_vel`（`geometry_msgs/Twist`）**，厂家确认；CAN 已被底盘驱动封装 |
| **控制前提** | ⚠️ **必须先把控制设为「自动模式」**（厂家原话，切换方式未知） |
| **存储** | 根在 **eMMC 55G（剩 24G）**；**NVMe 477G 已格式化但未挂载** |
| **网络** | ⚠️ `eth2` UP 但**无 IPv4**；`can0` UP(500k)；**SSH 22 可用**；**能联网**（已实测） |
| **浏览器** | firefox 110 + `DISPLAY=:0` → **能本地显示控制台** |
| **关键约束** | Runtime 需 Python ≥3.10，而 ROS Noetic 的 rospy 是 Python 3.8 → **版本冲突，见 §7** |

**一句话**：这台能装 Runtime（装完就有 HTTP 桥/策略门/审计/前端），
**但不能直接开车** —— 缺一个 ROS `/cmd_vel` 适配层，且动作语义要重新定义。

---

## 1. 硬件与系统

| 项 | 值 | 来源 |
| --- | --- | --- |
| 主机名 | `nvidia` | recon-offline-env |
| 用户 / uid | `nvidia` / 1000 | recon-offline-env |
| 架构 | **aarch64** | recon-offline-env |
| 板卡 | **t186ref**（Jetson AGX Orin） | recon-offline-env（L4T 行） |
| 系统 | Ubuntu **20.04.5** LTS | recon-offline-env |
| 内核 | `5.10.104-tegra` | recon-offline-env |
| L4T | **R35.3.1**（GCID 32827747，2023-03-19） | recon-offline-env |
| glibc | 2.31（`Ubuntu GLIBC 2.31-0ubuntu9.9`） | recon-offline-env |
| 内存 | **29 GB** | recon-offline-env |
| GPU | Tegra 集成（**无 `nvidia-smi`**，正常现象；无独立 VGA 设备） | recon-offline-env |
| CUDA | **11.4**（`nvcc` V11.4.315；`/usr/local/cuda` `/usr/local/cuda-11` `/usr/local/cuda-11.4`） | recon-offline-env |
| TensorRT | 8.5.2.2 | **仅同事报告，未复核** |
| cuDNN | 8.6.0 | **仅同事报告，未复核** |
| OpenCV | 4.2.0 | **仅同事报告，未复核** |

> ⚠️ **与同事报告的冲突**：同事记录「`nvcc` 不在 PATH」，但 recon 实测 `nvcc` 可调用（release 11.4）。
> 现在**是可用**的。若后续脚本报找不到 nvcc，先 `which nvcc` 确认。

---

## 2. 软件环境

### 2.1 Python

| 项 | 值 |
| --- | --- |
| `python3` | **3.8.10** → `/usr/bin/python3` |
| `python` | **2.7.18** |
| 其它版本 | `/usr/bin/python3.8`、`/usr/bin/python3.9`（3.9.5） |
| `pip3` | ✅ 可用（有 `cryptography` 弃用告警，不影响） |
| `venv` | ✅ 有 |
| `ensurepip` | ❌ `No module named 'ensurepip'`（所以 `python3 -m venv` 可能不稳，用 `virtualenv` 或 `uv`） |

**⚠️ Runtime 要求 `requires-python >= 3.10`，本机不满足。**

### 2.2 ROS

| 项 | 值 |
| --- | --- |
| 发行版 | **Noetic** |
| 包数量 | **282** |
| `ROS_MASTER_URI` | `http://localhost:11311` |
| `ROS_PACKAGE_PATH` | `/home/nvidia/catkin_ws/src:/opt/ros/noetic/share` |
| `ROS_VERSION` / `ROS_PYTHON_VERSION` | 1 / 3 |
| `rosnode` / `rostopic` | ✅ 都在 `/opt/ros/noetic/bin/` |
| ROS 2 | ❌ 不在 PATH |
| 当前运行的节点 | **无**（recon 时 master 未起） |

**`/opt/ros/noetic` 下已装的 gazebo 相关包**：`gazebo_ros`、`gazebo_ros_pkgs`、`gazebo_plugins`、
`gazebo_msgs`、`gazebo_dev`、`gazebo_ros_control`（Gazebo **Classic**，随 Noetic 安装）

### 2.3 工具链

| 工具 | 状态 |
| --- | --- |
| git / curl / pip3 | ✅ |
| ssh / scp / rsync | ✅ |
| gzip / tar / unzip | ✅ |
| make / gcc | ✅ |
| **node / npm** | ❌ **缺失**（不影响：三维视图用已构建的 `dist/`） |

### 2.4 容器

`docker0` 网桥存在（`172.17.0.1/16`，DOWN）→ **Docker 已安装**（同事报告亦确认）

### 2.5 远程桌面

`nxnode.bin` / `nxrunner.bin` 在跑，监听 `127.0.0.1:12001 / 22615 / 22616 / 25001`
→ **NoMachine 已安装并在运行**

---

## 3. 存储（⚠️ 最需要注意的一项）

### 3.1 现状

```
Filesystem       Type   Size  Used  Avail  Use%  Mounted on
/dev/mmcblk0p1   ext4    54G   28G    24G   55%   /            ← 根分区在 eMMC
/dev/sda1        vfat    28G   22M    28G    1%   /media/nvidia/6292-E606   ← U 盘（现场传文件用）
nvme0n1p1        ext4   477G    ?      ?     ?    （未挂载）    ← NVMe 闲置
```

### 3.2 设备树要点

| 设备 | 大小 | 说明 |
| --- | --- | --- |
| `mmcblk0` | 59.3G | **eMMC**，根分区 `mmcblk0p1` 55G |
| `zram0`~`zram7` | 各 1.9G | 压缩内存 swap |
| `sda` | 28.9G | USB 存储（现场用于传文件） |
| **`nvme0n1`** | **477G** | **NVMe SSD**；`nvme0n1p1` 477G **ext4 已格式化但未挂载** |

### 3.3 结论与风险

| 项 | 结论 |
| --- | --- |
| 根分区余量 | 24 GB → 装 Runtime（0.6 MB）+ Python 3.11（约 200 MB）**够用** |
| **eMMC 寿命** | ⚠️ 长期往根分区写审计日志会磨损 eMMC，**建议日志放 NVMe** |
| NVMe 状态 | ⚠️ **已格式化但未挂载，477 GB 完全没用** |
| 内容未知 | ❗ **必须先确认里面有没有数据**，再决定是否使用 |

> ⚠️ **与同事报告的冲突**：同事记录「**没看到 NVMe**」。
> 但 `recon-vehicle.sh` 用 `lsblk` 明确列出了 `nvme0n1` + `nvme0n1p1`。
> **以 `lsblk` 为准 —— NVMe 确实存在。**（同事可能只看了 `df -h`，而未挂载的磁盘不会出现在 `df` 里。）

**查看 NVMe 内容（先看，别格式化）**：

```bash
lsblk -f
sudo blkid /dev/nvme0n1p1
sudo mkdir -p /mnt/nvme && sudo mount /dev/nvme0n1p1 /mnt/nvme
ls -la /mnt/nvme            # ← 先看这里有没有数据
sudo umount /mnt/nvme
```

---

## 4. 网络

### 4.1 接口

| 接口 | 状态 | 说明 |
| --- | --- | --- |
| `lo` | UP | 127.0.0.1 |
| **`eth2`** | **UP** | `64:62:66:00:77:20`，**无 IPv4**（只有 IPv6/link-local） |
| `eth0` / `eth1` / `eth3` | DOWN | 未插线 |
| `wlan0` | DOWN | 无线未启用 |
| `docker0` | DOWN | `172.17.0.1/16` |
| **`can0`** | **UP** | **500 kbps**，`ERROR-ACTIVE`，**有实时数据** |
| `can1`~`can4` | DOWN | |
| `l4tbr0` / `rndis0` / `usb0` | DOWN | USB 网络未用 |

**默认路由：无**（只有 docker0 的 linkdown 路由）

### 4.2 联网能力（实测）

```bash
curl -sI http://pypi.org | head -1
→ HTTP/1.1 301 Moved Permanently        ✅ 能上网
```

**⚠️ 但 `eth2` 每次重启后需要重新配 IP**（现场经验）。

### 4.3 监听端口

| 端口 | 用途 |
| --- | --- |
| **22 (tcp)** | **SSH，可用**（`sshd` 在跑） |
| 4000 (tcp+udp) | 某个 Web 服务 |
| 7001 / 12001 / 22615 / 22616 / 25001 | **NoMachine 远程桌面** |
| 3000 | 某个 Web 服务 |
| 111 | rpcbind |
| 123 | NTP |
| 53 | systemd-resolved |

### 4.4 SSH

```bash
ssh nvidia@<车IP>
```
`DISPLAY=:0`、`ubuntu.desktop` 在跑 → **有图形界面可用**

---

## 5. CAN 总线（已确认不需要直接操作）

### 5.1 实测数据

`candump -T 3000 can0`（只订阅 3 秒，未发送）抓到：

> 下面每行第二列是**十六进制报文 ID**（candump 的原始格式，等价于 `0x241`、`0x253`）。

```
can0  253   [8]  00 00 00 00 00 00 00 00
can0  254   [8]  00 00 00 00 00 00 00 00
can0  241   [8]  BA 00 00 00 00 00 00 3D
can0  251   [8]  00 00 00 00 00 00 00 00
can0  252   [8]  00 00 00 00 00 00 00 00
can0  221   [8]  00 00 00 00 00 00 00 00
can0  311   [8]  00 00 00 00 00 00 00 00
can0  241   [8]  BA 00 00 00 00 00 00 3E      ← 末字节递增 = 计数/状态反馈
```

### 5.2 ⭐ 结论：**不要去碰 CAN**

厂家 2026-10-22 明确答复：

> **「底盘驱动把 can 封装了，直接发 topic 就行」**

**所以：CAN 只作为「已确认存在且活跃」的事实记录，不作为开发接口。**
所有车控走 **ROS `/cmd_vel`**。

---

## 6. ⭐ 控制接口（厂家确认 —— Runtime 负责人重点看）

### 6.1 厂家答复原文要点

| 问题 | 厂家答复 |
| --- | --- |
| 底盘型号 | **Scout 2.0** |
| 启动方式 | `roslaunch iqr_robot_bringup bringup.launch` 启动所有传感器和底盘 |
| **控制接口** | **直接发 `cmd_vel` 就可以控制车，`cmd_vel` 是官方的格式，每个字段都有解释** |
| **前提** | **控制车需要把控制设置为自动模式** |
| CAN | **底盘驱动已经把 CAN 封装了，直接发 topic 就行** |

### 6.2 现场已有的启动脚本

`~/outdoor_start.sh`（现场实拍确认；包名 `iqr_robot_bringup` 已核实）：

```bash
#!/bin/bash
roslaunch iqr_robot_bringup outdoor_bringup.launch
sleep 5
roslaunch scout_navigation  localization_run.launch
sleep 5
roslaunch mpc_formation     muit_dmpc_with_time_mqtt.launch
sleep 3
```

**三个 launch 的含义**：

| launch | 作用 |
| --- | --- |
| `iqr_robot_bringup` / `outdoor_bringup.launch` | 底盘 + 所有传感器 |
| `scout_navigation` / `localization_run.launch` | **Scout 底盘驱动** + 定位 |
| `mpc_formation` / `muit_dmpc_with_time_mqtt.launch` | **多机 DMPC 编队控制**，**走 MQTT** |

### 6.3 ⚠️ 仍未确认的一项（关键）

| # | 未确认 | 影响 | 怎么解决 |
| --- | --- | --- | --- |
| **1** | **「自动模式」怎么切换？** | **不解决的话，`/cmd_vel` 发了车也不动** | 追问厂家：是 topic / service / 遥控器拨档 / App？ |

**已排除的疑问**：包名前缀是 **`iqr`**（不是我先前从照片里误读的 `tqr`），已由现场核实。

**唯一的小差异**：厂家说启动用 `bringup.launch`，而 `~/outdoor_start.sh` 里写的是
`outdoor_bringup.launch` —— 很可能是两个不同的 launch 文件（一个全集、一个室外场景）。
一条命令可确认：

```bash
roslaunch iqr_robot_bringup --files 2>/dev/null | head -20
ls $(rospack find iqr_robot_bringup)/launch/ 2>/dev/null
```

### 6.4 其它待确认（已问厂家，等答复）

- `iqr_robot_bringup` / `scout_navigation` 是厂家提供的吗？源码可看吗？
- `~/catkin_ws/src/swarm_ros` 是做什么的？
- MQTT broker 地址/端口（`muit_dmpc_with_time_mqtt` 用的）
- `/dev/nvme0n1p1` 里有数据吗？能否挂载使用？
- `eth2` 每次重启需重配是有意设计吗？

---

## 7. ⚠️ 对 Runtime 的影响（给 Runtime 负责人）

### 7.1 Runtime 装得上吗 —— **能**

| 项 | 结论 |
| --- | --- |
| 依赖 | `pyproject.toml: dependencies = []` → **零第三方依赖** |
| 唯一要求 | **Python ≥ 3.10** |
| 磁盘 | 源码 0.6 MB，根分区剩 24 GB → **完全够** |
| 装法 | `deadsnakes` PPA 装 `python3.11`，或 `uv python install 3.11` |

**装完即具备**：HTTP 桥 `:8765`、策略门裁决、审计落盘、回放、能力注册表、前端 5178/5179。

### 7.2 但**开车**缺什么 —— 缺一整层

| 现实 | 细节 |
| --- | --- |
| Runtime 会说的协议 | **MAVLink**（`px4_sitl_backend` / `mavlink_backend_session` 等 16 个 adapter 文件） |
| 车听得懂的协议 | **ROS `/cmd_vel` = `geometry_msgs/Twist`** |
| 仓库现状 | `rospy` / `cmd_vel` / `Twist` / `geometry_msgs` / `rosbridge` **命中数全部为 0** |

**→ 没有任何 ROS 支持。这是新增工作，不是配置。**

### 7.3 ⚠️ 硬冲突：Python 版本

| | 版本 |
| --- | --- |
| Runtime 要求 | **≥ 3.10** |
| ROS Noetic `rospy` | **3.8** |

**→ Runtime 里不可能 `import rospy`。**

**三个可选方案**：

| 方案 | 做法 | 评价 |
| --- | --- | --- |
| **A（推荐）** | 写一个 **Python 3.8 中继节点**：收 socket/MQTT → 发 `/cmd_vel` | 版本隔离干净；Runtime 不改；中继可单独测（`rostopic echo` 验证） |
| **B** | `rosbridge_server`（apt，3.8 侧）+ `roslibpy`（纯 Python，3.11 可用）走 WebSocket | 标准做法，无侵入，但多一层 JSON |
| **C** | Runtime 用 `subprocess` 调 `rostopic pub /cmd_vel ...` | 零依赖，适合先验证；不适合高频控制 |

### 7.4 ⚠️ 动作语义对不上（设计问题，不是实现问题）

Runtime 的动作集是按**无人机**设计的：

| Runtime 动作 | 无人机含义 | 地面车（Scout 2.0）怎么办 |
| --- | --- | --- |
| `takeoff` | 起飞 | **无意义**（或映射为"解锁/驻车释放"） |
| `land` | 降落 | **无意义**（或映射为"驻车/急停"） |
| `goto` | 飞到坐标 | 需要**闭环导航**（或交给 `move_base`） |
| `hold_position` | 悬停 | ✅ 直接支持：`cmd_vel` 全零 |
| `return_home` | RTL 回起飞点 | 需自己记起点 + 闭环 |
| `reduce_speed` | 降速 | ✅ **语义天然匹配** |
| `maintain_heading` | 保持航向 | ✅ **语义天然匹配** |

**结论：需要和 Runtime 负责人一起定义「地面车动作集合」，不是写个 adapter 就完。**

### 7.5 其它环境约束（开发时要知道）

| 约束 | 影响 |
| --- | --- |
| **无 `nvidia-smi`** | 不能靠它查显存；用 `tegrastats` |
| **`ensurepip` 缺失** | `python3 -m venv` 可能不稳；用 `uv` 或 `virtualenv` |
| **无 `node`/`npm`** | 三维视图必须用**已构建的 `dist/`**，不能现场构建 |
| **`/usr/bin/python3` 是 3.8** | **绝不能替换** —— `apt`/桌面/`rosdep` 全绑在它上面 |
| **用户无 `dialout` 组** | 若将来走串口，需要 `sudo usermod -aG dialout nvidia` |
| **eMMC 写入寿命** | 审计日志建议放 NVMe |

---

## 8. 数据来源与置信度

| 来源 | 覆盖内容 | 置信度 |
| --- | --- | --- |
| **`recon-offline-env.sh`** 输出（`UGV.txt` 前半） | 系统/Python/GPU/磁盘/ROS/网络/浏览器/工具/能力评级 | ⭐⭐⭐ **实测，最高** |
| **`recon-vehicle.sh`** 输出（`UGV.txt` 后半） | NVMe 设备树/ROS 细节/工作空间/CAN/串口/远程访问 | ⭐⭐⭐ **实测，最高** |
| **厂家微信回复（2026-10-22）** | 底盘型号、启动方式、**控制接口 `/cmd_vel`**、自动模式前提、CAN 已封装 | ⭐⭐⭐ **权威** |
| **同事早期测试报告** | TensorRT 8.5.2.2 / cuDNN 8.6.0 / OpenCV 4.2.0、docker、eMMC 启动 | ⭐⭐ **未复核** |
| 现场实拍照片 | `outdoor_start.sh` 内容、`curl` 联网成功 | ⭐⭐⭐ 实测 |

### 已发现的冲突（以实测为准）

| 冲突项 | 同事报告 | 本文件（实测） | 判定 |
| --- | --- | --- | --- |
| **NVMe** | 「没看到 NVMe」 | `lsblk` 明确列出 `nvme0n1` 477G + `nvme0n1p1` ext4 | **以实测为准：NVMe 存在** |
| **nvcc** | 「不在 PATH」 | `nvcc` 可调用，release 11.4 | **以实测为准：可用** |

---

## 9. 待办清单

| # | 事项 | 需要什么 | 谁 |
| --- | --- | --- | --- |
| 1 | 装 Python 3.11 + Runtime + 验 `/api/health` | 无（有网即可） | 现场 |
| 2 | **追问厂家：「自动模式」怎么切换** | 厂家答复 | 你 |
| 3 | ~~核实 `iqr` / `tqr` 包名~~ **已确认是 `iqr`** | — | 已解决 |
| 4 | 查 NVMe 内容 → 决定是否挂载 | `sudo` | 现场 |
| 5 | 挂载 NVMe 并把审计日志指过去 | `sudo` | 现场 |
| 6 | `eth2` 固定 IP 或改用热点 | `sudo` | 现场 |
| 7 | 定「地面车动作集合」 | 设计讨论 | Runtime 负责人 + 你 |
| 8 | 写 `/cmd_vel` 中继节点（方案 A） | 方案 7 定稿 | 开发 |
| 9 | 确认 MQTT broker 地址 | 厂家答复 | 你 |

---

## 10. 现场复现命令（让任何人能自己验一遍）

```bash
# 系统
uname -a; lsb_release -a; cat /etc/nv_tegra_release 2>/dev/null | head -1

# Python
python3 --version; ls /usr/bin/python3.* 2>/dev/null

# CUDA
which nvcc; nvcc --version 2>/dev/null | tail -2

# ROS
echo $ROS_DISTRO; rosversion -d; ls /opt/ros/

# 磁盘（关键：看 NVMe）
lsblk -f; df -h / /mnt/nvme 2>/dev/null

# 网络
ip -brief a; ip route

# CAN（只订阅 3 秒，不发送）
candump -T 3000 can0 2>/dev/null | head -10

# 车端启动脚本
cat ~/outdoor_start.sh

# 包名核实
ls ~/catkin_ws/src | grep -i robot_bringup
rospack find iqr_robot_bringup 2>/dev/null
rospack find iqr_robot_bringup 2>/dev/null

# 联网
curl -sI http://pypi.org | head -1
```
