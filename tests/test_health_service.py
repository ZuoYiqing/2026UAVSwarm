from uav_runtime.services.health_service import health


def test_health_ok() -> None:
    out = health()
    assert out["status"] == "ok"
    assert out["service"] == "uav-runtime"
