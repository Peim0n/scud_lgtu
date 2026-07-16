"""
HTTP API для тестирования и удалённого управления СКУД.

Запускается отдельным потоком внутри AccessController.
Предоставляет endpoints для:
- проверки состояния
- просмотра локального кэша
- добавления/удаления идентификаторов
- генерации тестовых QR
- отправки команд (открыть турникет, записать shift)
"""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional

from .events import ScudCommand, CommandTarget, CommandAction
from .qr_encoder import encode_qr

logger = logging.getLogger(__name__)


class ApiHandler(BaseHTTPRequestHandler):
    """Обработчик HTTP-запросов тестового API."""

    controller: Any = None

    def _send_json(self, data: Any, status: int = 200) -> None:
        """Отправить JSON-ответ клиенту."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def _read_json(self) -> dict:
        """Прочитать и распарсить JSON из тела POST-запроса."""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body) if body else {}

    def do_GET(self) -> None:  # noqa: N802
        """Обработчик GET-запросов."""
        if self.path == "/health":
            self._send_json({
                "healthy": self.controller._engine.is_healthy(),
                "running": self.controller._running.is_set(),
            })

        elif self.path == "/cache":
            cache = self.controller._cache
            self._send_json({
                "users": {str(k): v for k, v in cache._users.items()},
                "allowed": {k: list(v) for k, v in cache._allowed.items()},
            })

        elif self.path == "/events":
            store = self.controller._store
            self._send_json({
                "count": len(store._events),
                "events": [
                    {
                        "event_id": e.event_id,
                        "token_type": e.token_type,
                        "token": e.token,
                        "result": e.result,
                        "description": e.description,
                    }
                    for e in store._events[-20:]
                ],
            })

        elif self.path == "/mux/state":
            self._send_json({
                "mux_state": self.controller._engine.get_mux_state(),
            })

        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        """Обработчик POST-запросов."""
        body = self._read_json()

        if self.path == "/cache/add":
            id_type = body.get("type", "maxid")
            token = body.get("token", "")
            user_id = body.get("user_id")
            self.controller._cache.add(id_type, token, user_id=user_id)
            self._send_json({"ok": True, "type": id_type, "token": token, "user_id": user_id})

        elif self.path == "/cache/remove":
            id_type = body.get("type", "maxid")
            token = body.get("token", "")
            self.controller._cache._allowed.setdefault(id_type, set()).discard(
                self.controller._cache._hash(id_type, token)
            )
            self._send_json({"ok": True})

        elif self.path == "/qr/generate":
            max_id = int(body.get("max_id", 12345))
            key_id = int(body.get("key_id", 0))
            timestamp = int(body.get("timestamp")) if "timestamp" in body else None
            if timestamp is None:
                import time as _time
                timestamp = int(_time.time())
            keys_dir = body.get("keys_dir", "key")
            private_path = os.path.join(keys_dir, f"private_key.{key_id}")
            shared_path = os.path.join(keys_dir, f"shared_key.{key_id}")
            if not os.path.exists(private_path) or not os.path.exists(shared_path):
                self._send_json({"error": f"Keys not found for key_id {key_id}"}, 404)
                return
            with open(private_path, "rb") as f:
                private_key_pem = f.read()
            with open(shared_path, "rb") as f:
                shared_key_raw = f.read()
            url = encode_qr(key_id, timestamp, max_id, private_key_pem, shared_key_raw)
            self._send_json({"url": url, "max_id": max_id, "key_id": key_id, "timestamp": timestamp})

        elif self.path == "/command/open":
            self.controller._open_turnstile()
            self._send_json({"ok": True, "command": "open"})

        elif self.path == "/command/shift":
            value = body.get("value", 0)
            self.controller._engine.send_command(
                ScudCommand(
                    target=CommandTarget.SHIFT,
                    action=CommandAction.WRITE_SHIFT,
                    payload={"value": int(value)},
                )
            )
            self._send_json({"ok": True, "command": "shift", "value": value})

        else:
            self._send_json({"error": "Not found"}, 404)

    def log_message(self, format: str, *args: Any) -> None:
        """Перенаправить логи HTTP-запросов в debug-логгер."""
        logger.debug("API %s", format % args)


class ApiServer:
    """Тестовый HTTP-сервер для внешнего управления."""

    def __init__(self, controller: Any, host: str = "0.0.0.0", port: int = 8080):
        """Создать HTTP API для переданного контроллера."""
        self._controller = controller
        self._host = host
        self._port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Запустить HTTP-сервер в фоновом потоке."""
        ApiHandler.controller = self._controller
        self._server = HTTPServer((self._host, self._port), ApiHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="ApiServer", daemon=True)
        self._thread.start()
        logger.info("HTTP API запущен на http://%s:%d", self._host, self._port)

    def stop(self) -> None:
        """Остановить HTTP-сервер и дождаться завершения потока."""
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        logger.info("HTTP API остановлен")
