# Runtime Linux 离线部署依赖 v1

本文件与 `runtime_linux_x86_64_py310.requirements.txt` 由 Runtime 工作线维护。
算法线维护模型/推理引擎，Simulation 维护 PX4/Gazebo，集成线消费固定版本进行验收。
本轮仅准备部署依赖和说明，不修改执行 API、Policy、车辆映射、ROS 或厂家系统。

## 目标与边界

- 已核对目标：WSL 分发版 `Ubuntu`，Ubuntu 22.04、Linux x86_64、glibc 2.35、CPython 3.10.12。
- Runtime 源码固定为 `332b6c4`；四线组合验收版本为 `064cdf1`（Draft #93）。
- 这是运行与测试依赖包，不包含 Python 解释器、模型、CUDA、PX4、Gazebo、前端构建产物。
- 不适用于 Jetson aarch64/Python 3.8，也不是 Windows wheel 包。其他台式机先核对系统、架构和 Python ABI。
- 保留系统 Python；新建独立 venv，不使用 sudo pip，不替换 `/usr/bin/python3`。
- 当前平台 HTTP 只允许 loopback；本包不实现跨台式机网络部署，也不增加容器/资源隔离。

## 离线 wheel 清单

20 个完整 wheel 共 17,227,620 字节。每个文件的版本和 SHA-256 均锁定在相邻 requirements 文件。
包含 pymavlink 2.4.49、fastcrc 0.3.6、lxml 6.1.1（与本机原有 WSL 运行包版本对齐），
pytest 9.0.2、jsonschema 4.23.0，以及安装工具和传递依赖。
Python 3.10 需要的 `exceptiongroup`、`tomli` 显式列出，避免在 Windows 上准备包时漏掉条件依赖。
`colorama` 为跨平台解析时带入的小型附加包，不代表 Linux 需要 Windows 控制组件。

下载解析最初使用本机配置的镜像，随后显式使用官方索引复核，且独立对全部 20 个文件逐一检查：

1. 读取 wheel 顶层 `.dist-info/METADATA`，取得准确包名和版本。
2. 查询官方 `https://pypi.org/pypi/<name>/<version>/json` 中同名 wheel 的发布记录。
3. 将本地 SHA-256 和字节数与官方发布记录比较；20/20 相同。
4. 保留完整 wheel，包含其 `.dist-info/licenses/` 等许可文件，不剥离第三方许可。

核验哈希不等于安全认证或设备兼容性认证。pymavlink 的 wheel 标注 LGPLv3；
pip/setuptools 等还含 vendored 组件许可，搬运和再分发时保留原文件并另行检查许可义务。

## 在有网准备机复现下载

在固定源码 checkout 根目录执行。下面参数针对 Ubuntu 22.04 的 CPython 3.10，而非准备机的 Python：

```text
python -m pip download --index-url https://pypi.org/simple --only-binary=:all: --require-hashes --platform manylinux_2_35_x86_64 --platform manylinux_2_34_x86_64 --platform manylinux_2_31_x86_64 --platform manylinux_2_28_x86_64 --platform manylinux_2_26_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 --implementation cp --python-version 310 --abi cp310 --dest .runtime/deployment-linux-x86_64-py310/wheelhouse -r docs/runtime_linux_x86_64_py310.requirements.txt
```

禁止以 `requirements_full_from_env.txt` 代替：它可能带入开发机无关依赖。
本包锁定单一 wheel 哈希，不应当无审核更新版本或追加其它架构的 wheel。

## 无网安装与检查

目标机须已具备 CPython 3.10 和可用的 `venv`/`ensurepip`；否则先准备对应系统的解释器离线包。
`venv` 不可跨机器复制。源码和 wheelhouse 可搬运，但在目标机重新创建环境。
以下为 Linux shell，在源码 checkout 根目录执行，环境目录自行选择未被其它服务使用的路径：

```bash
python3.10 -m venv /path/to/new-runtime-env
/path/to/new-runtime-env/bin/python -m pip install --no-index --no-cache-dir --disable-pip-version-check --only-binary=:all: --find-links .runtime/deployment-linux-x86_64-py310/wheelhouse --require-hashes -r docs/runtime_linux_x86_64_py310.requirements.txt
/path/to/new-runtime-env/bin/python -m pip check
/path/to/new-runtime-env/bin/python -I -c 'import pymavlink, fastcrc, lxml.etree, pytest, jsonschema; print("dependency_import_ok")'
```

wheelhouse 与锁文件都必须可读；缺包/哈希错误应失败，不使用联网回退。
在 WSL 下优先把 venv 放在 Linux 原生持久文件系统；在 `/mnt/d` 安装大量小文件较慢，
而 `/tmp` 在 WSL 重启后可能消失。本轮曾中断挂载盘上的慢速 venv 创建，其部分文件保留在忽略目录，
不作为可用环境，不删除或覆盖它。

本机本轮实际环境路径：

