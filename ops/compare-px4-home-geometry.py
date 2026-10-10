#!/usr/bin/env python3
"""把三台的 PX4 HOME lat/lon 换算成相对间距，与 spawn 的三机间距对照。

为什么这样算：`HOME_POSITION.local_x/y/z` 在本环境里是 None（PX4 没填），
所以不能直接拿本地坐标比。但**三台之间的相对位移**可以由 lat/lon 算出 ——
而 spawn 的间距是已知的（UAV-01/02/03 = (0,0) / (0,+8) / (0,-8)），
所以只要相对间距吻合，就能确认 **PX4 home == 各自 spawn 点**。
"""
from __future__ import annotations

import math

# 实测（check-px4-home-vs-pad.py 的输出）
HOMES = {
    "UAV-01": (47.3979707, 8.5461637),
    "UAV-02": (47.3979709, 8.5462699),
    "UAV-03": (47.3979707, 8.5460576),
}
# manifest 的 spawn（scene_ned，与 EKF 原点一致）
SPAWNS = {"UAV-01": (0.0, 0.0), "UAV-02": (0.0, 8.0), "UAV-03": (0.0, -8.0)}

# WGS84 在纬度 47.4° 处的每度米数
LAT_M = 111_320.0
LON_M = 111_320.0 * math.cos(math.radians(47.39797))


def ned(origin: str, target: str) -> tuple[float, float]:
    lat0, lon0 = HOMES[origin]
    lat1, lon1 = HOMES[target]
    north = (lat1 - lat0) * LAT_M
    east = (lon1 - lon0) * LON_M
    return north, east


print("=" * 74)
print("实测 PX4 HOME 的相对间距  vs  manifest spawn 的相对间距")
print("=" * 74)
print(f"  （换算用 WGS84：北向 {LAT_M:.0f} m/deg，东向 {LON_M:.0f} m/deg @ lat 47.398）")
print()

pairs = [("UAV-01", "UAV-02"), ("UAV-01", "UAV-03"), ("UAV-02", "UAV-03")]
worst = 0.0
for a, b in pairs:
    hn, he = ned(a, b)
    sn = SPAWNS[b][0] - SPAWNS[a][0]
    se = SPAWNS[b][1] - SPAWNS[a][1]
    dn, de = hn - sn, he - se
    err = math.hypot(dn, de)
    worst = max(worst, err)
    print(f"  {a} → {b}")
    print(f"    实测 HOME 间距 : 北 {hn:+.2f} m  东 {he:+.2f} m")
    print(f"    spawn 间距      : 北 {sn:+.2f} m  东 {se:+.2f} m")
    print(f"    偏差            : {err:.3f} m   {'✅' if err < 0.5 else '⚠️'}")

print()
print("=" * 74)
print("结论")
print("=" * 74)
if worst < 0.5:
    print(f"  ✅ **PX4 HOME 就是各自的 spawn 点**（最大偏差 {worst:.3f} m）。")
    print()
    print("  → 所以三台的 home 是**分别设置**的，落在各自的起飞位置上，")
    print("    与 manifest 的 spawn_ned / 三个 pad 中心一致。")
else:
    print(f"  ⚠️ **偏差最大 {worst:.3f} m —— HOME 与 spawn 不是同一点。**")

print()
print("  ⚠️ 但这里要说清**这个结论证明了什么、没证明什么**：")
print()
print("     ✅ 证明了：PX4 的 home 与站点几何（spawn / pad 中心）**在几何上吻合**。")
print("        三方要求的'核验 HOME_POSITION 与目标 pad 一致'在**当前配置下会通过**。")
print()
print("     ❌ **没有证明**：这条核验**能挡住屋顶着陆那类事故**。")
print("        回到那次事故：飞机在场景 (N≈15.6, E≈-0.7) 落在屋顶。")
print("        而它的 home 是 (0,0) —— **home 与 pad 是一致的**。")
print("        问题不在'飞机去了别的地方'，而在：")
print("          · `RETURN_HOME` 在距离**刚开始缩短**时就报了完成（飞机根本没到家）")
print("          · 随后那发 `LAND` 的语义是 'Landing at current position'")
print("          · 于是它降在**当时所在位置的正下方**（屋顶），而不是 home")
print()
print("     所以核验 HOME==pad 是**必要但不充分**：")
print("       · 它防止'RTL 回到一个非站点的地方自行降落'")
print("       · 它**不**防止'在途中下发 LAND'")
print("     三方提出的'三个时点分开'正好覆盖了后者 —— 两者需要一起做。")
