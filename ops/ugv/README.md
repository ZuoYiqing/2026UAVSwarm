# UGV（Scout 2.0）现场验证脚本

两个**独立**的 ROS 脚本，用来在离线环境证明两件事：

| 脚本 | 证明什么 |
| --- | --- |
| **`ugv_drive.py`** | **我们能控制这台车的底盘**（轮子按指令转） |
| **`ugv_payload.py`** | **我们能读到它上面的载荷数据**（雷达/相机/IMU/云台/底盘状态） |

**它们不依赖 Runtime，也不依赖 pymavlink。** 只用 `rospy` + 标准库。

> **为什么要这两个脚本**：Runtime 目前的适配层只有 MAVLink，而车只认 ROS `/cmd_vel`；
> Runtime 的 `payload_adapter.py` 是无硬件桩。所以"能控车、能读载荷"这件事，
> 现在只能靠车上的 ROS 直接验证。这是验收时唯一能拿出手的**真机能力证据**。

---

## 为什么之前 `rostopic pub -1` 轮子不动

```bash
rostopic pub -1 /cmd_vel ...        # -1 = 只发【一条】
```

- Scout 底盘固件有**指令超时保护**（约 0.5 秒）：收不到新指令就减速停车
- 所以一条 `0.05 m/s` 只让车动 ≈0.5 秒 ≈ **2.5 厘米**，肉眼看不出来

**`ugv_drive.py` 就是解决这个的：以 10 Hz 持续发布。**

---

## 一、拷到车上

```bash
# 从 U 盘拷（假设挂在 /media/nvidia/...）
mkdir -p ~/ugv_tools
cp /media/nvidia/*/ugv_drive.py ~/ugv_tools/
cp /media/nvidia/*/ugv_payload.py ~/ugv_tools/
chmod +x ~/ugv_tools/*.py
ls -l ~/ugv_tools/
```

---

## 二、环境准备（每次开新终端都要）

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
```

**第二条不能省** —— `/scout_status`、`/pan_tilt_status` 这些消息类型定义在车的包里，
不 source 就解析不到（脚本会给出提示）。

**先确认 ROS 能用**：
```bash
rostopic list | head -5
```
- **能列出来** → 正常
- **`ERROR: Unable to communicate with master!`** → **master 没起，见下面"故障排查"**

---

## 三、第一次跑：先驱动底盘

### ⚠️ 安全前提：**先把车架空或垫起轮子**

`0.05 m/s × 3 秒 = 15 厘米`。第一次跑务必架空。

### 三个终端，**bringup 那个全程别关**

| 终端 | 命令 |
| --- | --- |
| **①** | `roslaunch iqr_robot_bringup bringup.launch` |
| **②** | 等 ① 完全起来后（**约 15 秒**，相机初始化要 13 秒），跑下面的驱动脚本 |
| **③** | 可选：`rostopic echo /scout_status` 盯着反馈 |

**终端 ① 里要看到这些关键行**（说明底盘驱动起来了）：

```
[INFO] Working as scout mini: 0
[INFO] Working as scout omni: 0
Start listening to port: can0
[INFO] Using CAN bus to talk with the robot
```

### 终端 ② 的第一次运行（**脚本化，最可靠**）

```bash
cd ~/ugv_tools
python3 ugv_drive.py --linear 0.05 --duration 3
```

**期望输出**：

```
====================================================================
 ugv_drive  ——  持续向 /cmd_vel 发布，10.0 Hz
 硬上限: 线速度 0.20 m/s, 角速度 0.60 rad/s
 ⚠️ 请确认车已架空或垫起轮子
====================================================================
 发送 lin=+0.050 ang=+0.000 持续 3.0 秒
  指令 lin=+0.050 ang=+0.000  反馈 lin=+0.050  mode=1  state=0  fault=0  batt=25.8V
  ...
  退出中：连发 10 帧零速度…
  已归零。
 完成。
```

**判断标准**：

| 看到什么 | 结论 |
| --- | --- |
| `反馈 lin≈+0.050` 且**轮子在转** | ✅ **通了** |
| `反馈 lin=0.000` 但 `fault=0 mode=1` | ⚠️ 指令没生效，见下面 |
| 没有 `反馈` 这几个字 | ⚠️ `/scout_status` 没订上，先 `source ~/catkin_ws/devel/setup.bash` |

### 交互模式（熟练之后用）

```bash
python3 ugv_drive.py
```

```
> w            前进 3 秒（默认 --hold 3）
> s            后退
> a            左转
> d            右转
> x            立即归零并保持 1 秒
> 0.1          把速度改成 0.1 m/s
> status       打印一次底盘反馈
> q            退出
```

---

## 四、第二次跑：读载荷数据

**bringup 还在跑的前提下**，新开一个终端：

```bash
cd ~/ugv_tools
python3 ugv_payload.py --duration 15 --save-dir ./ugv_samples
```

**期望输出**：

```
====================================================================
 ugv_payload  ——  读取车上载荷数据
 按 topic 动态解析消息类型，不需要事先知道是哪个 msg 包
