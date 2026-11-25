# 任务规划页：本地 4B 只读预览

不配置模型时，普通 Runtime 启动方式不变。设置 `UAV_RUNTIME_LOCAL_MODEL_ENABLED=1`
即可在**普通 Runtime 进程**中启用模型预览；三机遥测仍按原配置启动。模型只参与
`POST /api/planner/plan-mission`，不参与飞行控制或授权。
复用已启动的 Windows 本地推理服务（默认别名 `qwen3.5-4b-q4-lab`），不下载、打包或启动模型。

## 启动方式

Windows Runtime 与模型在同一主机时，可使用现有 loopback 监听。在独立 Runtime worktree 根目录执行：

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
$env:UAV_RUNTIME_LOCAL_MODEL_ENABLED = '1'
$env:UAV_RUNTIME_LOCAL_MODEL_TIMEOUT_S = '18'
python -B -m uav_runtime.http.server
```

### WSL Runtime → Windows 4B

Windows 上的模型继续只监听 `127.0.0.1:18116`。通过同属方案 A 的小型中转，仅在
Windows 已存在的 WSL 虚拟网卡地址监听 18116。只接受当前 WSL 来源地址和 bearer token，
只转发 `GET /health`、`GET /v1/models` 和 `POST /v1/chat/completions` 到固定 loopback。
不绑定 `0.0.0.0`、物理网卡，不新增防火墙规则，也不重启现有模型。WSL NAT 地址变化后重新取值并重启中转。

在 Windows PowerShell（worktree 根目录；`Ubuntu` 可替换为实际仿真发行版）：

```powershell
$uavWslDistro = 'Ubuntu'
$uavWslGateway = (wsl.exe -d $uavWslDistro --exec ip -j -4 route show default | ConvertFrom-Json).gateway
$uavWslPeer = (wsl.exe -d $uavWslDistro --exec ip -j -4 route get $uavWslGateway | ConvertFrom-Json).prefsrc
$uavModelToken = Join-Path ([IO.Path]::GetTempPath()) ('uav-model-relay-' + [guid]::NewGuid() + '.token')
$uavRandom = [byte[]]::new(32)
$uavRng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $uavRng.GetBytes($uavRandom) } finally { $uavRng.Dispose() }
[IO.File]::WriteAllText($uavModelToken, [BitConverter]::ToString($uavRandom).Replace('-', ''),
    [Text.Encoding]::ASCII)
wsl.exe -d $uavWslDistro --exec wslpath -a $uavModelToken
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -B -m uav_runtime.http.wsl_model_relay --gateway $uavWslGateway --wsl-peer $uavWslPeer --token-file $uavModelToken --timeout-s 18
```

上面 `wslpath` 输出的是 token **文件路径**；令牌内容不打印、不进环境变量或命令行、不提交。
在 WSL 的 Runtime checkout、使用现有带 `pymavlink` 的 Python 环境：

```bash
uav_wsl_gateway="$(ip -4 route show default | awk 'NR==1 {print $3}')"
export UAV_RUNTIME_LOCAL_MODEL_URL="http://${uav_wsl_gateway}:18116/v1"
export UAV_RUNTIME_LOCAL_MODEL_TOKEN_FILE='<上面输出的 WSL 文件路径>'
export UAV_RUNTIME_LOCAL_MODEL_ENABLED=1
export UAV_RUNTIME_LOCAL_MODEL_TIMEOUT_S=18
export UAV_RUNTIME_TELEMETRY_ENABLED=true
PYTHONPATH=src python3 -B -m uav_runtime.http.server
```

默认 alias 可用 `UAV_RUNTIME_LOCAL_MODEL_ALIAS` 修改；模型预算可用
`UAV_RUNTIME_LOCAL_MODEL_TIMEOUT_S` 修改，Windows 中转的 `--timeout-s` 应同步配置。
非 loopback 模型地址只接受 WSL2 当前默认网关，并要求提供 token 文件。不使用浏览器来配置模型地址。
旧 `--read-only-model-preview` 可留作隔离诊断；三机遥测演示**不使用**该开关。

### 网页和预热

Runtime HTTP 仍只监听 `127.0.0.1:8765`。如果主控制台未运行，在另一个终端启动：

```powershell
python -B -m http.server 5178 --bind 127.0.0.1 --directory frontend/swarm-console
```

打开 `http://localhost:5178/` 的任务规划页。若页面保存过测试 API，确认连接地址为
`http://127.0.0.1:8765/api`。在“任务目标”输入“巡检西北区域。”，点击“预览任务”，
不手选固定模板。模型预览只接受本机控制台的来源，预览回包不授权执行。若 8765 已有
Runtime，由进程的操作者正常停掉旧实例，再使用普通模式启动；不抢占接收端口。

