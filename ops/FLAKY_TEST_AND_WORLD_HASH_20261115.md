# 一个 flaky 测试，和它背后的两个真问题（2026-11-15）

**发现方式**：r3 预演（r2 + #102 + #103）跑全量测试时挂了一个。

---

## 结论先行

**不是 #102 / #103 引入的回归。** 我用 r2 定版基线也复现了：

```
r2 定版（d50cd8f）：
  第 1 次  FAILED
  第 2 次  passed
  第 3 次  passed

r3 预演（6998f4f）：
  第 1 次  passed
  第 2 次  passed
  第 3 次  FAILED
```

**两边都间歇性失败 → 测试本身不稳定，与 r3 无关。**

失败的测试：

```
tests/unit/test_three_uav_health.py:228
::test_integrated_health_uses_runtime_telemetry_without_binding_mavlink
assert 'not_ready' == 'ready'
```

---

## 机制（读代码得到的，不是猜）

### 三个事实

**① 生产阈值很紧（`simulation/px4_gazebo/health.py:23-24`）**

```python
HEARTBEAT_MAX_AGE_S = 2.5
TELEMETRY_MAX_AGE_S = 1.5      # ← 遥测超过 1.5 秒就判 stale
```

**② 测试 fixture 在"构建时"打时间戳（`test_three_uav_health.py:110-114`）**

```python
now = harness.utc_now()
...
"source_timestamp": now, "valid_for_ms": 5000,
```

**③ `_collect` 里有个冷缓存会慢的 I/O（`ground_reference.py:74-75`）**

```python
raw_digest = hashlib.sha256(world_bytes).hexdigest()
digest = hashlib.sha256(harness.canonical_world_bytes(world_bytes)).hexdigest()
```

### 串起来

```
fixture 打时间戳            ← t0
  ↓
_collect → collect_health
  ↓
读 world .sdf + 算两次 sha256 ← 冷缓存时可能 > 1.5 秒
  ↓
用 now() 算 telemetry_age      ← t1，如果 t1-t0 > 1.5 → status = not_ready
  ↓
assert status == "ready"       ← 挂
```

**第一次跑最慢（import + 冷缓存），所以"第 1 次失败、后面通过"这个模式完全对得上。**

---

## 问题一：测试用了墙钟，且窗口只有 1.5 秒

**这是测试设计问题。** 现代测试不该依赖墙钟 —— 一旦 host 变慢、磁盘变慢、
或者 CI 上并发跑，就会随机挂。

### 建议修法（三选一，优先级从高到低）

1. **注入可控时钟**（最好）
   `collect_health` 已经有 `clock_probe` 参数，但没有可注入的"当前时间"。
   加一个 `now_provider` 参数，测试传固定时间，完全不依赖墙钟。

2. **fixture 的时间戳在 `collect_health` 内部打**
   把 `_runtime_telemetry(manifest)` 改成传一个 **工厂函数**，
   在 `collect_health` 真正开始评估时才生成时间戳。

3. **最省事但最差**：把测试里的 `valid_for_ms` 调大
   —— 治标，掩盖问题。

---

## 问题二（更重要）：world_sha256 **每次健康检查都重算**

`ground_reference.py` 每次 `collect_health` 都：
1. 读整个 world `.sdf` 文件
2. 算 `raw_digest`
3. 做一次 canonical 变换
4. 再算 `digest`

**而 world 文件在一次仿真期间是静态的** —— 改都不会改。

### 为什么这值得修

| 影响 | 说明 |
|---|---|
| **性能** | 每次健康检查多两次 sha256 + 一次文件读。前端轮询健康/遥测时会被放大 |
| **现场风险** | **`TELEMETRY_MAX_AGE_S = 1.5` 是生产阈值**。weier 上如果恰好撞上冷缓存或磁盘慢，集成健康会翻成 `not_ready` —— 表现为"3/3 在线"偶尔变"离线" |
| **演示观感** | 观众看到"在线节点"忽然从 3 掉到 2 又跳回 3，会以为是系统不稳 |

### 建议修法

**加一层 world hash 缓存**（按 world 路径 + mtime 做 key）：

```python
# 伪代码
@lru_cache(maxsize=8)
def _world_digest(path: str, mtime_ns: int) -> str:
    ...  # 只在文件真的变了才重算
```

**这一改同时修好 flaky 测试和现场风险。**

---

## 对当前阶段的影响

| 问题 | 阻塞什么 |
|---|---|
| 测试 flaky | ❌ 不阻塞 r2/#102/#103 的代码正确性，但**会让每次跑测试的结果不可信** |
| world hash 无缓存 | ⚠️ **可能影响 weier 现场验收**（第三阶段） |

---

## 建议动作

| # | 做什么 | 谁 | 优先级 |
|---|---|---|---|
| 1 | 给 `collect_health` 加 `now_provider`（或把 fixture 时间戳改成工厂） | 仿真 | P1 |
| 2 | 给 world hash 加缓存（按路径+mtime） | 仿真 | **P0**（现场风险） |
| 3 | 顺手把 `TELEMETRY_MAX_AGE_S = 1.5` 是否合理复核一遍 | 仿真 + Runtime | P1 |

> **第 3 条值得单独说**：1.5 秒对 50 Hz 的遥测流（每 20 ms 一帧）来说很宽，
> 但如果 Runtime 侧是**按需拉取**而不是持续接收，就可能因为轮询间隔撞线。
> 建议确认一下 `link_quality` 的采样方式，避免现场"链路质量"忽高忽低。

---

## 一个提醒：这个 flake 让之前所有"全绿"都要打折扣

r2 报的 **1083 passed** 和 r3 预演的 **1090 passed** 都可能是**这一次没抽到那个 flake**。

**不是他们造假**，而是这种 flaky 测试的特性 —— **跑一次绿不代表稳定**。

建议以后验收时：
```bash
# 关键的集成测试连跑 3 次，全绿才算过
for i in 1 2 3; do PYTHONPATH=src python3 -m pytest <关键测试> -q; done
```

**这一条比多写十个测试更有用。**
