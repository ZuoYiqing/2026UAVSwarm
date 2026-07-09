from uav_runtime.core.planner import Plan
from uav_runtime.core.protocol import ProtocolSynthesizer


def test_protocol_synthesizer_creates_messages() -> None:
    plan = Plan(mission="demo", tasks=[{"action": "patrol", "params": {"sector": 1}}])
    bundle = ProtocolSynthesizer().synthesize(plan)
    assert len(bundle.messages) == 1
    assert bundle.messages[0]["msg_type"] == "patrol"
