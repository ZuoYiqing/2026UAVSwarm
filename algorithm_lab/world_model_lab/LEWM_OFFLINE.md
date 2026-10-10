# LeWorldModel 离线加载验证

本阶段使用作者发布的 `quentinll/lewm-pusht` 视觉权重和官方架构，目标是验证
本地严格加载、图像编码、动作条件预测与断网启动。是 PushT 检查点的 I/O
冒烟实验；完整任务性能需真实 PushT 轨迹和评价环境，迁移到无人机还需数据
与动作定义。这些阶段的完成状态分别记录，不以成功加载代替任务完成。

## 固定来源

- [官方源码](https://github.com/lucas-maes/le-wm)，revision
  `8edfeb336732b5f3ce7b8b210d0ba370a09e2cac`，MIT；迁移时携带 `LICENSE`。
- [官方权重](https://huggingface.co/quentinll/lewm-pusht)，revision
  `22b330c28c27ead4bfd1888615af1340e3fe9052`，模型卡标注 MIT。
- `weights.pt` 为 state_dict，72,290,721 字节；SHA-256
  `48938400ae3464c9680731287f583a9cb516f55a8ec64ea13a91be47fb15b607`。
- 配置 SHA-256 `2564086e961e7b5c7c04dffc451091115b389a590645ff19653c64fd0bc16e09`。
- ViT tiny 构造参数依据 [stable-pretraining vit_hf](https://github.com/galilai-group/stable-pretraining/blob/ab836bf699a2be712dfcf980a5eb70d36391e876/stable_pretraining/backbone/utils.py)：
  192 hidden、12 layers、3 heads、768 intermediate、224 RGB、14 patch，
  无 pooling/mask token。直接构建 Transformers ViTConfig/ViTModel。

输入三帧 `1×3×3×224×224` RGB，按 ImageNet mean/std 归一化，读取 CLS token，
观察与预测特征均为 `1×3×192`。逐项严格加载全部权重；不动态执行 config 的
`_target_`，不忽略缺失键、不改名迁就检查点，不加载 serialized model object。
需要 PyTorch >=2.6，以 `weights_only=True`、CPU mmap 读取。

## 独立环境与依赖

所有资产和临时文件都在原算法 worktree 的
`algorithm_lab/world_model_lab/artifacts/lewm/`：`model/`、`vendor/`、`wheelhouse/`、
`.venv/`、`tmp/`、`runs/`。本模块 `.gitignore` 已忽略这些文件。
根依赖和已有环境保持原样。Windows CPU 环境使用 Python 3.11；核心依赖为：

| 依赖 | 用途 | 许可 |
| --- | --- | --- |
| PyTorch 2.6.0 CPU | 权重及网络计算 | BSD-3-Clause |
| Transformers 4.40.2 | 与权重键匹配的 ViT 实现 | Apache-2.0 |
| NumPy 1.26.4 | 图像数组 | BSD-3-Clause |
| Pillow 10.2.0 | 本地 RGB 解码 | HPND |
| einops 0.8.0 | 官方模型中的张量变换 | MIT |

不安装 stable-worldmodel 的仿真/训练 extras、视频生成器或训练日志服务。
依赖中的 Hub 库是 Transformers 的间接依赖；推理不用远程加载入口。
wheelhouse/完整版本锁与哈希清单用于离线安装，大小以生成的 manifest 为准。
Windows CPython 3.11 CPU wheels **不能用于 Linux ARM64/Jetson**。
模型和源码可迁移；板端 PyTorch/CUDA 需按实际 JetPack/Python 准备。

## 输入与输出

`scripts/lewm_offline_probe.py` 自动创建明确标记的三张人工 RGB 输入，或读取
同契约的 `--request`。图像原生 224×224、RGB；不自动 resize 或色彩转换。
请求包含 `fixture_kind=synthetic_rgb_io_smoke`、三个相对图像路径、三组
`normalized_action_blocks`，每组 10 个有限值。10 维来自 PushT 的 5 步
二维动作拼接，**不是三维加速度、航点或 MAVLink 参数**。

样例动作全部为归一化后的零，另做加 0.25 的特征敏感性检查。这些人工输入
没有真实未来画面标签；不报告预测准确率、目标置信度或任务成功率。
真正 PushT 动作归一化需要训练集均值和方差，当前迁移包未包含该数据集统计。

每个 `runs/<id>/` 保存原图和完整请求、资产/输入哈希、完整 192 维观察与预测
特征、输出哈希、严格加载键数、参数数、版本、重复推理差异、首轮/热推理
耗时和进程 RSS/峰值。耗时涵盖三帧编码和一次三上下文预测，不含图像 I/O。
`model_loaded` 与 `inference_completed` 明确区分准备、加载、推理。

```text
# 从 world_model_lab 目录运行，输出目录必须是新的。
artifacts/lewm/.venv/Scripts/python.exe scripts/lewm_offline_probe.py --assets artifacts/lewm --output artifacts/lewm/runs/cpu_smoke_01 --device cpu
```

运行前可用内存需 >=3 GiB；导入后和热推理循环中保留 >=1.5 GiB。
资源不够时保存 blocked 报告并退出 2，不加载模型，不自行关闭用户程序。
`--prepare-only` 只做源码/权重哈希与样例准备，不属于加载成功。

程序将 HF/Torch 缓存设为新建空目录，启用离线环境变量；安装 Python socket
审计钩子并实测 socket 创建被拒绝后，才导入 ML 依赖与执行推理。这个测试
验证 Python API 层的离线运行；实际部署仍须目标系统断网冷启动验证。

## 离线安装和打包

下载完成后，本机安装只使用本地 wheelhouse：

```text
python -m pip install --no-index --find-links artifacts/lewm/wheelhouse -r requirements-lewm-load.txt
python -m pip check
```

`scripts/package_lewm_probe.py` 复制最小推理源码、官方源码/许可证、权重、
配置、完整输入样例与文件 SHA-256；可选携带 Windows wheels 和精确版本锁。
不复制 venv、Git 目录、缓存、训练代码或仿真环境。包的 manifest 明确记录
有无完成模型推理，而非一律宣称可用。校验可用已有 `worldlab.cli verify`。

```text
# 使用刚准备的隔离 Python 打包；不是系统 Python。
artifacts/lewm/.venv/Scripts/python.exe scripts/package_lewm_probe.py --assets artifacts/lewm --output artifacts/lewm/bundles/windows_cpu_01 --windows-wheelhouse --report artifacts/lewm/runs/cpu_smoke_01/report.json
# 拷贝到另一台 Windows x64 / Python 3.11 电脑后，从包目录运行：
python -m venv .venv
.venv/Scripts/python.exe -m pip install --no-index --find-links wheelhouse -r requirements-windows.lock.txt
.venv/Scripts/python.exe -m worldlab.cli verify --bundle .
.venv/Scripts/python.exe scripts/lewm_offline_probe.py --assets assets --request examples/request.json --output runs/new_run --device cpu
```

这份 Windows 安装锁不能给 Orin 使用。板端先准备匹配 JetPack 的 ARM64
依赖，模型/源码部分可共用；不得尝试安装 Windows wheelhouse。

## 板端待验收

目标 AGX Orin 32GB；需要真实 JetPack/Ubuntu/Python/CUDA/PyTorch 版本与板卡
访问方式。目标上断网安装匹配的 ARM64 包，验证哈希，再用 `--device cuda`
执行同一份输入，多次冷启动，记录实际输出/数值差异、首轮与 p50/p95 时延、
RSS及 CUDA 内存。CUDA 时序会同步，不将异步 kernel 入队时间当推理时间。

功耗另用板端 `tegrastats` 采集原始功率轨记录；同时记录功耗模式、温度、
冷却条件、CPU/GPU 时钟和空闲基线。保留输入采样时间并与推理时段对齐。
进程 RSS、板卡共享内存和整板功耗各有不同含义，不可相互代替。
当前没有板卡访问权限，板端结果和功耗不能由本机或规格表推算。

CPU 首轮适合验证加载；4050 CUDA 与板端 CUDA 是后续各自的测量结果。
本模块只产出研究特征，尚无 Runtime 映射、控制请求或执行授权。
