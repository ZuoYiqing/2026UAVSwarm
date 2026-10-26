# UGV 装 Runtime 的安装指南（Jetson AGX Orin）

**目标**：在这台车上把 Runtime（`uav_runtime` HTTP 桥 `:8765`）跑起来。
**依据**：现场 recon（`UGV.txt`）+ 厂家 2026-10-22 微信回复。

---

## 厂家回复要点（已确认）

| 问题 | 厂家答复 |
| --- | --- |
| 底盘型号 | **Scout 2.0** |
| 启动方式 | `roslaunch iqr_robot_bringup bringup.launch` 启动所有传感器和底盘 |
| **控制接口** | **直接发 `/cmd_vel` 就可以控制车**，`cmd_vel` 是官方格式，每个字段有解释 |
| 前提 | **控制车需要把控制设置为自动模式** |
| CAN | **底盘驱动已经把 CAN 封装了，直接发 topic 就行** |

> ⚠️ 注意：厂家写的是 `iqr_robot_bringup`，而现场 `~/outdoor_start.sh` 里是
> `iqr_robot_bringup`，launch 名也不同（`bringup.launch` vs `outdoor_bringup.launch`）。
> **这两个名称需要现场核实**（很可能是我从屏幕照片上读错了 `iqr` 的 `q`）。

**结论：不需要碰 CAN 协议。控制路径是 ROS + `/cmd_vel`。**

---

## 一、这台机器的真实约束

| 项 | 值 | 对安装的影响 |
| --- | --- | --- |
| Python | **3.8.10**（另有 3.9.5） | ❌ **Runtime 要求 ≥3.10** |
| 网络 | 能联网 | ✅ 可以直接装 |
| 根分区 | eMMC 55G，**剩 24G** | ✅ 够（Runtime 源码只有 0.6 MB） |
| NVMe | 477G ext4，**未挂载** | 建议后续挂载放日志 |
| ROS | Noetic（Python 3.8） | ⚠️ **与 Runtime 的 3.10 冲突，见第四节** |
| 浏览器 | firefox 110 + `DISPLAY=:0` | ✅ 能直接看控制台 |
| SSH | ✅ 22 端口 | ✅ 可远程操作 |

**Runtime 本体零第三方依赖**（`pyproject.toml: dependencies = []`），
所以装 Runtime 只需要 **一个 ≥3.10 的解释器**，不需要 pymavlink。

---

## 二、安装步骤（手敲）

### 第 0 步：先确认能上网

```bash
ping -c 2 8.8.8.8
curl -sI https://pypi.org | head -1
```

**如果不通**（`eth2` 没有 IPv4），先配网：

```bash
ip a show eth2
sudo dhclient eth2
ip a show eth2          # 看有没有拿到 192.168.x.x
```

或者用热点方案（你提到 UGV 能开热点）。

### 第 1 步：装 Python 3.11（并排装，不动 3.8）

```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

**验证（两条都要对）**：

```bash
python3.11 --version        # 期望 Python 3.11.x
/usr/bin/python3 --version  # 期望还是 Python 3.8.10（没被换掉才对）
```

> **⚠️ 绝对不要** `update-alternatives` 把 `python3` 指向 3.11，也不要用
> `apt install python3` 升级 —— Ubuntu 20.04 的 `apt`、桌面、`rosdep` 全绑在 3.8 上，
> 替换会破坏系统。

### 第 2 步：把源码放上去

源码只有 `src/uav_runtime/`（17 个子包）+ `pyproject.toml` + `config/`，约 0.6 MB。

**方式 A：U 盘**（现实里最省事，你们已经在用 `/media/nvidia/6292-E606`）

```bash
mkdir -p ~/uavswarm
# 假设 tar.gz 已经在 U 盘上
tar -xzf /media/nvidia/6292-E606/发送文件/01-source.tar.gz -C ~/uavswarm
ls ~/uavswarm/src/uav_runtime/http/server.py    # 必须存在
```

**方式 B：从有网机器 scp**

```bash
scp nvidia@<中间笔记本IP>:~/uavswarm/01-source.tar.gz ~/
```

### 第 3 步：起 Runtime

```bash
cd ~/uavswarm
PYTHONPATH="$PWD/src" python3.11 -m uav_runtime.http.server
```

**期望**：

```
uav_runtime_http_bridge listening on http://127.0.0.1:8765/api
```

### 第 4 步：验证（另开一个终端）

```bash
curl http://127.0.0.1:8765/api/health
```

**期望**：`{"status": "ok", "service": "uav_runtime_http_bridge", ...}`

```bash
curl http://127.0.0.1:8765/api/capabilities | head -20
curl http://127.0.0.1:8765/api/vehicle-snapshot
```

**`vehicle-snapshot` 是空的 —— 这是正常的**，因为 Runtime 目前没有连任何载具。

### 第 5 步：起前端（可选，车上能直接看）

```bash
# 主控台 5178
cd ~/uavswarm
python3 -m http.server 5178 --bind 127.0.0.1 --directory frontend/swarm-console &

# 三维 5179（需要先把 02-frontend-3d-dist 解到 simulation-3d 里）
python3 -m http.server 5179 --bind 127.0.0.1 --directory frontend/swarm-console/simulation-3d/dist &
```

然后车上有 `DISPLAY=:0` + firefox，可以本地打开 `http://127.0.0.1:5178/`。

