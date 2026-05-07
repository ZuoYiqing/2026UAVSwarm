# 2026UAVSwarm 目标机离线迁移操作说明（极简保险版）

## 适用前提
- 目标机完全无网络
- 目标机无 GPU
- 本地机与目标机可通过网线传文件
- 当前项目运行时代码仅依赖 Python 标准库
- 若需要在目标机运行测试，仅额外需要 `pytest`

---

## 一、建议迁移的内容

### 必带
1. 项目代码目录 `2026UAVSwarm/`

### 建议带（保险版）
2. 一个最小离线 wheel 包目录 `wheelhouse_basic/`
   - `pytest`
   - `pip`
   - `setuptools`
   - `wheel`

### 可选
3. 一份说明文件（本文件）

---

## 二、本地机准备步骤（联网电脑）

### 1. 在本地机准备项目代码
确认当前代码已经提交或至少拷贝完整。

### 2. 准备最小离线包目录
在本地机当前 Python 环境中执行：

```powershell
mkdir wheelhouse_basic
python -m pip download pytest pip setuptools wheel -d wheelhouse_basic
```

执行后会得到一个 `wheelhouse_basic/` 文件夹。

### 3. 将以下内容传到目标机
- `2026UAVSwarm/`
- `wheelhouse_basic/`

---

## 三、目标机准备步骤（无网电脑）

### 1. 创建 Python 3.11 环境（推荐）
优先尝试和本地一致的 Python 3.11：

```powershell
conda create -n uavruntime311 python=3.11 -y
conda activate uavruntime311
```

如果 3.11 不能建，再退而求其次考虑 3.10，但优先 3.11。

### 2. 安装最小测试依赖（如果需要跑 pytest）
如果目标机要跑测试：

```powershell
python -m pip install --no-index --find-links=wheelhouse_basic pytest pip setuptools wheel
```

如果目标机只运行项目、不跑测试，这一步可以跳过。

---

## 四、如何运行项目

### 1. 进入项目目录
```powershell
cd D:\2026UAVSwarm
```

### 2. 运行 CLI（示例）
```powershell
python -m uav_runtime.console.cli --help
```

如果你的仓库当前入口不是这个路径，就按实际 README 中的方式运行。

---

## 五、如何运行测试

### 1. 单独跑核心测试
```powershell
python -m pytest tests/unit/test_protocol_schema.py -q
python -m pytest tests/unit/test_policy_contract_shapes.py -q
python -m pytest tests/integration/test_minimal_runtime_flow.py -q
```

### 2. 全量运行
```powershell
python -m pytest -q
```

---

## 六、当前项目依赖判断

### 运行时
当前项目运行时代码只依赖 Python 标准库，不依赖第三方 wheel。

### 测试时
当前只需要：
- `pytest`

因此，不需要准备大而全的离线 wheelhouse，也不需要迁移 GPU/CUDA 相关包。

---

## 七、推荐的实际迁移策略

### 方案 A：运行版
适用于只做演示、不跑测试的目标机。

带过去：
- 项目代码

不需要额外 wheel。

### 方案 B：开发验证版
适用于目标机需要离线跑测试。

带过去：
- 项目代码
- `wheelhouse_basic/`

---

## 八、常见问题

### 1. 目标机什么包都没有，会不会跑不起来？
只要目标机有合适的 Python 环境（推荐 3.11），当前项目运行时代码就能跑，因为它只用标准库。

### 2. 还需要准备 CPU 版 torch / numpy / pandas 吗？
当前不需要。因为项目现在没有实际 import 这些第三方库。

### 3. 要不要带 requirements_full_from_env.txt？
不建议直接使用那份全量环境快照。它会带进很多无关包和历史残留。当前项目用不到。

---

## 九、推荐保留的两个最小文件

### requirements_test_min.txt
```text
pytest>=8.0
```

### offline_transfer_note.txt
可直接使用本说明文件。
