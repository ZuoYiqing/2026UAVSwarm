"""`gz topic --json-output` 输出的解析测试。

要修的问题（实测，不是设想）
--------------------------
三机巡逻验收报 `status: FAIL`，唯一原因是 UAV-01 的标定检查抛了：

    Extra data: line 1 column 14 (char 13)

`Extra data` 是 `json.JSONDecodeError` 的格式，含义是"一个 JSON 值之后还有内容"。
调用链闭合在 `evidence.json_messages`：

    capture_poses()  → json_messages(result.stdout)   ← 没有 try，异常直接抛
    json_messages()  → json.loads(line)               ← 假设"每行一个 JSON 对象"
    → 抛进 patrol._monitor_origin → _calibration_error → calibration_valid_at_end=False

**那句文档注释里的假设在负载下不成立**：`gz topic` 会把多个对象写进同一行。
三机 + 相机版比原来负载大得多（RTF 0.948、三路相机 30fps），更容易撞上。

修法
----
用 `json.JSONDecoder.raw_decode` 增量解析，而不是按行。它对
「每行一个对象」「一行多个对象」「带前导/尾随空白」三种情况都成立 ——
**严格比原来更宽容**，所以不会破坏当前能工作的场景。
"""
from __future__ import annotations

import json

import pytest

from simulation.px4_gazebo.evidence import json_messages


def test_single_object_per_line_still_works() -> None:
    """原有行为必须保留：每行一个对象。"""
    output = '{"a": 1}\n{"a": 2}\n'
    assert json_messages(output) == [{"a": 1}, {"a": 2}]


def test_multiple_objects_on_one_line_are_all_parsed() -> None:
    """**这是修的那个 bug**：一行里有两个对象，按行解析会报 Extra data。

    真实的报错是 `Extra data: line 1 column 14 (char 13)`：
    前 13 个字符是一个合法 JSON 值，后面还跟着另一个。
    """
    output = '{"a": 1}{"a": 2}\n'
    assert json_messages(output) == [{"a": 1}, {"a": 2}]


def test_the_exact_error_shape_from_the_incident() -> None:
    """复现那次失败的确切形状。

    构造一个"前 13 字符是合法 JSON、后面还有内容"的输入，
    断言旧写法会抛 `Extra data`、新写法能解析出来。
    """
    # '{"sec":1}' 正好 9 字符；补成 13 字符：'{"sec":17912}' 是 13 字符
    first = '{"sec":17912}'
    assert len(first) == 13, f"构造的长度应是 13，实际 {len(first)}"
    output = first + '{"sec":17913}\n'

    # 旧行为：按行解析 → Extra data: line 1 column 14 (char 13)
    with pytest.raises(json.JSONDecodeError) as excinfo:
        json.loads(output.strip())
    assert "Extra data" in str(excinfo.value)
    assert excinfo.value.pos == 13

    # 新行为：两个都能解析出来
    assert json_messages(output) == [{"sec": 17912}, {"sec": 17913}]


def test_mixed_line_and_concatenated() -> None:
    """两种形态混在一起也要成立。"""
    output = '{"a": 1}\n{"b": 2}{"c": 3}\n{"d": 4}\n'
    assert json_messages(output) == [{"a": 1}, {"b": 2}, {"c": 3}, {"d": 4}]


def test_blank_lines_and_whitespace_are_ignored() -> None:
    output = '\n  \n{"a": 1}\n\t\n{"a": 2}\n\n'
    assert json_messages(output) == [{"a": 1}, {"a": 2}]


def test_empty_output_is_empty_list() -> None:
    assert json_messages("") == []
    assert json_messages("\n \n\t\n") == []


def test_non_object_is_rejected() -> None:
    """非对象必须拒绝 —— 下游按 dict 取字段，放任会变成更晚的 KeyError。"""
    with pytest.raises(ValueError, match="gazebo_message_not_object"):
        json_messages("[1, 2, 3]\n")


def test_non_object_after_a_valid_object_still_rejected() -> None:
    """不能因为前面解析成功就放过后面的非对象。"""
    with pytest.raises(ValueError, match="gazebo_message_not_object"):
        json_messages('{"a": 1}\n"just a string"\n')


def test_truncated_output_is_rejected_not_silently_dropped() -> None:
    """被截断的最后一个对象必须报错，**不能静默丢弃**。

    为什么这条重要：静默丢弃会让"少了一帧位姿"看起来像"采样就是这么多"，
    而位姿序列正是标定与间距判据的依据 —— 少一帧可能让判据算错而不报错。
    """
    with pytest.raises(json.JSONDecodeError):
        json_messages('{"a": 1}\n{"b": ')


def test_trailing_garbage_is_rejected() -> None:
    """合法对象之后的非 JSON 垃圾必须报错，不能只取前面的。"""
    with pytest.raises(json.JSONDecodeError):
        json_messages('{"a": 1}\n<not json>\n')


def test_realistic_pose_message_shape() -> None:
    """贴近真实的 dynamic_pose 消息：一行挤了多个。"""
    one = '{"header":{"stamp":{"sec":17912,"nsec":0}},"pose":[{"name":"x500_mono_cam_0"}]}'
    two = '{"header":{"stamp":{"sec":17912,"nsec":100000000}},"pose":[{"name":"x500_mono_cam_1"}]}'
    rows = json_messages(one + two + "\n")
    assert len(rows) == 2
    assert rows[0]["pose"][0]["name"] == "x500_mono_cam_0"
    assert rows[1]["pose"][0]["name"] == "x500_mono_cam_1"
