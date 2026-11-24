#!/usr/bin/env python3
"""serve_3d_proxy.py —— 静态服务 3D 构建产物，并把 /api/* 反向代理到 Runtime。

为什么需要它
------------
simulation-3d 的构建产物（dist/assets/index-*.js）里有几处把 API 根地址硬编码成
相对路径 "/api"：

    const o = `${String(e || "/api").replace(/\\/+$/, "")}/vehicle-snapshot`;
    sN = BZe({ apiBaseUrl: "/api" });          // 这一处连 URL 参数都不认

用 `python -m http.server` 起静态服务时，这些请求会打到 5179 自己身上，于是：

    "GET /api/vehicle-snapshot HTTP/1.1" 404 -
    code 404, message File not found

只在浏览器 URL 上加 ?runtimeApiBaseUrl=... 只能救一部分（YZe 那条链路），
硬编码 "/api" 的那处救不了。所以最稳的办法是让 5179 自己把 /api/* 转给 Runtime：

    浏览器 → http://127.0.0.1:5179/api/vehicle-snapshot
           → 本脚本转发 → http://127.0.0.1:8765/api/vehicle-snapshot

这样前端一行代码都不用改，也不需要记 URL 参数。

依赖
----
只用标准库（http.server + urllib），Python 3.8+ 即可。
用系统 python3（3.10）或 ~/tools/python（3.11）都行，**与 pymavlink 无关**。

用法
----
    python3 ops/serve_3d_proxy.py --dir frontend/swarm-console/simulation-3d/dist

    # 指定端口 / Runtime 地址
    python3 ops/serve_3d_proxy.py --dir <dist> --port 5179 --runtime http://127.0.0.1:8765

    # 给另一台机器访问（跨机器演示）
    python3 ops/serve_3d_proxy.py --dir <dist> --bind 0.0.0.0

验证
----
    curl -sI http://127.0.0.1:5179/                              # 200，静态首页
    curl -s  http://127.0.0.1:5179/api/health                    # 转发到 Runtime
    curl -s  http://127.0.0.1:5179/api/vehicle-snapshot | head   # 不再是 404
"""

from __future__ import annotations

import argparse
import functools
import http.server
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROXY_PREFIXES = ("/api/", "/api")


class Handler(http.server.SimpleHTTPRequestHandler):
    """静态文件 + /api/* 反向代理。"""

    runtime_base = "http://127.0.0.1:8765"
    proxy_timeout = 30.0

    # ---------- 路由 ----------

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api" or self.path.startswith("/api/"):
            self._proxy("GET")
        else:
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path == "/api" or self.path.startswith("/api/"):
            self._proxy("HEAD")
        else:
            super().do_HEAD()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api" or self.path.startswith("/api/"):
            self._proxy("POST")
        else:
            self.send_error(405, "Only /api/* accepts POST")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---------- 代理实现 ----------

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _proxy(self, method: str) -> None:
        url = self.runtime_base.rstrip("/") + self.path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        request = urllib.request.Request(url, data=body, method=method)
        content_type = self.headers.get("Content-Type")
        if content_type:
            request.add_header("Content-Type", content_type)

        try:
            with urllib.request.urlopen(request, timeout=self.proxy_timeout) as response:
                self._relay(response.status, response.headers, response.read())
        except urllib.error.HTTPError as error:            # Runtime 自己回的 4xx/5xx
            self._relay(error.code, error.headers, error.read())
        except Exception as error:                          # 连不上 Runtime
            message = (
                f"502 Bad Gateway: cannot reach Runtime at {self.runtime_base}\n"
                f"  {type(error).__name__}: {error}\n"
                f"  Runtime 起了吗？  curl http://127.0.0.1:8765/api/health\n"
            ).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self._cors()
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(message)

    def _relay(self, status: int, headers, payload: bytes) -> None:
        self.send_response(status)
        self.send_header(
            "Content-Type", headers.get("Content-Type", "application/json; charset=utf-8")
        )
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    # ---------- 日志 ----------

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        # 加一截前缀，方便一眼区分"静态请求"和"转发请求"
        kind = "PROXY" if self.path.startswith("/api") else "static"
        sys.stderr.write(f"[{kind}] {self.address_string()} {fmt % args}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="静态服务 3D dist，并把 /api/* 代理到 Runtime")
    parser.add_argument(
        "--dir",
        default="frontend/swarm-console/simulation-3d/dist",
        help="要服务的目录（含 index.html），默认 simulation-3d/dist",
    )
    parser.add_argument("--port", type=int, default=5179, help="监听端口，默认 5179")
    parser.add_argument("--bind", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument(
        "--runtime",
        default="http://127.0.0.1:8765",
        help="Runtime 地址，默认 http://127.0.0.1:8765",
    )
    args = parser.parse_args(argv)

    root = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        print(f"❌ 目录不存在: {root}", file=sys.stderr)
        return 1
    if not (root / "index.html").is_file():
        print(f"❌ 找不到 {root / 'index.html'}", file=sys.stderr)
        return 1

    Handler.runtime_base = args.runtime
    handler = functools.partial(Handler, directory=str(root))

    try:
        server = http.server.ThreadingHTTPServer((args.bind, args.port), handler)
    except OSError as error:
        print(f"❌ 绑定 {args.bind}:{args.port} 失败: {error}", file=sys.stderr)
        print(f"   端口被占用？  ss -ltnpH 'sport = :{args.port}'", file=sys.stderr)
        return 1

    print(f"  服务目录 : {root}")
    print(f"  监听     : http://{args.bind}:{args.port}")
    print(f"  代理前缀 : /api/*  →  {args.runtime}")
    print("  Ctrl+C 停止")
    sys.stdout.flush()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
