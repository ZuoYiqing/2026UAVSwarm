#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ugv_drive.py —— 用 /cmd_vel 驱动 Scout 2.0 底盘（离线环境用的最小控制器）

为什么需要这个脚本
------------------
现场之前用 `rostopic pub -1 /cmd_vel ...` 试，轮子不动。原因不是接口不通，而是：
  · `-1` 只发【一条】消息
  · Scout 底盘固件有指令超时保护（约 0.5 秒）：收不到新指令就减速停车
  · 所以一条 0.05 m/s 的指令只让车动约 0.5 秒 ≈ 2.5 厘米，肉眼看不出

这个脚本做的事就是：**以固定频率（默认 10 Hz）持续发布 /cmd_vel**，
并且把"发多少、发多久、什么时候归零"都写清楚，方便架空验证。

安全设计（都很重要，别删）
--------------------------
1. 每 10 Hz 发一帧，空闲时发全零 —— 底盘不会因为"没收到指令"而行为怪异
2. 速度硬上限（--max-linear / --max-angular），键盘怎么按都不会超
3. 加速度限幅（--slew-linear / --slew-angular），不会突变跳变
4. 每条移动指令只持续 --hold 秒（默认 3 秒），到点自动归零
5. Ctrl-C / q 退出时，连续发 10 帧零速度再断开 —— 不把车丢在半途
6. 全程读 /scout_status，把 control_mode / fault_code / 实际速度打在屏幕上，
   你能立刻看到"指令有没有被接受"

用法
----
    # 第一次跑，建议脚本化（不需要按键，最可靠）
    python3 ugv_drive.py --linear 0.05 --duration 3

    # 交互式（输入命令后回车）
    python3 ugv_drive.py

    # 只发零速度，验证急停通道
    python3 ugv_drive.py --zero --duration 3

交互命令（输入后按回车）
    w        前进（持续 --hold 秒）
    s        后退
    a        左转（原地）
    d        右转（原地）
    x        立即归零并保持 1 秒
    0.1      把前进速度设为 0.1 m/s（受 --max-linear 限制）
    status   打印一次 /scout_status 关键字段
    q        退出

⚠️ 跑之前先把车架空或垫起轮子。0.05 m/s × 3 秒 = 15 厘米。
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

try:
    import rospy
    from geometry_msgs.msg import Twist
except ImportError:
    sys.stderr.write(
        "导入 rospy 失败。这个脚本必须在车上的 ROS 环境里跑：\n"
        "  source /opt/ros/noetic/setup.bash\n"
        "如果 /scout_status 也要读，还需要车的消息包：\n"
        "  source ~/catkin_ws/devel/setup.bash\n"
    )
    raise


