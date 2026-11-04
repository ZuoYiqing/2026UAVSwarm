#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ugv_payload.py —— 读 Scout 2.0 车上的载荷数据，并存成可用样本

它解决什么问题
--------------
Runtime 的 `payload_adapter.py` 是**无硬件桩**（文件里自称 intentionally hardware-free），
所以从 Runtime 那条路拿不到任何真实的相机/雷达/云台数据。

但**车上的 ROS 里这些数据全都在发**：
    /scan                              激光雷达（pointcloud_to_laserscan 转好的）
    /camera/color/image_raw/compressed RGBD 相机彩色图（JPEG，已压缩，不需要 cv2）
    /camera/depth/points              深度点云（PointCloud2）
    /imu/data , /imu/data0             HWT9053 IMU
    /pan_tilt_status                  云台角度
    /odom , /robot_pose_ekf/odom_combined   定位
    /scout_status                     底盘状态（速度/模式/故障/电压/电机）
    /BMS_status                       电池管理

这个脚本用**纯 rospy + 标准库**把它们读出来（不需要 cv2、不需要 numpy 也能跑摘要），
并且可以**存成文件**，作为"我们确实拿到了真实载荷数据"的证据。

为什么不用 cv2
--------------
`/camera/color/image_raw/compressed` 是 `sensor_msgs/CompressedImage`，
里面的 `data` **本来就是 JPEG 字节流** —— 直接写进 .jpg 文件就是一张能打开的图。
所以完全不需要图像库，避免在车上装依赖。

用法
----
    # 只看摘要（1 秒一行），Ctrl-C 退出
    python3 ugv_payload.py

    # 跑 15 秒，把样本存到 ./ugv_samples
    python3 ugv_payload.py --duration 15 --save-dir ./ugv_samples

    # 只关心雷达和底盘状态
    python3 ugv_payload.py --only /scan,/scout_status

依赖
----
    source /opt/ros/noetic/setup.bash
    若 /scout_status、/pan_tilt_status 的类型不在标准包里，还要：
    source ~/catkin_ws/devel/setup.bash

本脚本用 ROS master 的 topic 类型表**动态解析消息类型**，
所以即使不知道 `/pan_tilt_status` 是哪个 msg 包定义的，也能自动订阅上。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional

try:
    import rospy
    import rosgraph
    from roslib.message import get_message_class
except ImportError:
    sys.stderr.write(
        "导入 rospy 失败。请在车上的 ROS 环境里跑：\n"
        "  source /opt/ros/noetic/setup.bash\n"
        "  source ~/catkin_ws/devel/setup.bash\n"
    )
    raise


#: 我们关心的 topic。值是"期望的类型"，只用于在拿不到类型表时兜底。
WANTED = {
    "/scan": "sensor_msgs/LaserScan",
    "/camera/color/image_raw/compressed": "sensor_msgs/CompressedImage",
    "/camera/depth/points": "sensor_msgs/PointCloud2",
    "/imu/data": "sensor_msgs/Imu",
    "/imu/data0": "sensor_msgs/Imu",
    "/odom": "nav_msgs/Odometry",
    "/robot_pose_ekf/odom_combined": "geometry_msgs/PoseWithCovarianceStamped",
    "/scout_status": "scout_msgs/ScoutStatus",
    "/pan_tilt_status": "pan_tilt_msgs/PanTiltStatus",
    "/BMS_status": "bms_msgs/BmsStatus",
}

#: 需要存文件时，允许存图的 topic（其余存 JSON 摘要）
IMAGE_TOPICS = {"/camera/color/image_raw/compressed"}


class Sample:
    """某个 topic 的一条摘要（不保存原始大数组，避免文件巨大）。"""

    def __init__(self, topic: str, msg_type: str) -> None:
        self.topic = topic
        self.msg_type = msg_type
        self.count = 0
        self.last_summary: Dict[str, Any] = {}
        self.last_time = 0.0
        self.saved = 0


