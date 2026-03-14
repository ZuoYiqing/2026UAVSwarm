from __future__ import annotations

from typing import Any, Dict, List


def _header_fields() -> List[Dict[str, Any]]:
    # Based on the field table in your provided demo protocol.
    return [
        {"name": "msg_id", "type": "uint16", "length": 2, "range": "0-65535", "desc": "消息类型标识"},
        {"name": "msg_len", "type": "uint16", "length": 2, "range": "0-65535", "desc": "消息总长度（字节）"},
        {"name": "src_node", "type": "uint8", "length": 1, "range": "1-255", "desc": "源节点编号"},
        {"name": "dst_node", "type": "uint8", "length": 1, "range": "0=广播,1-255=单播", "desc": "目的节点编号"},
        {"name": "seq", "type": "uint16", "length": 2, "range": "0-65535", "desc": "消息序号"},
        {"name": "timestamp", "type": "uint32", "length": 4, "range": "ms", "desc": "相对时间戳"},
    ]


def _msg_uav_status() -> Dict[str, Any]:
    return {
        "name": "UAV_STATUS",
        "msg_id": 1001,
        "direction": "UAV->GS",
        "trigger": "periodic",
        "period_s": 5,
        "comment": "无人机周期性状态上报",
        "fields": [
            {"name": "uav_id", "type": "uint8", "length": 1, "range": "1-255", "desc": "无人机编号"},
            {"name": "x_pos", "type": "float32", "length": 4, "range": "km", "desc": "X 方向位置"},
            {"name": "y_pos", "type": "float32", "length": 4, "range": "km", "desc": "Y 方向位置"},
            {"name": "altitude", "type": "float32", "length": 4, "range": "m", "desc": "高度"},
            {"name": "heading", "type": "float32", "length": 4, "range": "deg", "desc": "航向角"},
            {"name": "speed", "type": "float32", "length": 4, "range": "m/s", "desc": "速度"},
            {"name": "fuel_level", "type": "uint8", "length": 1, "range": "0-100", "desc": "燃油/电量百分比"},
            {"name": "mission_phase", "type": "uint8", "length": 1, "range": "0=Idle,1=Search,2=Track", "desc": "任务阶段"},
        ],
    }


def _msg_target_report() -> Dict[str, Any]:
    return {
        "name": "TARGET_REPORT",
        "msg_id": 1101,
        "direction": "UAV->ClusterHead",
        "trigger": "event",
        "comment": "发现可疑目标的上报",
        "fields": [
            {"name": "uav_id", "type": "uint8", "length": 1, "range": "1-255", "desc": "上报无人机编号"},
            {"name": "target_id", "type": "uint16", "length": 2, "range": "1-65535", "desc": "目标临时编号"},
            {"name": "x_pos", "type": "float32", "length": 4, "range": "km", "desc": "目标估计位置 X"},
            {"name": "y_pos", "type": "float32", "length": 4, "range": "km", "desc": "目标估计位置 Y"},
            {"name": "speed", "type": "float32", "length": 4, "range": "m/s", "desc": "目标估计速度"},
            {"name": "heading", "type": "float32", "length": 4, "range": "deg", "desc": "目标估计航向"},
            {"name": "confidence", "type": "uint8", "length": 1, "range": "0-100", "desc": "目标可信度"},
            {"name": "threat_level", "type": "uint8", "length": 1, "range": "0=低,1=中,2=高", "desc": "威胁等级"},
        ],
    }


def _msg_target_summary() -> Dict[str, Any]:
    return {
        "name": "TARGET_SUMMARY",
        "msg_id": 1201,
        "direction": "ClusterHead->GS",
        "trigger": "event/periodic",
        "comment": "簇首汇总目标态势摘要",
        "fields": [
            {"name": "cluster_id", "type": "uint8", "length": 1, "range": "1-255", "desc": "簇编号"},
            {"name": "target_count", "type": "uint8", "length": 1, "range": "0-255", "desc": "目标数量"},
            {"name": "summary_flags", "type": "uint16", "length": 2, "range": "bitmask", "desc": "摘要标志"},
            {"name": "reserved", "type": "uint16", "length": 2, "range": "-", "desc": "预留"},
            {"name": "targets", "type": "struct[]", "length": 0, "range": "variable", "desc": "目标列表(简化版)"},
        ],
    }


