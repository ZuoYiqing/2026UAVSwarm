# 产品接口报告（消息与协议规范）- protocol_json

版本：v0.1（Demo）

## 1. 设计原则

- 统一消息头：便于多链路、多协议转发
- schema 可验证：协议可版本化、可回溯、可生成
- 字段最小化：链路受限下优先保证状态/目标关键字段

## 2. protocol_json 结构

```json
{
  "version": "0.1",
  "header_fields": [...],
  "messages": [...]
}
```

## 3. 消息列表（Demo）

- UAV_STATUS：周期性状态上报
- TARGET_REPORT：成员->簇首目标上报
- TARGET_SUMMARY：簇首->GS态势摘要
- CMD_MISSION：GS->UAV/Cluster任务调整
- CMD_ACTION：GS->簇首对目标的资源调度动作
- CLUSTER_CMD：簇首->成员簇内重分配
- LINK_STATUS：链路健康状态

## 4. 代码生成

- `messages.h`：C 结构体骨架（可嵌入式）
- `messages.py`：Python dataclasses（测试/仿真/网关）

> 序列化建议：CBOR/Protobuf/Flatbuffers，或自定义紧凑二进制编码。