def summarize(topic: str, msg: Any) -> Dict[str, Any]:
    """把消息转成一个简短、可读的字典。不认识的类型退化为字符串前 200 字。"""
    s: Dict[str, Any] = {"topic": topic}

    # ---- 激光雷达 ----
    if hasattr(msg, "ranges") and hasattr(msg, "angle_min"):
        rs = [r for r in msg.ranges if r == r and r != float("inf")]  # 去 NaN 和 inf
        s["points"] = len(msg.ranges)
        s["valid"] = len(rs)
        s["range_min"] = float(msg.range_min)
        s["range_max"] = float(msg.range_max)
        s["min_m"] = round(min(rs), 3) if rs else None
        s["mean_m"] = round(sum(rs) / len(rs), 3) if rs else None
        s["angle_min_deg"] = round(float(msg.angle_min) * 57.2958, 1)
        s["angle_max_deg"] = round(float(msg.angle_max) * 57.2958, 1)
        return s

    # ---- 压缩图像 ----
    if hasattr(msg, "data") and hasattr(msg, "format"):
        data = getattr(msg, "data", b"")
        s["bytes"] = len(data)
        s["format"] = str(getattr(msg, "format", ""))
        return s

    # ---- 点云 ----
    if hasattr(msg, "width") and hasattr(msg, "height") and hasattr(msg, "fields"):
        s["width"] = int(msg.width)
        s["height"] = int(msg.height)
        s["fields"] = [f.name for f in msg.fields][:8]
        return s

    # ---- IMU ----
    if hasattr(msg, "linear_acceleration") and hasattr(msg, "angular_velocity"):
        la, av = msg.linear_acceleration, msg.angular_velocity
        s["accel"] = [round(la.x, 3), round(la.y, 3), round(la.z, 3)]
        s["gyro"] = [round(av.x, 3), round(av.y, 3), round(av.z, 3)]
        return s

    # ---- 里程/位姿 ----
    if hasattr(msg, "pose") and hasattr(msg.pose, "pose"):
        p = msg.pose.pose.position
        s["position"] = [round(p.x, 3), round(p.y, 3), round(p.z, 3)]
        return s

    # ---- Scout 底盘状态（字段名来自现场实测） ----
    for key in ("linear_velocity", "angular_velocity", "control_mode",
                "base_state", "fault_code", "battery_voltage"):
        if hasattr(msg, key):
            v = getattr(msg, key)
            s[key] = round(v, 3) if isinstance(v, float) else v
    if hasattr(msg, "motor_states"):
        try:
            s["motors"] = len(msg.motor_states)
            if msg.motor_states:
                m0 = msg.motor_states[0]
                s["motor0"] = {
                    "current": round(float(getattr(m0, "current", 0.0)), 2),
                    "rpm": round(float(getattr(m0, "rpm", 0.0)), 1),
                    "temp": round(float(getattr(m0, "temperature", 0.0)), 1),
                }
        except Exception:  # noqa: BLE001
            pass
    if len(s) > 1:
        return s

    # ---- 兜底：把消息字符串化 ----
    s["raw"] = str(msg)[:200]
    return s


