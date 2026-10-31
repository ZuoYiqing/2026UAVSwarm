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

统一新Runtime版本后，仍由集成唯一启动受管SITL：保持三机disarmed、不加载模型、
不POST任务。检查计数能观察BAD_DATA且不会污染身份，正常样本持续fresh；若仍有
source0真实消息，诊断应保留message_type并继续拒绝。然后再刷新health/标定，
读取HOME/RTL，不据解析过滤直接宣称preflight ready。PR继续Draft，不合并main。
