"""Short-lived, loopback-only status page for the owner's YouTube OAuth flow."""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Literal


OAuthPageState = Literal["waiting", "connected", "stopped"]
_ALLOWED_STATES = frozenset({"waiting", "connected", "stopped"})

_HTML = """<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>เชื่อมต่อ YouTube</title>
  <link rel="stylesheet" href="style.css">
  <script src="app.js" defer></script>
</head>
<body>
  <main class="card">
    <div class="brand-mark" aria-hidden="true">▶</div>
    <p class="eyebrow">KATY404 · YOUTUBE</p>
    <h1>เชื่อมต่อบัญชี YouTube</h1>
    <div class="status-line" role="status" aria-live="polite">
      <span id="status-dot" class="dot" aria-hidden="true"></span>
      <span id="status-title">กำลังรอการยืนยันจาก Google</span>
    </div>
    <p id="status-detail" class="detail">ทำขั้นตอนลงชื่อเข้าใช้และยินยอมในหน้าต่าง Google ที่เปิดขึ้น</p>
    <p class="footnote">หน้านี้แสดงสถานะการเชื่อมต่อเท่านั้น และจะไม่ขอหรือแสดงรหัสผ่านหรือ token</p>
  </main>
</body>
</html>
"""

_CSS = """* { box-sizing: border-box; }
:root { color-scheme: dark; font-family: "Segoe UI", "Noto Sans Thai", sans-serif; }
body {
  min-height: 100vh; margin: 0; display: grid; place-items: center; padding: 24px;
  color: #f1f5f9; background: radial-gradient(circle at 50% 0%, #192b46 0, #0b1220 48%, #080c15 100%);
}
.card {
  width: min(100%, 520px); padding: 42px; border: 1px solid #26354b; border-radius: 22px;
  background: rgba(15, 24, 39, .94); box-shadow: 0 24px 80px rgba(0, 0, 0, .36);
}
.brand-mark {
  width: 48px; height: 36px; display: grid; place-items: center; margin-bottom: 30px;
  border-radius: 11px; color: white; background: #e11d48; font-size: 18px;
}
.eyebrow { margin: 0 0 10px; color: #8fa9cb; font-size: 12px; font-weight: 700; letter-spacing: .13em; }
h1 { margin: 0 0 26px; font-size: clamp(24px, 5vw, 32px); letter-spacing: -.025em; }
.status-line { display: flex; align-items: center; gap: 12px; font-size: 17px; font-weight: 650; }
.dot { width: 10px; height: 10px; flex: none; border-radius: 50%; background: #38bdf8; box-shadow: 0 0 18px #38bdf855; }
.status-connected .dot { background: #34d399; box-shadow: 0 0 18px #34d39966; }
.status-stopped .dot { background: #fb7185; box-shadow: 0 0 18px #fb718566; }
.detail { min-height: 48px; margin: 12px 0 30px 22px; color: #b8c5d8; line-height: 1.7; }
.footnote { margin: 0; padding-top: 18px; border-top: 1px solid #26354b; color: #8293aa; font-size: 13px; line-height: 1.65; }
"""

_JAVASCRIPT = """(() => {
  const title = document.getElementById("status-title");
  const detail = document.getElementById("status-detail");
  const line = document.querySelector(".status-line");
  const states = {
    waiting: ["กำลังรอการยืนยันจาก Google", "ทำขั้นตอนลงชื่อเข้าใช้และยินยอมในหน้าต่าง Google ที่เปิดขึ้น"],
    connected: ["เชื่อมต่อบัญชีสำเร็จ", "บันทึก OAuth credential ในไฟล์ของบัญชีที่เลือกแล้ว กลับไปดูผลในโปรแกรม"],
    stopped: ["การเชื่อมต่อหยุดแล้ว", "ดูรายละเอียดในหน้าต่างโปรแกรม แล้วลองใหม่เมื่อพร้อม"]
  };
  let timer = null;
  let terminal = false;

  async function poll() {
    try {
      const response = await fetch("status", { cache: "no-store", credentials: "same-origin" });
      if (!response.ok) throw new Error("status unavailable");
      const result = await response.json();
      const message = states[result.state];
      if (!message) throw new Error("unknown status");
      title.textContent = message[0];
      detail.textContent = message[1];
      line.className = `status-line status-${result.state}`;

      if (result.state === "connected" || result.state === "stopped") {
        terminal = true;
        if (timer !== null) window.clearTimeout(timer);
        await fetch("ack", { method: "POST", cache: "no-store", credentials: "same-origin" });
        return;
      }
    } catch (_) {
      // Keep waiting if the local page cannot read its status yet.
    }

    if (!terminal) timer = window.setTimeout(poll, 500);
  }

  poll();
})();
"""


class OAuthStatusPageError(RuntimeError):
    """A generic local status-page startup error safe to show without details."""


