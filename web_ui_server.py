#!/usr/bin/env python3
from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any, Callable
import urllib.parse


HTML_PAGE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BoramClaw Web UI</title>
  <style>
    :root { color-scheme: light; }
    body { margin: 0; font-family: "Pretendard", "Noto Sans KR", sans-serif; background: #f5f7fb; color: #101828; }
    .wrap { max-width: 920px; margin: 0 auto; padding: 24px; }
    .card { background: #fff; border-radius: 12px; box-shadow: 0 10px 30px rgba(16,24,40,.08); padding: 16px; }
    h1 { margin: 0 0 12px; font-size: 22px; }
    .row { display: flex; gap: 10px; }
    textarea { width: 100%; min-height: 96px; border: 1px solid #d0d5dd; border-radius: 10px; padding: 10px; resize: vertical; }
    button { border: 0; border-radius: 10px; padding: 10px 16px; background: #2563eb; color: #fff; font-weight: 600; cursor: pointer; }
    button:disabled { opacity: .6; cursor: not-allowed; }
    pre { white-space: pre-wrap; background: #0f172a; color: #e2e8f0; border-radius: 10px; padding: 12px; min-height: 160px; overflow: auto; }
    .meta { margin-top: 8px; color: #475467; font-size: 13px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>BoramClaw Web UI</h1>
      <div class="row">
        <textarea id="msg" placeholder="메시지를 입력하세요. 예: 아카이브에서 오늘 논문 3개 요약해줘"></textarea>
      </div>
      <div class="row" style="margin-top:10px">
        <button id="askBtn" type="button">질문 보내기</button>
      </div>
      <div class="meta" id="meta"></div>
      <pre id="out"></pre>
    </div>
  </div>
  <script>
    const askBtn = document.getElementById("askBtn");
    const msg = document.getElementById("msg");
    const out = document.getElementById("out");
    const meta = document.getElementById("meta");
    async function ask() {
      const text = msg.value.trim();
      if (!text) return;
      askBtn.disabled = true;
      out.textContent = "처리 중...";
      meta.textContent = "";
      const started = Date.now();
      try {
        const res = await fetch("/api/ask", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({message: text})
        });
        const data = await res.json();
        if (!res.ok) {
          out.textContent = data.error || ("요청 실패: HTTP " + res.status);
        } else {
          out.textContent = data.answer || "";
        }
      } catch (err) {
        out.textContent = "요청 중 오류: " + String(err);
      } finally {
        const elapsed = ((Date.now() - started) / 1000).toFixed(2);
        meta.textContent = "응답 시간: " + elapsed + "초";
        askBtn.disabled = false;
      }
    }
    askBtn.addEventListener("click", ask);
    msg.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") ask();
    });
  </script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        request_path = parsed.path

        if request_path == "/" or request_path.startswith("/index.html"):
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if request_path.startswith("/api/health"):
            started_at = float(getattr(self.server, "started_at", time.time()))  # type: ignore[attr-defined]
            uptime = int(max(0.0, time.time() - started_at))
            return self._write_json(
                200,
                {
                    "ok": True,
                    "status": "ok",
                    "uptime_seconds": uptime,
                    "service": "web_ui",
                },
            )

        if request_path == "/oauth/google/callback":
            query_raw = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            query = {key: (values[-1] if values else "") for key, values in query_raw.items()}
            oauth_callback = getattr(self.server, "oauth_callback", None)  # type: ignore[attr-defined]
            if not callable(oauth_callback):
                result_payload = {"ok": False, "error": "oauth_callback is not configured"}
            else:
                try:
                    callback_result = oauth_callback(query)
                except Exception as exc:
                    callback_result = {"ok": False, "error": str(exc)}
                if isinstance(callback_result, dict):
                    result_payload = callback_result
                else:
                    result_payload = {"ok": False, "error": "oauth_callback must return dict payload"}

            ok = bool(result_payload.get("ok", False))
            title = "OAuth 연결 완료" if ok else "OAuth 연결 실패"
            detail = ""
            if ok:
                detail = str(result_payload.get("message", "")).strip() or "인증 코드 교환이 완료되었습니다."
            else:
                detail = str(result_payload.get("error", "")).strip() or "인증 코드 교환 중 오류가 발생했습니다."
            status_code = 200 if ok else 400
            body = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: "Pretendard", "Noto Sans KR", sans-serif; background: #f5f7fb; color: #101828; }}
    .wrap {{ max-width: 760px; margin: 40px auto; padding: 20px; }}
    .card {{ background: #fff; border-radius: 12px; box-shadow: 0 10px 30px rgba(16,24,40,.08); padding: 20px; }}
    h1 {{ margin: 0 0 12px; font-size: 24px; }}
    p {{ margin: 0 0 10px; line-height: 1.6; }}
    pre {{ white-space: pre-wrap; background: #0f172a; color: #e2e8f0; border-radius: 10px; padding: 12px; overflow: auto; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>{html.escape(title)}</h1>
      <p>{html.escape(detail)}</p>
      <p>이 창을 닫고 원래 앱으로 돌아가도 됩니다.</p>
      <pre>{html.escape(json.dumps(result_payload, ensure_ascii=False, indent=2))}</pre>
    </div>
  </div>
</body>
</html>
"""
            payload = body.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self._write_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/ask":
            self._write_json(404, {"ok": False, "error": "not_found"})
            return
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._write_json(400, {"ok": False, "error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            self._write_json(400, {"ok": False, "error": "invalid_payload"})
            return
        message = str(payload.get("message", "")).strip()
        if not message:
            self._write_json(400, {"ok": False, "error": "message is required"})
            return
        ask_callback = getattr(self.server, "ask_callback", None)  # type: ignore[attr-defined]
        if not callable(ask_callback):
            self._write_json(500, {"ok": False, "error": "ask_callback is not configured"})
            return
        try:
            answer = str(ask_callback(message))
        except Exception as exc:
            self._write_json(500, {"ok": False, "error": str(exc)})
            return
        self._write_json(200, {"ok": True, "answer": answer})


class WebUIServer:
    def __init__(
        self,
        ask_callback: Callable[[str], str],
        port: int = 8091,
        oauth_callback: Callable[[dict[str, str]], dict[str, Any]] | None = None,
    ) -> None:
        self.ask_callback = ask_callback
        requested_port = int(port)
        if requested_port < 0:
            requested_port = 0
        self.port = requested_port
        self._server = ThreadingHTTPServer(("127.0.0.1", requested_port), _Handler)
        self.port = int(self._server.server_port)
        self._server.ask_callback = ask_callback  # type: ignore[attr-defined]
        self._server.oauth_callback = oauth_callback  # type: ignore[attr-defined]
        self._server.started_at = time.time()  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="boramclaw-web-ui")
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


def start_web_ui_server(
    ask_callback: Callable[[str], str],
    port: int = 8091,
    oauth_callback: Callable[[dict[str, str]], dict[str, Any]] | None = None,
) -> WebUIServer:
    server = WebUIServer(ask_callback=ask_callback, port=port, oauth_callback=oauth_callback)
    server.start()
    return server
