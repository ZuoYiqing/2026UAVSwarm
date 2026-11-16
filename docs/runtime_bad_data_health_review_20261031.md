# SITL 健康证据拒绝与 BAD_DATA 边界修复（2026-10-31）

## 现场事实

固定集成 eaebe45，随后诊断版53f2dbe；受管 run_id
`ff4c956d062b4a5ab7c5cbc00e35ef54`，world simple_recon_v0_1。
本轮只做无飞行检查，没有任务 POST、ARM/TAKEOFF/LAND，没有加载模型或前端。
Simulation/Integration 管理启停；Runtime 只读 GET 和本线修复，不另开 receiver。

- 三机 PX4 PID484/1046/1762，独立端口14540/41/42；现场唯一归属为地面01/03、
  平台02。standalone health、三路1280×960递增相机帧和三机静态标定通过。
- Runtime 23:08:08+08 实际 GET：三机 connected=true、stale=false、armed=false；
  平台mode=sitl、同run、ground_link=healthy、active_task=null、fresh landed=1，
  safe_to_stop=true、model_configured=false。
- 但 runtime-telemetry 两个 fresh 标记均false，01/03=session_unavailable，
  02=platform_telemetry_stale；独立位置/心跳时间仍推进。
- 只读诊断提交 c0f2244 加入 session status、RX-alive、identity/receive error，
  没有改健康门。经安全停止/同run重启后，诊断确认三会话 status connected、
  RX alive，但都有 target_system_mismatch：observed_system_id=0。
- 现场诊断文件 SHA256（Integration/Simulation提供）：
  `3b64e5449fbbddc9ffd71779c984c063c0fe99a16bbc8d45da6e6ce6314f37bb`。
  原现场未记录触发消息类型，不能倒推为已经抓到了 BAD_DATA 原包。
- 之后按新鲜落地/未武装/lease lost和精确进程身份安全停止Runtime/代理，再停止
  受管仿真。Integration/Simulation核查无相关进程或端口残留。

## 精确可复现机制

从本机实际 Ubuntu 离线 pymavlink 源码及内存对象确认：
`MAVLink_bad_data(b"invalid", "fixture")` 返回 type=BAD_DATA、source=0/0。
它是解析器产生的伪报文，不是一个真实source0无人机。旧 dispatcher 在取
message type 之前检查身份，因此该对象会把已正确收样的会话永久置
target_system_mismatch。单元回归在修复前实际复现，非仅静态推测。

这证明缺陷机制存在，并与现场观测兼容；**尚未证明原现场的所有sysid0报文
就是BAD_DATA**。下一现场必须检查解析计数、真实拒绝的message_type和freshness。

## 修复边界

只对 get_type()==BAD_DATA 的解析伪帧，在身份判定之前计数并记录UTC接收时间，
不保存/暴露原始payload，不推进RX序号，不更新ACK/遥测/回调，也不清已有身份故障。
诊断增加 parser_error_count/last_parser_error_timestamp；真实拒绝包含message_type
和observed system/component。

真实 HEARTBEAT、LOCAL_POSITION_NED、COMMAND_ACK 的source0或其他错误身份仍
fail closed。握手身份校验、唯一receiver、Policy、2.5s/1.5s样本限时、5s信封TTL、
标定/ground_reference、ACK完成判据均未放宽。只有解析噪声没有有效样本时仍过期。

## 验证

- 修复前新增回归：4 failed、1 passed、1 skipped；其中BAD_DATA污染身份被复现，
  另三个失败为新增message_type诊断尚不存在。Windows缺pymavlink的真实对象测试跳过。
- Windows修复专项（producer/view/session/registry）：124 passed、1 skipped，3.70s。
- Ubuntu实际pymavlink对象+producer/session：62 passed、0 skipped、0 failed，13.48s；
  只构造内存对象，没有打开PX4端口。
- Windows完整回归：1049 passed、8 skipped、0 failed（93.12s）。跳过为5真实多PX4、
  1真实巡检opt-in、1Linux TCP专用验证器、1本机缺pymavlink的真实对象测试；后者已
  在上述Ubuntu实际安装环境通过，不把Windows skip冒充pass。
- diff检查与Python语法检查通过；现场复验仍待集成，不能当作飞行PASS。

## 下一现场判定

### 第二次现场纠正：UNKNOWN 包装器才是该轮触发类型

