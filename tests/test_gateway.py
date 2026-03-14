from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.gateway import AdapterGateway


def test_gateway_send_success() -> None:
    gw = AdapterGateway()
    gw.register(FakeAdapter())
    out = gw.send("fake", {"a": 1})
    assert out.accepted is True


def test_gateway_missing_adapter() -> None:
    gw = AdapterGateway()
    out = gw.send("none", {})
    assert out.accepted is False