def _msg_cmd_mission() -> Dict[str, Any]:
    return {
        "name": "CMD_MISSION",
        "msg_id": 2001,
        "direction": "GS->UAV/Cluster",
        "trigger": "event",
        "comment": "任务模式/区域调整命令",
        "fields": [
            {"name": "cmd_id", "type": "uint16", "length": 2, "range": "固定=2001", "desc": "命令编号"},
            {"name": "target_uav", "type": "uint8", "length": 1, "range": "0=广播,1-255", "desc": "命令目标"},
            {"name": "mission_mode", "type": "uint8", "length": 1, "range": "1=继续搜索,2=重点搜索,3=返回", "desc": "任务模式"},
            {"name": "area_id", "type": "uint16", "length": 2, "range": "0=全局,其他=局部", "desc": "区域 ID"},
            {"name": "param1", "type": "float32", "length": 4, "range": "-", "desc": "备用参数1"},
            {"name": "param2", "type": "float32", "length": 4, "range": "-", "desc": "备用参数2"},
        ],
    }


def _msg_cmd_action() -> Dict[str, Any]:
    return {
        "name": "CMD_ACTION",
        "msg_id": 2002,
        "direction": "GS->UAV/Cluster",
        "trigger": "event",
        "comment": "对目标的处置动作(跟踪/观察/忽略等，民用演训可理解为资源分配动作)",
        "fields": [
            {"name": "target_id", "type": "uint16", "length": 2, "range": "1-65535", "desc": "目标编号"},
            {"name": "action", "type": "uint8", "length": 1, "range": "1=跟踪,2=保持观察,3=忽略", "desc": "动作"},
            {"name": "priority", "type": "uint8", "length": 1, "range": "0-10", "desc": "优先级"},
            {"name": "time_limit_s", "type": "uint16", "length": 2, "range": "秒", "desc": "有效时间"},
        ],
    }


def _msg_cluster_cmd() -> Dict[str, Any]:
    return {
        "name": "CLUSTER_CMD",
        "msg_id": 2101,
        "direction": "ClusterHead->Member",
        "trigger": "event",
        "comment": "簇内任务重分配",
        "fields": [
            {"name": "cluster_id", "type": "uint8", "length": 1, "range": "1-255", "desc": "簇编号"},
            {"name": "target_uav", "type": "uint8", "length": 1, "range": "1-255", "desc": "被调整 UAV"},
            {"name": "sub_task", "type": "uint8", "length": 1, "range": "1=继续搜索,2=转为跟踪,3=返回", "desc": "子任务"},
            {"name": "area_id", "type": "uint16", "length": 2, "range": "区域ID", "desc": "任务区域"},
            {"name": "ref_target_id", "type": "uint16", "length": 2, "range": "可为0", "desc": "参考目标"},
        ],
    }


def _msg_link_status() -> Dict[str, Any]:
    return {
        "name": "LINK_STATUS",
        "msg_id": 3001,
        "direction": "Any->Any",
        "trigger": "periodic",
        "period_s": 2,
        "comment": "链路健康状态",
        "fields": [
            {"name": "node_id", "type": "uint8", "length": 1, "range": "1-255", "desc": "节点编号"},
            {"name": "link_ok", "type": "uint8", "length": 1, "range": "0/1", "desc": "链路是否正常"},
            {"name": "rssi", "type": "int8", "length": 1, "range": "dBm", "desc": "RSSI"},
            {"name": "snr", "type": "int8", "length": 1, "range": "dB", "desc": "SNR"},
        ],
    }


class ProtocolSynthesizer:
    """Protocol synthesizer.

    For demo purposes, we generate a canonical protocol that matches the example scenario.
    In a production system, this module would:
    - retrieve relevant protocol entries via RAG
    - diff/merge with existing protocol_json
    - add new message defs when needed
    - run schema/constraint checks
    """

    def synthesize(self, decision: Dict[str, Any], scene: Dict[str, Any]) -> Dict[str, Any]:
        _ = decision
        _ = scene

        protocol = {
            "version": "0.1",
            "header_fields": _header_fields(),
            "messages": [
                _msg_uav_status(),
                _msg_target_report(),
                _msg_target_summary(),
                _msg_cmd_mission(),
                _msg_cmd_action(),
                _msg_cluster_cmd(),
                _msg_link_status(),
            ],
        }
        return protocol