集成 fe50d80、新run `3a305b4ce28b453a9eabd3d5c89d3cc2` 实际诊断表明，
parser_error_count=0，拒绝类型为 UNKNOWN_291、UNKNOWN_380；Runtime 23:28:59+08
的另一时刻读取还看到 UNKNOWN_8。identity_error 会覆盖为后续错误，所以这些
是不同时间快照，不应写成“三机均同一类型”或“首次错误类型”。此结果排除了
BAD_DATA 作为这一轮的直接拒绝原因，前述BAD_DATA修复不能称作已解决该现场。

新诊断文件SHA256（Simulation独立核查）：
`6c7b376828451feb012d6d257ff5e107f9d213dcfcb07a75a7b063d7ef616511`。
该新run只确认standalone与诊断文件，不声称已有integrated.json通过/失败记录。
新run也已由集成安全清理。

读取本机安装的 MAVLink_unknown 和 decode 源码，确认未识别ID会在CRC_extra/
签名验证、真实header赋值之前返回包装器；其msgId为负sentinel -2，source默认0/0。
Simulation读取本机PX4 build将291映射为ESC_STATUS、380为TIME_ESTIMATE_TO_TARGET，
且当前venv v10/v20 dialect map均不含291/380；单设MAVLINK20不能解决。
不能据包装器或raw header声称该帧CRC/源身份有效。

最小处理不升级离线依赖，也不解码/使用上述负载：只对MAVLink_unknown类、
负sentinel -2、合法UNKNOWN数字标签三者同时满足的包装器隔离并记录有界
unsupported计数/type/time。它不进入ACK/遥测/回调/RX cursor/模型，不清已有故障。
普通解码消息即使名字UNKNOWN_*或source0、以及非负msgId对象仍严格拒绝。
仅正确源、已识别的HB/LOCAL样本能贡献两类fresh；只有未知帧仍会stale。
这不是把未知帧当作良性或有效，而是不能让其合成header冒充身份断言。
ESC/时间估算等未支持负载依然不可用，完整dialect兼容升级是独立后续事项。

新增包装器回归先2项失败复现。修复后Windows专项128 passed、1 skipped（3.82s）；
Ubuntu真实pymavlink对象/producer/session专项66 passed、0 skipped（12.09s）；
Windows完整回归1053 passed、8 skipped、0 failed（83.09s），跳过分类同前。
AST与diff/cached检查通过。下一新run仍需实测unsupported
计数、身份无误、已识别样本新鲜，再运行integrated health、标定和HOME/RTL。

统一新Runtime版本后，仍由集成唯一启动受管SITL：保持三机disarmed、不加载模型、
不POST任务。检查计数能观察BAD_DATA且不会污染身份，正常样本持续fresh；若仍有
source0真实消息，诊断应保留message_type并继续拒绝。然后再刷新health/标定，
读取HOME/RTL，不据解析过滤直接宣称preflight ready。PR继续Draft，不合并main。

## 第三轮真实 SITL 只读复验（2026-11-01）

本节是后续实测，前文的失败和当时“待复验”结论保留为历史记录。
集成负责人于08:44–09:03（Asia/Shanghai）恢复并独占操作受管run
`85051379fdde404c87c06ddeb545c143`，固定集成提交`5b7936c`，包含Runtime
`73dc599b3ac44ff95fc69424bec22717d4addd23`。Runtime负责人于14:08后只读
核对原始JSON、集成对话中的实际命令/输出和本机停止状态；没有重新启动仿真。

### 已通过的范围

- `integrated.json`（08:54:32）、`integrated-published.json`（08:57:06）、
  `integrated-preflight.json`（08:59:10）均为同run、mode=integrated、ready=true，
  三节点heartbeat_fresh/telemetry_fresh/process_identity_valid均true、reason=ok。
  这三个时间点的RTF分别约0.556/0.561/0.537；不能据此声称全负载性能或飞行性能。
- 最后保存的`runtime-telemetry.json`时间为08:59:42，源为runtime_session_rx，
  sysid1/2/3、compid1、端口14540/41/42，三会话connected、RX alive，
  identity_error/last_receive_error均null，parser_error_count均0。
  unsupported_message_count分别5569/5998/5552，最后类型均UNKNOWN_291；
  同时只有已识别样本提供freshness。各机heartbeat age约1510/745/2214ms，
  position age约6/505/75ms，仍使用原2500/1500ms限制。
  大量未知包装器仍被隔离，但不再冒用合成0/0污染会话身份。
