# 任务规划页：本地 4B 只读预览

普通 Runtime 启动方式不变，不调用模型。演示需要手动启用，只使用已经启动的
`127.0.0.1:18116` 本地推理服务（模型别名 `qwen3.5-4b-q4-lab`）；不下载、打包或启动模型。

在独立 Runtime worktree 根目录执行：

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -B -m uav_runtime.http.server --read-only-model-preview
```

Runtime 监听 `127.0.0.1:8765`。如果主控制台未运行，在另一个终端从同一目录启动：

```powershell
python -B -m http.server 5178 --bind 127.0.0.1 --directory frontend/swarm-console
```

打开 `http://localhost:5178/` 的任务规划页。若页面保存过测试 API，确认连接地址为
`http://127.0.0.1:8765/api`。在“任务目标”输入“巡检西北区域。”，点击“预览任务”，
不手选固定模板。这个模式只接收本机浏览器请求，
不启动遥测、飞控接收器、平台网关或故障注入；除只读规划预览外，拒绝全部 POST。
如果 8765 已有 Runtime，先由该进程的操作者正常停掉它，不抢端口或杀别的服务。

## 页面和测试判据

| 路径 | 页面可见字段 |
| --- | --- |
| 真实模型输出通过校验 | `intent_source: "local_model"`，`fallback_reason: null` |
| 服务未就绪、超时或正在忙 | `intent_source: "rules"`，`fallback_reason: "model_unavailable"` |
| 回答无效、换目标、漏排除项或改顺序 | `intent_source: "rules"`，`fallback_reason: "model_low_confidence"`（拒收原因，不代表测出了一个置信度分数） |
| 目录目标有歧义、互斥、属于仅参照项或规则无法绑定 | 不叫模型去猜；保留原有澄清或拒绝回包，无降级标记 |

自动预览先用当前场景目录验证请求能明确绑定。模型只看到用户原话和编号目录，不看到规则答案；
模型选出的目标、顺序、仅定位与排除项须与已验证约束一致。通过后采用模型绑定，字面证据仍来自原话。
这是首演版的有限识别，不代表支持目录外对象或自由任务分解。模型预算不超过 4 秒，给现有前端的
5 秒 HTTP 限时留出余量。生成方式仍为 `plan_source: "template"`，步骤只是骨架；
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

也可保留同一环境开关执行 `python -B -m pytest -q -rs`，将实际 4B 调用纳入全量测试。
模型长时间空闲后，首个预览曾超时并按预期显示降级；健康接口返回正常不等于首个推理能在
4 秒内完成。演示前可先跑上面的真实门禁确认模型已能及时响应，再启动控制台预览 Runtime。