```text
/home/zyq/.local/share/uav-runtime-envs/linux-x86_64-py310-20261024
```

该路径仅是当前机器的运维信息，不是平台 API，也不是其它机器必须使用的路径。

## 不连接 PX4 的 Runtime 测试

在 Runtime checkout 根目录执行；下列平台用例使用 fake adapter 和临时 loopback 端口，不连接 14540–14542：

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /path/to/new-runtime-env/bin/python -m pytest -q -rs -p no:cacheprovider tests/unit/test_platform_autonomy.py --basetemp .runtime/deployment-linux-x86_64-py310/pytest-platform
```

测试通过仅证明 Linux 依赖和 fake 执行机制，不代表 PX4/Gazebo 飞行通过。

### 2026-10-24 实际验证结果

- 20 个 wheel 的官方 SHA-256/字节数核对通过；独立 venv 以 `--no-index --require-hashes` 安装成功。
- `python -m pip check`：`No broken requirements found`。
- `python -I` 导入 pymavlink/fastcrc/lxml.etree/pytest/jsonschema 成功，且 `sys.prefix != sys.base_prefix`。
- Runtime checkout 全量：**956 passed、12 skipped、0 failed，127.20 s**。
- 跳过项：5 个三机真实 PX4 用例、1 个显式真实巡检用例、6 个需要 Node 的转换器接口用例。
  未为通过 Python 回归额外安装 Node，也未将这些跳过项算作通过。
- `compileall` 与 `git diff --check` 通过；字节码放在专用环境缓存，测试临时文件放专用 Linux 目录。

本轮完整 pytest 命令（在 Runtime checkout 根目录）：

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/zyq/.local/share/uav-runtime-envs/linux-x86_64-py310-20261024/bin/python -m pytest -q -rs -p no:cacheprovider --basetemp /home/zyq/.local/share/uav-runtime-envs/linux-x86_64-py310-20261024/pytest-runtime-20261024
```

### 本地搬运包

归档放在本 Runtime worktree 的忽略目录：
`.runtime/runtime-linux-x86_64-py310-20261024.tar.gz`。
只包含 `.runtime/deployment-linux-x86_64-py310/wheelhouse/`、本说明与 SHA 锁文件，
不包含 venv、测试临时文件、日志、凭据、源码、模型或其它工作树内容。
解压到确认过的同版本源码 checkout 根目录后，wheelhouse 路径与上述命令一致。
源码应使用集成固定候选 `064cdf1` 或经核对包含该实现的后续版本，不应误用旧离线包源码。
归档整体哈希随交付报告/PR 提供；安装时仍对每个 wheel 强制验证锁文件中的哈希。

## 模型与实体验证仍需独立完成

算法线提供匹配 Linux ABI 的推理引擎、既有 GGUF、候选服务源码、SHA-256 和许可证。
CPU 推理引擎可作为不依赖 CUDA 的基线；能打印 `--version` 不等于能加载模型，也不等于满足 2 秒截止时间。
先做模型加载、冷/热候选请求、非法输出及超时测试，再进入单机 SITL 验收。
不绕过已有 RAM/VRAM 保护，不把 Windows 的模型延迟外推到 Linux，不降低 Runtime 截止时间来凑通过。

当前模型测试只允许 fake 遥测，不向 PX4 发指令；地面链路、算法和机载 Runtime 的服务归属须先检查，
不得占用或关闭别人的进程。UAV-02 受控起飞/保持/降落另按集成验收窗口进行。
实车 ROS 双向桥、安全停车和跨机器台式机部署均未包含在本次依赖准备中。

算法线已补交文档提交 `527ef06`（Draft #96）；算法源码仍为 `17017cd`。
其本地 `uav02-candidate-b10964-cpu-ubuntu22.04.tar.gz` 包含官方 Linux CPU b10964 引擎、
复用的 Qwen3.5-0.8B Q4、候选服务及许可，整体 SHA-256 为
`4c5c25e37146c39599746effc3e29334386a43970bdad83c24d73f96eb7168ef`。
ELF/动态库/version 和候选服务缺模型时的拒绝路径已验证；模型尚未加载，因为可用主机内存
未达到既有 3 GiB 保护门槛。Linux GPU 引擎、CPU 模型实际推理和 2 秒延迟达标仍未验证。

## 2026-10-29 后续实测（不改变原包）

用户清理主机内存后已实际加载同一 Linux CPU 模型。原算法 ctx512 的简短候选请求可通过，
但完整 Runtime 请求超过上下文；ctx2048 解决容量后，完整请求仍频繁超过 2 秒。
因此“尚未加载”是 10 月 24 日的历史状态，不是当前状态；也不能据此把模型集成标为通过。
逐轮日志、回退与任务终态、复现脚本及后续算法修正结果见
`runtime_local_model_verification_20261029.md`。
原 2026-10-24 wheel/model 包和系统 Python 均未覆盖，真实 PX4/Gazebo/控制台联合验收仍未完成。
