from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
import json
from threading import Thread

import pytest

from uav_runtime.http import model_preview_config as config, wsl_model_relay as relay


TOKEN = "synthetic-reader-token-not-a-real-secret"
GATEWAY = "172.19.96.1"


def test_defaults_and_operator_budget_overrides():
    assert config.ModelPreviewConfig.from_env({}).timeout_s == 18
    selected = config.ModelPreviewConfig.from_env({
        "UAV_RUNTIME_LOCAL_MODEL_TIMEOUT_S": "27.5",
        "UAV_RUNTIME_LOCAL_MODEL_ALIAS": "other-approved-model",
    })
    assert selected.alias == "other-approved-model" and selected.timeout_s == 27.5


@pytest.mark.parametrize("value", ["0", "-2", "inf", "nan", "not-a-number", "301"])
def test_invalid_budget_is_a_configuration_error(value):
    with pytest.raises(ValueError, match="timeout"):
        config.ModelPreviewConfig.from_env({"UAV_RUNTIME_LOCAL_MODEL_TIMEOUT_S": value})


@pytest.mark.parametrize("url", [
    "http://localhost:18116/v1", "http://127.0.0.1:18116/v1?next=x",
    "http://127.0.0.1:18116/v1#frag", "http://user@127.0.0.1:18116/v1",
    "http://172.19.96.2:18116/v1", "http://0.0.0.0:18116/v1", "http://192.0.2.10:18116/v1",
])
def test_nonlocal_or_decorated_model_urls_are_rejected(monkeypatch, tmp_path, url):
    monkeypatch.setattr(config, "_wsl_default_gateway", lambda: IPv4Address(GATEWAY))
    token_file = tmp_path / "test-token"
    token_file.write_text(TOKEN, encoding="ascii")
    with pytest.raises(ValueError, match="IPv4|gateway"):
        config.ModelPreviewConfig.from_env({
            "UAV_RUNTIME_LOCAL_MODEL_URL": url, "UAV_RUNTIME_LOCAL_MODEL_TOKEN_FILE": str(token_file),
        })


def test_only_authenticated_wsl_default_gateway_is_admitted(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_wsl_default_gateway", lambda: IPv4Address(GATEWAY))
    url = {"UAV_RUNTIME_LOCAL_MODEL_URL": f"http://{GATEWAY}:18116/v1"}
    with pytest.raises(ValueError, match="authenticated"):
        config.ModelPreviewConfig.from_env(url)
    token_file = tmp_path / "test-token"
    token_file.write_text(TOKEN + "\n", encoding="ascii")
    env = {**url, "UAV_RUNTIME_LOCAL_MODEL_TOKEN_FILE": str(token_file)}
    selected = config.ModelPreviewConfig.from_env(env)
    assert selected.host == GATEWAY and TOKEN not in repr(selected)
    monkeypatch.setattr(config, "_wsl_default_gateway", lambda: None)
    with pytest.raises(ValueError, match="gateway"):
        config.ModelPreviewConfig.from_env(env)


def test_adapter_is_verified_not_just_a_private_address(monkeypatch):
    monkeypatch.setattr(relay.subprocess, "check_output", lambda *args, **kwargs:
                        json.dumps({"IPAddress": GATEWAY, "PrefixLength": 20}))
    assert str(relay._windows_wsl_adapter(IPv4Address(GATEWAY))) == f"{GATEWAY}/20"
    with pytest.raises(ValueError, match="virtual adapter"):
        relay._windows_wsl_adapter(IPv4Address("192.168.1.5"))


@contextmanager
def serving(httpd):
    with httpd:
        thread = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=2)


def test_relay_requires_the_peer_and_token_and_strips_credentials():
    upstream_calls = []

    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            self.reply(None)

        def do_POST(self):
            self.reply(self.rfile.read(int(self.headers["Content-Length"])))

        def reply(self, body):
            upstream_calls.append((self.command, self.path, self.headers.get("Authorization"), body))
            raw = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Upstream)) as upstream:
        bridge = relay._RelayServer(("127.0.0.1", 0), peer="127.0.0.1", token=TOKEN, timeout_s=1,
                                   upstream_port=upstream)
        assert not bridge.verify_request(None, ("127.0.0.2", 1))
        with serving(bridge) as port:
            def call(method, path, *, token=None, body=None):
                connection = HTTPConnection("127.0.0.1", port, timeout=2)
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                try:
                    connection.request(method, path, body, headers)
                    with connection.getresponse() as response:
                        return response.status, json.load(response)
                finally:
                    connection.close()

            assert call("GET", "/health")[0] == 401
            assert call("GET", "/health", token="wrong")[0] == 401
            assert call("GET", "/health?bad=1", token=TOKEN)[0] == 404
            assert call("POST", "/api/plans/execute", token=TOKEN)[0] == 404
            assert call("GET", "/health", token=TOKEN) == (200, {"status": "ok"})
            assert call("POST", "/v1/chat/completions", token=TOKEN, body=b'{"stream":false}')[0] == 200
    assert upstream_calls == [
        ("GET", "/health", None, None),
        ("POST", "/v1/chat/completions", None, b'{"stream":false}'),
    ]