- 08:59:03静态标定报告status=PASS、mode=read_only_no_mavlink，三机各13个
  配对样本、跨度约1.088s，最大残差分别0.0105/0.0131/0.0185m，发布3/3成功。
  未激励物理轴运动；不能写成完整动态坐标标定或机载感知验证。
- 随后实际`GET /api/preflight?node_id=UAV-02`于08:59:10返回ready、
  reason_codes=[]，三机fresh_disarmed=true、landed_state=1、busy=false。
  HOME证据verified=true，global/local XY交叉误差约0.0041m；
  RTL_TYPE=0、rally count=0、rtl_destination_evidence.verified=true。
  HOME请求的ACK为command512/result0，是只读信息请求，不是起降执行ACK。
  响应明确execution_authorized=false、flight_command_sent=false。

### 没有掩盖的失败/边界

08:57:57第一次预检为not_ready：ground_reference_unavailable及
home_or_rtl_not_checked；当时health年龄约51s，且08:54:58发布的标定也早已
超过60s。刷新标定和动态health后，08:59:10才ready。该对比同时改变了两个
过期条件，**不能用于证明静态ground_reference被health TTL错误失效，也不能
用于证明其长期有效性**；静态几何、动态健康、标定生命周期须继续分别判断。
上述ready仅是各采样时刻的证据，保存文件现在已过期，不可重新发布成当前证据。

本轮没有任务POST、ARM/TAKEOFF/LAND，没有加载模型、主控台或三维前端。
因此没有飞行命令ACK、起飞稳定高度、实际LAND完成、切链期间任务继续、
模型与仿真同负载、双前端一致性或屋顶反例验收。先前模型+fake任务的通过
不能与本轮真实遥测拼接成一次完整飞行成功。PR #97/#93继续Draft，不合并main。

### 原始证据及安全收尾

原始JSON保留在固定集成checkout的忽略目录：
`D:/2026UAVSwarm/.runtime/uav02-autonomy-integration/.runtime/px4_gazebo/health/85051379fdde404c87c06ddeb545c143/`。
以下SHA256由Runtime负责人在2026-11-01独立读取文件计算，不提交运行产物：

| 文件 | SHA256 |
| --- | --- |
| integrated.json | `cbd0d2765ae8c763e558e1cdb01ec4ceb3653171bbe3a636db69a06909b1058a` |
| integrated-published.json | `7e0498d11e3734fdd7a9e609313fa0883e21c07530acbd3629267c77c9cb3252` |
| integrated-preflight.json | `3d08628b0bea389f5a24068503a6ef25b3ea4d6a00ff0a36aec0e8afd37384e9` |
| calibration-preflight.json | `9140229210a8c68f7a50a5df9ab2930811b3bbc84be18c133944c1b73c52fa1b` |
| runtime-telemetry.json | `321bb78d9f470581c74d525e95e68dff35abe5b9542cf1f583496765a80c412a` |

预检响应及停止命令输出保留在集成负责人对话
`019ff00c-d362-7022-9f2a-4b3af2935b4b`的任务
`01a19490-7e74-74d1-ae6f-def18fd75484`；本目录没有单独保存preflight响应JSON，
不将integrated-preflight.json误称为该HTTP响应。

集成先正常退出导出器/地面Runtime，再执行受管`onboard_deployment.py stop-sitl`
和`stop_three_uav.sh`，均exit0；stop-sitl返回同run的stopped，Harness返回
cleanup.clean=true、world_stopped=true、ports_released=true。Gazebo子进程短暂
退出中后自行消失，后续进程/监听复核为空，没有据旧PID强杀。
14:08本线复核默认Ubuntu为Stopped、两个受管state不存在、相关Windows TCP
监听为空、主机可用内存3.62GiB。该检查不是新的在线健康或飞行验收。

### 本线归档复核

2026-11-01在Runtime独立工作区执行：

```text
python -B -m pytest -q -rs -p no:cacheprovider tests/unit/test_runtime_telemetry_evidence.py tests/unit/test_platform_view.py tests/unit/test_mavlink_backend_session.py tests/unit/test_vehicle_registry.py --basetemp .tmp_runtime_readonly_review_20261101
```

结果128 passed、1 skipped、0 failed（3.88s）。Windows未安装pymavlink，真实
解析对象测试跳过；前文Ubuntu实际安装环境66 passed的历史结果仍有其原版本
边界，不当成本轮重跑。本轮仅更新两份Runtime主责文档，未修改执行代码、
接口字段、TTL、配置或依赖；未重新运行全仓测试，不将先前1053 passed写成新结果。
