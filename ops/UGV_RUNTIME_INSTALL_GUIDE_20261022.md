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

哪条能返回路径，就是哪个。

---

## 六、⚠️ 已知错误（现场实测踩过的，共 6 个）

> 这一节是按现场实际报错写的，**症状 → 原因 → 解法** 一一对应。
> 三个系统（Windows cmd / Linux bash / Ubuntu 的两套 Python）混在一台车上，
> 大部分坑都来自"命令敲在了错误的 shell"或"用错了 Python"。

### 错误 1：`set PYTHONPATH=%CD%\src` —— Windows 语法混进 bash

```
nvidia@nvidia:~/uavswarm$ set PYTHONPATH=%CD%\src
nvidia@nvidia:~/uavswarm$ python -m uav_runtime.http.server
/usr/bin/python: No module named uav_runtime.http
```

| | |
| --- | --- |
| **症状** | `set` 那行**没有报错也没有效果**，接着就 `No module named` |
| **原因** | `set VAR=value` 是 **cmd.exe** 语法。bash 里 `set` 是shell 内建，不这样赋值；`%CD%` 也不存在 |
| **正确写法** | `export PYTHONPATH="$PWD/src"`（单独一行）<br>或 `PYTHONPATH="$PWD/src" 命令`（写在同一条命令前） |

```bash
# 一次性（推荐，不留副作用）
PYTHONPATH="$PWD/src" python3.11 -m uav_runtime.http.server

# 或分两步
export PYTHONPATH="$PWD/src"
python3.11 -m uav_runtime.http.server
```

### 错误 2：`python` 是 Python 2.7

```
/usr/bin/python: No module named uav_runtime.http
/usr/bin/python: No module named http
```

| | |
| --- | --- |
| **症状** | `python -m ...` 全报 `No module named` |
| **原因** | 本机 `python` → **Python 2.7.18**（recon 记录在案）。Python 2 没有 `http.server` 也没有本项目的包 |
| **正确写法** | **永远用 `python3.11`**，不要用 `python`，也不要用 `python3` |

### 错误 3：`dataclass() got an unexpected keyword argument 'slots'` ← **最典型**

```
nvidia@nvidia:~/uavswarm$ PYTHONPATH="$PWD/src" python3 -m uav_runtime.http.server
Traceback (most recent call last):
  ...
  File "/home/nvidia/uavswarm/src/uav_runtime/adapters/mavlink_backend_config.py", line 7, in <module>
    @dataclass(slots=True)
TypeError: dataclass() got an unexpected keyword argument 'slots'
```

| | |
| --- | --- |
| **症状** | import 阶段就崩，报 `dataclass() ... 'slots'` |
| **原因** | **`python3` 是 Python 3.8**，而 `@dataclass(slots=True)` 是 **Python 3.10 才加入**的参数 |
| **这说明什么** | ⚠️ **不是 bug** —— 这正是 `pyproject.toml: requires-python = ">=3.10"` 那条要求在生效 |
| **正确写法** | 用 3.11：`PYTHONPATH="$PWD/src" python3.11 -m uav_runtime.http.server` |

> 这个错误很好认：**只要看到 `dataclass(slots=True)`，就是 Python 版本太低。**

### 错误 4：`E: Invalid operation software-properties-common` —— 漏了 `install`

```
nvidia@nvidia:~$ sudo apt -y software-properties-common
E: Invalid operation software-properties-common
```

| | |
| --- | --- |
| **原因** | 漏了 `install` 这个子命令 |
| **正确写法** | `sudo apt install -y software-properties-common` |

**不过本机最终没走 apt 路线** —— 用 `uv` 更省事，见错误 5。

### 错误 5（推荐路线）：用 `uv` 装 Python 3.11，绕开 apt

现场实测这个方式最干净（**不需要 sudo，不动系统 Python**）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
uv python install 3.11
uv python find 3.11        # 打印解释器完整路径
python3.11 --version        # 实测输出 Python 3.11.18
```

**装到的位置**：

```
/home/nvidia/.local/share/uv/python/cpython-3.11.18-linux-aarch64-gnu/bin/python3.11
```

**若 `python3.11` 不在 PATH**，用完整路径：

```bash
PYTHONPATH="$PWD/src" \
  /home/nvidia/.local/share/uv/python/cpython-3.11.18-linux-aarch64-gnu/bin/python3.11 \
  -m uav_runtime.http.server
```

### 错误 6：5179 报 404 —— `dist/` 没解出来

```
127.0.0.1 - - "GET / HTTP/1.1" 404 -
```

| | |
| --- | --- |
| **症状** | 浏览器 5179 显示 `Error code: 404 / File not found` |
| **原因** | `01-source.tar.gz` **不含 `dist/`**（被 git 忽略），三维构建产物在 `02-frontend-3d-dist.tar.gz` 里 |
| **正确写法** | `tar -xzf 02-frontend-3d-dist.tar.gz -C frontend/swarm-console/simulation-3d` |

**附带的 404**：`GET /api/health 404` 是因为三维页面在自己的源（5179）上找 `/api`，
而 `python -m http.server` 没有 `/api` 代理（只有 Vite 开发模式配了 proxy）。
三维视图本身不依赖 `/api`，解出 `dist` 后这个 404 自然消失。

### 速查表

| 报错 | 一行解法 |
| --- | --- |
| `No module named uav_runtime.http` + `set PYTHONPATH=%CD%\src` | 那是 cmd 语法，改用 `PYTHONPATH="$PWD/src" python3.11 ...` |
| `/usr/bin/python: No module named http` | `python` 是 2.7，改用 `python3.11` |
| `dataclass() got an unexpected keyword argument 'slots'` | Python 3.8，改用 `python3.11` |
| `E: Invalid operation software-properties-common` | 漏 `install`，或改用 `uv` |
| 5179 `404 File not found` | 没解 `02-frontend-3d-dist.tar.gz` |

### 一条命令覆盖所有坑

```bash
cd ~/uavswarm && PYTHONPATH="$PWD/src" python3.11 -m uav_runtime.http.server
```

**实测成功输出**：

```
uav_runtime_http_bridge listening on http://127.0.0.1:8765/api
```

---

## 七、建议的落地顺序

```
① 装 Python 3.11 + 放源码 + 起 Runtime + /api/health        ✅ 已完成（2026-10）
② 追厂家问"自动模式怎么设"                                  ← 卡点
③ ~~核实 iqr/tqr~~ 已确认是 iqr
④ 挂载 NVMe（放日志和源码，保护 eMMC）                       ← 需要 sudo
⑤ 写 /cmd_vel 中继节点（方案 A）                             ← 需要设计确认
⑥ 和 Runtime 负责人定"地面车动作集合"                        ← 需要设计确认
```

**① 已完成。** 现场实测：

```
nvidia@nvidia:~/uavswarm$ PYTHONPATH="$PWD/src" python3.11 -m uav_runtime.http.server
uav_runtime_http_bridge listening on http://127.0.0.1:8765/api
```

主控台 5178 已能完整渲染（Runtime 未启动时显示 `Runtime API OFFLINE`）。