class DriveController:
    """把"想要的速度"以固定频率转成 /cmd_vel，并做限幅与归零。"""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.pub = rospy.Publisher(args.topic, Twist, queue_size=10)

        # 目标速度（会被限幅后发给底盘）
        self.target_linear = 0.0
        self.target_angular = 0.0

        # 实际发出去的速度（做加速度限幅用）
        self.sent_linear = 0.0
        self.sent_angular = 0.0

        # 当前这条移动指令还剩多少秒；到 0 就归零
        self.hold_remaining = 0.0

        # 从 /scout_status 读到的最新反馈（读不到就是 None）
        self.fb_linear: Optional[float] = None
        self.fb_angular: Optional[float] = None
        self.fb_control_mode: Optional[int] = None
        self.fb_base_state: Optional[int] = None
        self.fb_fault: Optional[int] = None
        self.fb_battery: Optional[float] = None

        self._subscribed = False

    # ---------- 反馈订阅（尽力而为：消息包不在也不影响驱动） ----------
    def subscribe_status(self) -> None:
        try:
            # 不同版本的 scout_msgs 路径略有差异，全部试一遍
            msg_type = None
            for mod, name in (
                ("scout_msgs.msg", "ScoutStatus"),
                ("scout_msgs.msg", "ScoutStatusMsg"),
            ):
                try:
                    m = __import__(mod, fromlist=[name])
                    msg_type = getattr(m, name)
                    break
                except (ImportError, AttributeError):
                    continue
            if msg_type is None:
                raise ImportError("scout_msgs 里没有 ScoutStatus")
            rospy.Subscriber(self.args.status_topic, msg_type, self._on_status, queue_size=5)
            self._subscribed = True
        except Exception as exc:  # noqa: BLE001 - 反馈是可选功能
            rospy.logwarn("读不到 %s（%s）：只发指令，不做反馈校验。"
                          "如需反馈请 source ~/catkin_ws/devel/setup.bash", self.args.status_topic, exc)

    def _on_status(self, msg: object) -> None:
        self.fb_linear = getattr(msg, "linear_velocity", None)
        self.fb_angular = getattr(msg, "angular_velocity", None)
        self.fb_control_mode = getattr(msg, "control_mode", None)
        self.fb_base_state = getattr(msg, "base_state", None)
        self.fb_fault = getattr(msg, "fault_code", None)
        self.fb_battery = getattr(msg, "battery_voltage", None)

    # ---------- 速度设置 ----------
    def set_motion(self, linear: float, angular: float, hold: float) -> None:
        self.target_linear = max(-self.args.max_linear, min(self.args.max_linear, linear))
        self.target_angular = max(-self.args.max_angular, min(self.args.max_angular, angular))
        self.hold_remaining = hold

    def stop(self) -> None:
        self.target_linear = 0.0
        self.target_angular = 0.0
        self.hold_remaining = 0.0

    # ---------- 主循环 ----------
    def spin_for(self, seconds: float) -> None:
        """按固定时长跑主循环：限幅 → 发布 → 打印。"""
        rate = rospy.Rate(self.args.rate)
        dt = 1.0 / self.args.rate
        end = time.time() + seconds
        last_print = 0.0
        while not rospy.is_shutdown() and time.time() < end:
            self.sent_linear = self._slew(
                self.sent_linear, self.target_linear, self.args.slew_linear * dt)
            self.sent_angular = self._slew(
                self.sent_angular, self.target_angular, self.args.slew_angular * dt)
            self.publish(self.sent_linear, self.sent_angular)
            now = time.time()
            if now - last_print >= self.args.print_every:
                last_print = now
                self.print_status()
            rate.sleep()

    def publish(self, linear: float, angular: float) -> None:
        msg = Twist()
        msg.linear.x = linear
        msg.linear.y = 0.0
        msg.linear.z = 0.0
        msg.angular.x = 0.0
        msg.angular.y = 0.0
        msg.angular.z = angular
        self.pub.publish(msg)

    @staticmethod
    def _slew(current: float, target: float, max_delta: float) -> float:
        """把 current 朝 target 靠拢，单步变化不超过 max_delta。"""
        delta = target - current
        if abs(delta) <= max_delta:
            return target
        return current + max_delta * (1.0 if delta > 0 else -1.0)

    def print_status(self) -> None:
        parts = [
            "指令 lin={:+.3f} ang={:+.3f}".format(self.sent_linear, self.sent_angular),
        ]
        if self._subscribed and self.fb_linear is not None:
            parts.append("反馈 lin={:+.3f}".format(self.fb_linear))
            parts.append("mode={}".format(self.fb_control_mode))
            parts.append("state={}".format(self.fb_base_state))
            parts.append("fault={}".format(self.fb_fault))
            if self.fb_battery is not None:
                parts.append("batt={:.1f}V".format(self.fb_battery))
        elif self._subscribed:
            parts.append("反馈: 还没收到 /scout_status")
        else:
            parts.append("反馈: 未订阅")
        if self.hold_remaining > 0:
            parts.append("hold {:.1f}s".format(self.hold_remaining))
        print("  " + "  ".join(parts), flush=True)

    def shutdown(self) -> None:
        """退出前连续发零速度，别把车丢在运动状态。"""
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        print("\n  退出中：连发 10 帧零速度…", flush=True)
        for _ in range(10):
            try:
                self.publish(0.0, 0.0)
            except Exception:  # noqa: BLE001 - 退出路径上尽力而为
                break
            time.sleep(0.1)
        print("  已归零。", flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="用 /cmd_vel 驱动 Scout 2.0（持续发布 + 限幅 + 自动归零）")
    p.add_argument("--topic", default="/cmd_vel", help="速度指令话题（默认 /cmd_vel）")
    p.add_argument("--status-topic", default="/scout_status", help="底盘反馈话题")
    p.add_argument("--rate", type=float, default=10.0, help="发布频率 Hz（默认 10）")
    p.add_argument("--hold", type=float, default=3.0, help="每条移动指令持续秒数（默认 3）")
    p.add_argument("--max-linear", type=float, default=0.20, help="前进速度硬上限 m/s（默认 0.20）")
    p.add_argument("--max-angular", type=float, default=0.60, help="转向速度硬上限 rad/s（默认 0.60）")
    p.add_argument("--slew-linear", type=float, default=0.30, help="线性加速度上限 m/s²（默认 0.30）")
    p.add_argument("--slew-angular", type=float, default=1.20, help="角加速度上限 rad/s²（默认 1.20）")
    p.add_argument("--print-every", type=float, default=1.0, help="状态打印间隔秒")
    # 脚本化模式
    p.add_argument("--linear", type=float, default=None, help="直接设定前进速度并跑 --duration 秒")
    p.add_argument("--angular", type=float, default=0.0, help="配合 --linear 的转向速度")
    p.add_argument("--duration", type=float, default=None, help="脚本化模式运行秒数")
    p.add_argument("--zero", action="store_true", help="只发零速度（测急停通道）")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    rospy.init_node("ugv_drive", anonymous=True, disable_signals=False)

    ctrl = DriveController(args)
    ctrl.subscribe_status()
    rospy.on_shutdown(ctrl.shutdown)

    print("=" * 68)
    print(" ugv_drive  ——  持续向 {} 发布，{} Hz".format(args.topic, args.rate))
    print(" 硬上限: 线速度 {:.2f} m/s, 角速度 {:.2f} rad/s".format(
        args.max_linear, args.max_angular))
    print(" ⚠️ 请确认车已架空或垫起轮子")
    print("=" * 68)

    # 给 publisher 一点时间建立连接，否则前几帧会丢
    time.sleep(args.hold if args.duration is None else 0.5)

    try:
        # ---------- 脚本化：只发零 ----------
        if args.zero:
            dur = args.duration or 3.0
            print(" 发送零速度 {:.1f} 秒（测急停通道）".format(dur))
            ctrl.stop()
            ctrl.spin_for(dur)
            return 0

        # ---------- 脚本化：固定速度跑一段时间 ----------
        if args.linear is not None:
            dur = args.duration or 3.0
            print(" 发送 lin={:+.3f} ang={:+.3f} 持续 {:.1f} 秒".format(
                args.linear, args.angular, dur))
            ctrl.set_motion(args.linear, args.angular, dur)
            ctrl.spin_for(dur)
            ctrl.stop()
            ctrl.shutdown()
            print(" 完成。")
            return 0

        # ---------- 交互式 ----------
        speed = 0.05
        print(" 交互模式：速度 {:+.3f} m/s，每次指令持续 {:.1f} 秒".format(speed, args.hold))
        print(" w 前进 / s 后退 / a 左转 / d 右转 / x 停 / status / q 退出")
        print(" 直接输入数字可改速度，例如 0.1")
        while not rospy.is_shutdown():
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                continue
            if line == "q":
                break
            if line == "status":
                ctrl.print_status()
            elif line == "x":
                ctrl.stop()
                ctrl.set_motion(0.0, 0.0, 1.0)
                print(" 已发送停止（保持 1 秒零速度）")
            elif line == "w":
                ctrl.set_motion(speed, 0.0, args.hold)
            elif line == "s":
                ctrl.set_motion(-speed, 0.0, args.hold)
            elif line == "a":
                ctrl.set_motion(0.0, +args.max_angular * 0.5, args.hold)
            elif line == "d":
                ctrl.set_motion(0.0, -args.max_angular * 0.5, args.hold)
            else:
                try:
                    speed = max(0.01, min(args.max_linear, float(line)))
                    print(" 速度已设为 {:+.3f} m/s".format(speed))
                except ValueError:
                    print(" 看不懂的命令：{!r}".format(line))
        return 0
    finally:
        ctrl.stop()
        ctrl.shutdown()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except rospy.ROSInterruptException:
        pass
