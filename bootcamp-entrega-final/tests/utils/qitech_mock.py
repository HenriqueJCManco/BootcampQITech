import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
TRANSFER_PATH = re.compile(r"^/account/([^/]+)/pix_transfer$")
TOKEN_PATH = re.compile(r"^/account/([^/]+)/pix_transfer/([^/]+)/(validate_token|resend_token)$")
CREATED_AT = "2026-10-18T12:00:00.000Z"


class QiTechMock:
    """QI Tech BaaS falsa para testes: Pix com 2FA v2 em memória.

    Segue as regras da documentação: status pending_2fa_approval na criação,
    token de 6 caracteres, até 5 tentativas (depois rejected) e expiração.
    """

    def __init__(self) -> None:
        self.token = "AB12CD"
        self.approvers: set[str] | None = None
        self.unavailable = False
        self.completion_status = "sent"
        self.transfers: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self) -> "QiTechMock":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def expire(self, pix_transfer_key: str) -> None:
        self.transfers[pix_transfer_key]["expired"] = True

    def calls(self, action: str) -> list[dict]:
        return [request for request in self.requests if request["action"] == action]

    def _handler(self):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                return

            def _body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length)) if length else {}

            def _reply(self, status: int, body: dict | None = None) -> None:
                raw = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _handle(self) -> None:
                body = self._body()
                match = TRANSFER_PATH.match(self.path) or TOKEN_PATH.match(self.path)
                action = "pix_transfer" if match and match.re is TRANSFER_PATH else (match.group(3) if match else "?")
                mock.requests.append({"method": self.command, "action": action, "path": self.path,
                                      "headers": dict(self.headers), "body": body})
                if mock.unavailable:
                    return self._reply(503)
                if action == "pix_transfer" and self.command == "POST":
                    return self._reply(*mock._create(body))
                if action == "validate_token" and self.command == "PUT":
                    return self._reply(*mock._validate(match.group(2), body))
                if action == "resend_token" and self.command == "PATCH":
                    return self._reply(*mock._resend(match.group(2)))
                return self._reply(404, error("PXT000023", "Outgoing PIX Transfer Not Found"))

            do_POST = do_PUT = do_PATCH = _handle

        return Handler

    def _create(self, body: dict) -> tuple[int, dict]:
        tfa = body.get("tfa_info")
        if not tfa:
            return 400, error("PXT000169", "tfa_info is required")
        if not UUID_V4.match(body.get("request_control_key", "")):
            return 406, error("PXT000103", "request_control_key must be a valid uuid v4 string")
        if any(t["request_control_key"] == body["request_control_key"] for t in self.transfers.values()):
            return 400, error("PXT000109", "request_control_key already in use")
        if self.approvers is not None and tfa["approver_document_number"] not in self.approvers:
            return 400, error("PXT000168", "No approver permission")
        key = str(uuid.uuid4())
        self.transfers[key] = {
            "request_control_key": body["request_control_key"], "pix_transfer_key": key,
            "end_to_end_id": "E" + uuid.uuid4().hex[:31], "pix_transfer_status": "pending_2fa_approval",
            "attempts": 0, "expired": False, "body": body,
        }
        return 202, self._view(key)

    def _validate(self, key: str, body: dict) -> tuple[int, dict]:
        transfer = self.transfers.get(key)
        if transfer is None:
            return 404, error("PXT000023", "Outgoing PIX Transfer Not Found")
        if transfer["pix_transfer_status"] != "pending_2fa_approval":
            return 400, error("PXT000175", "Invalid Status")
        if transfer["expired"]:
            return 400, error("PXT000172", "Token Expired")
        if body.get("token") != self.token:
            transfer["attempts"] += 1
            if transfer["attempts"] >= 5:
                transfer["pix_transfer_status"] = "rejected"
                return 400, error("PXT000171", "Number of token validation attempts exceeded", self._view(key))
            return 400, error("PXT000173", "Incorrect Token")
        transfer["pix_transfer_status"] = self.completion_status
        return (201 if self.completion_status == "sent" else 202), self._view(key)

    def _resend(self, key: str) -> tuple[int, dict]:
        transfer = self.transfers.get(key)
        if transfer is None:
            return 404, error("PXT000023", "Outgoing PIX Transfer Not Found")
        if transfer["attempts"] >= 5:
            return 400, error("PXT000171", "Number of token validation attempts exceeded")
        if transfer["pix_transfer_status"] != "pending_2fa_approval":
            return 400, error("PXT000175", "Invalid Status")
        transfer["expired"] = False
        return 202, self._view(key)

    def _view(self, key: str) -> dict:
        transfer = self.transfers[key]
        return {
            "request_control_key": transfer["request_control_key"], "pix_transfer_key": key,
            "end_to_end_id": transfer["end_to_end_id"], "pix_transfer_status": transfer["pix_transfer_status"],
            "created_at": CREATED_AT,
        }


def error(code: str, title: str, transfer: dict | None = None) -> dict:
    return {
        "title": title, "description": title, "translation": title, "code": code,
        "extra_fields": {"pix_transfer_data": transfer} if transfer else {},
    }