====================================================================
  样本保存到: /home/nvidia/ugv_tools/ugv_samples
  ✅ 订阅 /BMS_status                     bms_msgs/BmsStatus
  ✅ 订阅 /camera/color/image_raw/compressed  sensor_msgs/CompressedImage
  ✅ 订阅 /camera/depth/points            sensor_msgs/PointCloud2
  ✅ 订阅 /imu/data                       sensor_msgs/Imu
  ✅ 订阅 /odom                           nav_msgs/Odometry
  ✅ 订阅 /pan_tilt_status                pan_tilt_msgs/PanTiltStatus
  ✅ 订阅 /scan                           sensor_msgs/LaserScan
  ✅ 订阅 /scout_status                   scout_msgs/ScoutStatus
--------------------------------------------------------------------
  scan:412点/近0.72 m  |  image_raw:15帧  |  scout_status:mode=1/0.00m/s  |  ...
```

**跑完去看存下来的东西**：

```bash
ls -lh ~/ugv_tools/ugv_samples/
```

| 文件 | 是什么 |
| --- | --- |
| `img_001.jpg` … | **真实的相机彩色图**（能直接打开看） |
| `scan.json` | 雷达摘要（点数、最近距离、角度范围） |
| `scout_status.json` | 底盘状态（速度/模式/故障/电压/电机） |
| `camera_depth_points.json` | 点云元信息（尺寸、字段） |
| `imu_data.json` | IMU 加速度/角速度 |
| `odom.json` | 定位 |
| **`index.json`** | **总索引：每个 topic 收到多少帧 + 最后一次摘要** |

**`index.json` 就是"我们确实拿到了真实载荷数据"的证据文件。**

### 只看关心的 topic

```bash
python3 ugv_payload.py --only /scan,/scout_status --duration 10
```

---

## 五、故障排查

### `ERROR: Unable to communicate with master!`

**原因**：`roscore` 没在跑。
最常见的是：之前跑过 `roslaunch ...`，然后按了 `^C` —— **那会把 master 一起关掉**。

**解决**：重新起 `roslaunch`，**并且保持那个终端开着**。
或者单独起一个 `roscore` 终端。

**自检**：
```bash
rostopic list | head -3
```

### 轮子不转，但 `fault=0`

按这个顺序查（每一步都能自证）：

1. **遥控器拨杆**：厂家确认第二个拨杆拨到**最上面**才是自动模式，拨到中间是手动。
   **`/cmd_vel` 在手动模式下不生效。**
2. **看 `control_mode`**：
   ```bash
   rostopic echo /scout_status | grep control_mode
   ```
   拨遥控器拨杆时盯着看 —— 如果 `control_mode` 跟着变，说明拨杆有效；
   如果一直不变，可能是遥控器没开机/没配对。
3. **看 `base_state` 和 `fault_code`**：非 0 就去问厂家。
4. **确认速度够大**：`0.05 m/s` 在小轮子上很慢，脚本化模式试 `0.1`。

### `/scout_status` 订阅不上

```bash
source ~/catkin_ws/devel/setup.bash
rostopic info /scout_status        # 看 Type 是什么，和包名对不对
```

### 图像存不下来

`/camera/color/image_raw/compressed` 必须存在（相机节点在发压缩流）：

```bash
rostopic hz /camera/color/image_raw/compressed
```

如果只有 `/camera/color/image_raw`（未压缩），本脚本**不处理**它
（需要 cv2 或 cv_bridge）。告诉集成侧，我们改脚本。

---

## 六、脚本的安全设计（别删这些）

`ugv_drive.py` 里：

1. **10 Hz 持续发布**，空闲时发全零 —— 底盘不会因"没收到指令"而行为怪异
2. **速度硬上限** `--max-linear 0.20` / `--max-angular 0.60` —— 按键怎么按都超不了
3. **加速度限幅** `--slew-linear 0.30` —— 不突变跳变
4. **每条移动指令只持续 `--hold 3` 秒**，到点自动归零
5. **Ctrl-C / q 退出时连发 10 帧零速度** —— 不把车丢在运动状态
6. **全程读 `/scout_status`**，把 `control_mode`/`fault_code`/实际速度打在屏幕上

> ⚠️ **这三条要一起用才安全**：脚本的软急停（发零）、底盘自身的指令超时、
> **以及遥控器拨回中间的人工接管**。厂家明确说 ROS 里没有急停功能，
> **所以最可靠的永远是把拨杆拨回中间。**

---

## 七、下一步（这两个脚本之后）

这两个脚本**不接 Runtime**。它们的作用是"证明能力 + 拿到证据"。

**接 Runtime 的路径**（详见 `ops/PROMPT_to_runtime_20261104.md` 第四节 A）：
推荐在车端写一个 **MAVLink 垫片**（pymavlink，py3.8），把 MAVLink 速度指令转成
`/cmd_vel`、把 `/scout_status` 回填成 MAVLink 遥测 —— 这样 **Runtime 零改动**。

**为什么不在 Runtime 里 import rospy**：ROS Noetic 是 Python 3.8，
而 Runtime 要求 ≥3.10。**这是硬冲突，绕不过去。**