class LocalOAuthStatusPage:
    """Serve a private status page during one interactive OAuth authorization."""

    def __init__(
        self,
        *,
        browser_open: Callable[[str], bool] | None = None,
        terminal_read_timeout_seconds: float = 5.0,
    ) -> None:
        if terminal_read_timeout_seconds < 0:
            raise ValueError("terminal_read_timeout_seconds cannot be negative")
        self._browser_open = browser_open if browser_open is not None else webbrowser.open
        self._terminal_read_timeout_seconds = terminal_read_timeout_seconds
        self._nonce = secrets.token_urlsafe(24)
        self._state: OAuthPageState = "waiting"
        self._state_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._terminal_read = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._url: str | None = None
        self._status_url: str | None = None
        self._expected_host: str | None = None
        self._closed = False

    @property
    def url(self) -> str:
        if self._url is None:
            raise RuntimeError("Status page has not been started")
        return self._url

    @property
    def status_url(self) -> str:
        if self._status_url is None:
            raise RuntimeError("Status page has not been started")
        return self._status_url

    def start(self) -> None:
        """Bind to loopback, run the static page, and open it in the browser."""
        with self._lifecycle_lock:
            if self._closed or self._server is not None:
                raise OAuthStatusPageError("Could not start local OAuth status page")
            try:
                server = ThreadingHTTPServer(
                    ("127.0.0.1", 0),
                    self._make_handler(),
                )
                server.daemon_threads = True
                self._server = server
                port = server.server_address[1]
                self._expected_host = f"127.0.0.1:{port}"
                self._url = f"http://127.0.0.1:{port}/{self._nonce}/"
                self._status_url = f"http://127.0.0.1:{port}/{self._nonce}/status"
                thread = threading.Thread(
                    target=server.serve_forever,
                    kwargs={"poll_interval": 0.05},
                    name="youtube-oauth-status",
                    daemon=True,
                )
                self._thread = thread
                thread.start()
            except Exception as exc:
                self.close()
                raise OAuthStatusPageError("Could not start local OAuth status page") from exc

        try:
            opened = self._browser_open(self.url)
        except Exception as exc:
            self.close()
            raise OAuthStatusPageError("Could not open local OAuth status page") from exc
        if not opened:
            self.close()
            raise OAuthStatusPageError("Could not open local OAuth status page")

    def set_state(self, state: OAuthPageState) -> None:
        if state not in _ALLOWED_STATES:
            raise ValueError("Unknown OAuth status")
        with self._state_lock:
            self._state = state

    def finish(self) -> None:
        """Wait briefly for the page to acknowledge its terminal status, then close."""
        if self._server is None:
            self.close()
            return
        self._terminal_read.wait(self._terminal_read_timeout_seconds)
        self.close()

    def close(self) -> None:
        """Close the loopback listener safely; repeated calls are harmless."""
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            server = self._server
            thread = self._thread
            self._server = None
        if server is None:
            return
        if thread is not None and thread.is_alive():
            server.shutdown()
        server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)

    def _current_state(self) -> OAuthPageState:
        with self._state_lock:
            return self._state

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        page = self

        class StatusHandler(BaseHTTPRequestHandler):
            server_version = "LocalOAuthStatus"
            sys_version = ""

            def log_message(self, _format: str, *args: object) -> None:
                return

            def _headers(self, content_type: str, content_length: int | None = None) -> None:
                self.send_header("Content-Type", content_type)
                if content_length is not None:
                    self.send_header("Content-Length", str(content_length))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")

            def _respond(self, status: int, body: bytes = b"", content_type: str = "text/plain; charset=utf-8") -> None:
                self.send_response(status)
                self._headers(content_type, None if status == 204 else len(body))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _host_is_local(self) -> bool:
                return self.headers.get("Host") == page._expected_host

            def _not_found(self) -> None:
                self._respond(404, b"Not found")

            def do_GET(self) -> None:
                if not self._host_is_local():
                    self._not_found()
                    return
                path = self.path
                if "?" in path or "#" in path:
                    self._not_found()
                    return
                base = f"/{page._nonce}/"
                assets = {
                    f"/{page._nonce}/app.js": (_JAVASCRIPT.encode("utf-8"), "text/javascript; charset=utf-8"),
                    f"/{page._nonce}/style.css": (_CSS.encode("utf-8"), "text/css; charset=utf-8"),
                }
                if path == base:
                    self._respond(200, _HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif path == f"/{page._nonce}/status":
                    payload = json.dumps({"state": page._current_state()}, separators=(",", ":")).encode("utf-8")
                    self._respond(200, payload, "application/json; charset=utf-8")
                elif path in assets:
                    body, content_type = assets[path]
                    self._respond(200, body, content_type)
                else:
                    self._not_found()

            def do_POST(self) -> None:
                if not self._host_is_local() or self.path != f"/{page._nonce}/ack":
                    self._not_found()
                    return
                if self.headers.get("Content-Length", "0") != "0" or self.headers.get("Transfer-Encoding"):
                    self._respond(400, b"Invalid acknowledgement")
                    return
                if page._current_state() not in ("connected", "stopped"):
                    self._respond(409, b"Terminal status not available")
                    return
                self._respond(204)
                page._terminal_read.set()

            def do_HEAD(self) -> None:
                self._not_found()

            def do_PUT(self) -> None:
                self._not_found()

            def do_DELETE(self) -> None:
                self._not_found()

            def do_OPTIONS(self) -> None:
                self._not_found()

        return StatusHandler