class PayloadReader:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.samples: Dict[str, Sample] = {}
        self.images_saved: Dict[str, int] = {}

        self.save_dir: Optional[str] = None
        if args.save_dir:
            self.save_dir = os.path.abspath(args.save_dir)
            os.makedirs(self.save_dir, exist_ok=True)
            print("  样本保存到: " + self.save_dir)

    def resolve_types(self) -> Dict[str, str]:
        """从 ROS master 拿 topic→类型表；拿不到就用 WANTED 里的兜底值。"""
        topics = self.args.only.split(",") if self.args.only else list(WANTED.keys())
        topics = [t.strip() for t in topics if t.strip()]

        live: Dict[str, str] = {}
        try:
            master = rosgraph.Master("/ugv_payload")
            for t, typ in master.getTopicTypes():
                live[t] = typ
        except Exception as exc:  # noqa: BLE001 - 拿不到就退化
            print("  ⚠️ 读不到 topic 类型表（%s），用内置兜底类型" % exc)

        resolved: Dict[str, str] = {}
        missing = []
        for t in topics:
            if t in live:
                resolved[t] = live[t]
            elif t in WANTED:
                resolved[t] = WANTED[t]
                missing.append(t)
        if missing:
            print("  ⚠️ 这些 topic 当前没在发，仍按已知类型尝试订阅: " + ", ".join(missing))
        return resolved

    def subscribe_all(self) -> None:
        resolved = self.resolve_types()
        if not resolved:
            print("  ❌ 没有可订阅的 topic。先确认 bringup 在跑，并且用 rostopic list 看一眼。")
            return

        for topic, type_str in sorted(resolved.items()):
            cls = get_message_class(type_str)
            if cls is None:
                print("  ⚠️ 解析不了类型 %-45s %s（消息包没 source？）" % (topic, type_str))
                continue
            self.samples[topic] = Sample(topic, type_str)
            rospy.Subscriber(topic, cls, self._make_cb(topic), queue_size=10)
            print("  ✅ 订阅 %-42s %s" % (topic, type_str))

    def _make_cb(self, topic: str):
        def _cb(msg: Any) -> None:
            sample = self.samples[topic]
            sample.count += 1
            sample.last_time = time.time()
            summary = summarize(topic, msg)
            sample.last_summary = summary
            if self.save_dir:
                self._maybe_save(topic, msg, summary)
        return _cb

    def _maybe_save(self, topic: str, msg: Any, summary: Dict[str, Any]) -> None:
        sample = self.samples[topic]
        # 图像：每 --image-every 帧存一张
        if topic in IMAGE_TOPICS:
            n = self.images_saved.get(topic, 0)
            if n >= self.args.max_images:
                return
            if sample.count % max(1, self.args.image_every) != 0:
                return
            data = getattr(msg, "data", b"")
            if not data:
                return
            name = "img_{:03d}.jpg".format(n + 1)
            with open(os.path.join(self.save_dir, name), "wb") as f:  # type: ignore[arg-type]
                f.write(bytes(data))
            self.images_saved[topic] = n + 1
            sample.saved += 1
            return

        # 其余：每个 topic 只存一次最后一次摘要（够作证据，不产生大量文件）
        if sample.saved == 0:
            safe = topic.strip("/").replace("/", "_")
            path = os.path.join(self.save_dir, safe + ".json")  # type: ignore[arg-type]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            sample.saved += 1

    def print_summary(self) -> None:
        alive = {t: s for t, s in self.samples.items() if s.count > 0}
        dead = [t for t, s in self.samples.items() if s.count == 0]
        if not self.samples:
            return
        bits = []
        for t, s in sorted(alive.items()):
            short = t.rsplit("/", 1)[-1]
            if "points" in s.last_summary:
                bits.append("%s:%s点/近%s m" % (
                    short, s.last_summary.get("valid"), s.last_summary.get("min_m")))
            elif "bytes" in s.last_summary:
                bits.append("%s:%d帧" % (short, s.count))
            elif "control_mode" in s.last_summary:
                bits.append("%s:mode=%s/%.2fm/s" % (
                    short, s.last_summary.get("control_mode"),
                    s.last_summary.get("linear_velocity") or 0.0))
            elif "accel" in s.last_summary:
                bits.append("%s:%d帧" % (short, s.count))
            elif "position" in s.last_summary:
                bits.append("%s:(%.2f,%.2f)" % (
                    short, s.last_summary["position"][0], s.last_summary["position"][1]))
            else:
                bits.append("%s:%d帧" % (short, s.count))
        line = "  " + "  |  ".join(bits)
        if dead:
            line += "  |  未收到: " + ",".join(x.rsplit("/", 1)[-1] for x in dead)
        print(line, flush=True)

    def write_index(self) -> None:
        if not self.save_dir:
            return
        index = {
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "topics": {
                t: {
                    "msg_type": s.msg_type,
                    "messages_received": s.count,
                    "last_summary": s.last_summary,
                }
                for t, s in sorted(self.samples.items())
            },
        }
        with open(os.path.join(self.save_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        print("  索引已写到 " + os.path.join(self.save_dir, "index.json"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="读取 Scout 2.0 车上的载荷数据（雷达/相机/IMU/云台/底盘状态）")
    p.add_argument("--duration", type=float, default=None,
                   help="运行多少秒后自动退出（不填则一直跑到 Ctrl-C）")
    p.add_argument("--save-dir", default=None,
                   help="把样本存到这个目录（图片 .jpg、其余 .json）")
    p.add_argument("--only", default=None,
                   help="只订阅这些 topic，逗号分隔，例如 /scan,/scout_status")
    p.add_argument("--print-every", type=float, default=1.0, help="摘要打印间隔秒")
    p.add_argument("--image-every", type=int, default=30,
                   help="每隔多少帧存一张图（默认 30 帧 ≈ 1 秒）")
    p.add_argument("--max-images", type=int, default=10,
                   help="每个图像 topic 最多存多少张（默认 10）")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    rospy.init_node("ugv_payload", anonymous=True)

    print("=" * 72)
    print(" ugv_payload  ——  读取车上载荷数据")
    print(" 按 topic 动态解析消息类型，不需要事先知道是哪个 msg 包")
    print("=" * 72)

    reader = PayloadReader(args)
    reader.subscribe_all()
    if not reader.samples:
        print("  没有可订阅的 topic，退出。")
        return 1
    print("-" * 72)

    end = time.time() + args.duration if args.duration else None
    last_print = 0.0
    try:
        while not rospy.is_shutdown():
            now = time.time()
            if end is not None and now >= end:
                break
            if now - last_print >= args.print_every:
                last_print = now
                reader.print_summary()
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        print("-" * 72)
        print(" 汇总：")
        for t, s in sorted(reader.samples.items()):
            flag = "✅" if s.count else "❌"
            print("   %s %-44s %6d 帧  %s" % (flag, t, s.count, s.msg_type))
        reader.write_index()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except rospy.ROSInterruptException:
        pass
