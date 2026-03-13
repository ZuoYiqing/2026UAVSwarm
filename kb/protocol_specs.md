# 协议知识库：字段定义（Demo）

本文件用于 RAG 检索示例，内容来自你提供的最小场景协议表。

## 通用消息头（Header）

- msg_id (uint16, 2B): 消息类型标识
- msg_len (uint16, 2B): 消息总长度（字节）
- src_node (uint8, 1B): 源节点编号
- dst_node (uint8, 1B): 目的节点编号，0 表示广播
- seq (uint16, 2B): 消息序号
- timestamp (uint32, 4B): 相对时间戳（ms）

## UAV_STATUS

周期性上报无人机状态，建议 5s 周期。
字段：uav_id, x_pos, y_pos, altitude, heading, speed, fuel_level, mission_phase

## TARGET_REPORT

发现可疑目标触发上报，成员 -> 簇首。
字段：uav_id, target_id, x_pos, y_pos, speed, heading, confidence, threat_level

## TARGET_SUMMARY

簇首汇总目标态势，簇首 -> GS。
字段：cluster_id, target_count, summary_flags, reserved, targets[]

## CMD_MISSION

GS 下发任务调整（模式/区域/参数）。
字段：cmd_id, target_uav, mission_mode, area_id, param1, param2

## CMD_ACTION

GS 对目标的处置动作（跟踪/观察/忽略等），演训/巡检可理解为资源调度。
字段：target_id, action, priority, time_limit_s

## CLUSTER_CMD

簇首对簇内成员调整子任务。
字段：cluster_id, target_uav, sub_task, area_id, ref_target_id

## LINK_STATUS

链路健康度：node_id, link_ok, rssi, snr