---

## 三、装完之后"能干什么、不能干什么"（必须说清）

### ✅ 装完就有了

| 能力 | 验证方式 |
| --- | --- |
| HTTP 桥 `:8765` | `curl /api/health` |
| **策略门真的会裁决** | `submit-action land --demo-link-state lost` → `deny` + `blocked` |
| **审计落盘** | `audit/runtime.audit.jsonl` 两行/次 |
| **回放** | `replay-last` |
| 能力注册表 | `list-capabilities` |
| 前端显示 | 5178 / 5179 |
| 前端能连上 Runtime | 主控台顶部显示"在线" |

### ❌ 装完**还不能**开车

**因为 Runtime 的适配层全是 MAVLink，而车吃的是 ROS `/cmd_vel`。**

```
Runtime 现在会说的：  MAVLink（SET_POSITION_TARGET / COMMAND_LONG ...）
车现在听得懂的：      ROS  /cmd_vel（geometry_msgs/Twist）
                      ↑ 厂家已确认：底盘驱动封装了 CAN，只认 topic
```

**仓库里 `rospy` / `cmd_vel` / `Twist` 的命中数都是 0** —— 一行都没有。

**这不是配置问题，是需要新写一个适配层。**

---

## 四、要开车，还差一块积木（以及一个版本冲突）

### 冲突在哪

| | 版本 |
| --- | --- |
| Runtime 要求 | Python **≥ 3.10** |
| ROS Noetic 的 `rospy` | Python **3.8** |

**所以在 Runtime 里直接 `import rospy` 是不可能的**（3.11 装不上 Noetic 的 rospy）。

### 三个可行方案

| 方案 | 做法 | 优点 | 缺点 |
| --- | --- | --- | --- |
| **A（推荐）** | 写一个 **Python 3.8 的中继节点**：订阅一个简单 socket/MQTT，转成 `/cmd_vel` | 版本隔离干净；Runtime 不用改；中继可以单独测 | 多一个进程要维护 |
| **B** | 装 `rosbridge_server`（apt），Runtime 用 `roslibpy`（纯 Python，3.11 可用）通过 WebSocket 发 Twist | 标准做法，不侵入 | 要在 3.8 那侧装 rosbridge；多一层 JSON |
| **C** | Runtime 用 `subprocess` 调 `rostopic pub /cmd_vel ...` | 零依赖，最快验证 | 每次启动一个进程，不适合高频控制 |

**我倾向 A**：中继节点只做一件事（收指令 → 发 Twist），
**可以脱离 Runtime 单独测**（用 `rostopic echo` 看它发了什么），出了问题好定位。

### 但还有两个语义问题要先定

即使有了 `/cmd_vel`，**动作语义也不一样**：

| Runtime 的动作 | 无人机含义 | 地面车怎么办 |
| --- | --- | --- |
| `takeoff` / `land` | 起飞 / 降落 | **无意义**（或映射为"解锁/驻车"） |
| `goto` | 飞到坐标 | 需要一个**闭环导航**（或交给 `move_base`） |
| `hold_position` | 悬停 | → `cmd_vel` 全零 |
| `return_home` | RTL 回起飞点 | 需要自己记起点 + 闭环 |
| `reduce_speed` / `maintain_heading` | 降速 / 保持航向 | **这两个语义天然适合车** |

**所以"Runtime 控车"不是写个 adapter 就完了，还要定义"地面车的动作集合"。**
这是设计问题，建议和 Runtime 负责人一起定。

---

## 五、另外两个要补的信息

### 1. 追着厂家问一句"自动模式怎么设"

厂家说：**"控制车需要把控制设置为自动模式"**。但没说怎么设。

**追问方式**：

> 自动模式怎么切换？是 ROS topic / service，还是遥控器拨档，还是 App？
> 如果是 ROS 接口，麻烦给一下 topic 或 service 的名字和消息类型。

**这一条不解决，`/cmd_vel` 发了车也不动。**

### 2. ~~核实包名~~ **已确认是 `iqr`**（原以为可能是 `tqr`，是我从屏幕照片上读错了）

厂家写 `iqr_robot_bringup`，`~/outdoor_start.sh` 里是 `iqr_robot_bringup`。

```bash
ls ~/catkin_ws/src/ | grep -i robot_bringup
rospack find iqr_robot_bringup 2>/dev/null
rospack find iqr_robot_bringup 2>/dev/null
```

哪条能返回路径，就是哪个。**很可能是我从屏幕照片上把 `q` 看成了 `t`。**

---

## 六、建议的落地顺序

```
① 装 Python 3.11 + 放源码 + 起 Runtime + /api/health        ← 今天就能做完
② 追厂家问"自动模式怎么设"                                  ← 卡点
③ ~~核实 iqr/tqr~~ 已确认是 iqr
④ 挂载 NVMe（放日志和源码，保护 eMMC）                       ← 需要 sudo
⑤ 写 /cmd_vel 中继节点（方案 A）                             ← 需要设计确认
⑥ 和 Runtime 负责人定"地面车动作集合"                        ← 需要设计确认
```

**① 是纯安装，不依赖任何外部答复，可以马上做。**