演示前，在 WSL 普通 Runtime 启动后先发一条**只读预热请求**，确认模型确实被采用：

```bash
curl --fail --silent --show-error --max-time 20 http://127.0.0.1:8765/api/planner/plan-mission \
  -H 'Content-Type: application/json' \
  --data-binary '{"objective":"巡检西北区域。","dry_run":true}'
```

检查 `intent_source: "local_model"` 和 `execution_authorized: false`。仅 `/health` 正常
不足以证明模型已经预热；如仍降级，保留原因并继续排查，不把预热结果记作正式演示台词。

## 页面和测试判据

| 路径 | 页面可见字段 |
| --- | --- |
| 真实模型输出通过校验 | `intent_source: "local_model"`，`fallback_reason: null` |
| 服务未就绪、超时或正在忙 | `intent_source: "rules"`，`fallback_reason: "model_unavailable"` |
| 回答无效、换目标、漏排除项或改顺序 | `intent_source: "rules"`，`fallback_reason: "model_low_confidence"`（拒收原因，不代表测出了一个置信度分数） |
| 目录目标有歧义、互斥、属于仅参照项或规则无法绑定 | 不叫模型去猜；保留原有澄清或拒绝回包，无降级标记 |

自动预览先用当前场景目录验证请求能明确绑定。模型只看到用户原话和编号目录，不看到规则答案；
模型选出的目标、顺序、仅定位与排除项须与已验证约束一致。通过后采用模型绑定，字面证据仍来自原话。
这是首演版的有限识别，不代表支持目录外对象或自由任务分解。模型预算默认 **18 秒**，
给目标页面 **20 秒**的规划请求留约 2 秒。主控制台尚无该请求的外部配置入口，当前仓库页面仍是
5 秒；需要前端负责人为 `planMission` 单独接入可配置的默认 `20000` ms，不改变其他 API 超时。
本改动没有修改前端文件或收紧模型输出。生成方式仍为 `plan_source: "template"`，步骤只是骨架；
`execution_authorized` 一律为 `false`，不会调用执行接口。

默认 pytest 只使用本机临时测试服务覆盖成功、降级与规则拦截，不加载 4B。
本机已有健康 4B 且 8765 空闲时，可显式让测试从真实 Runtime 在 HTTP 上调用 4B：

```powershell
$env:UAV_RUNTIME_VERIFY_LOCAL_4B = '1'
python -B -m pytest -q -s tests/integration/test_runtime_local_4b_preview_live.py
Remove-Item Env:UAV_RUNTIME_VERIFY_LOCAL_4B
```

真实门禁要求两个请求实际返回 `local_model`，规则降级不算通过。测试只停止自己启动的
Runtime 子进程，保留既有模型服务。

同一测试开关也能将实际 4B 调用纳入全量测试。它使用隔离的 loopback Runtime 与真实模型，
并不代替 WSL 普通 Runtime 的三机联合验收。

WSL 通路单独复验（Windows 上已有 4B、无现有中转、WSL 的 8765 空闲）：

```powershell
python -B tests/integration/verify_wsl_runtime_model_route.py Ubuntu <WSL内含pymavlink的Python绝对路径>
```

此检查只建立临时中转、普通 Runtime 和三路临时 loopback MAVLink 心跳。
它检查同一 Runtime PID 在真实模型调用前后仍有三路连接，并要求 `local_model`、
`execution_authorized: false`。不启动 SITL，不发布仿真标定，因此不要求三机 `usable`；
未通过这一检查前，不进入正式五句台词联验。
