import os
from dataclasses import dataclass, field
from datetime import datetime

import requests

from connectors.rest_connector import RestConnector


PENDING_2FA_APPROVAL = "pending_2fa_approval"
SENT = "sent"
PENDING = "pending"
REJECTED = "rejected"

TOKEN_TTL_MINUTES = 5
MAX_TOKEN_ATTEMPTS = 5


@dataclass(frozen=True)
class QiPixTransfer:
    request_control_key: str
    pix_transfer_key: str
    status: str
    end_to_end_id: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_json(cls, body: dict) -> "QiPixTransfer":
        created_at = body.get("created_at")
        return cls(
            request_control_key=body["request_control_key"],
            pix_transfer_key=body["pix_transfer_key"],
            status=body["pix_transfer_status"],
            end_to_end_id=body.get("end_to_end_id"),
            created_at=datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else None,
        )


@dataclass
class QiTechError(Exception):
    http_status: int
    code: str
    title: str = ""
    description: str = ""
    translation: str = ""
    transfer: QiPixTransfer | None = field(default=None)

    def __str__(self) -> str:
        return f"QI Tech {self.http_status} {self.code}: {self.description}"


class QiTechUnavailable(Exception):
    pass


class QITechConnector(RestConnector):
    """Pix com Autenticação de Dois Fatores (2FA v2) da QI Tech BaaS.

    O token de 6 caracteres vai por SMS ou e-mail ao aprovador indicado em
    tfa_info, vale 5 minutos e aceita até 5 tentativas antes de a QI
    rejeitar a transferência.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float | None = None) -> None:
        super().__init__(
            self.__class__.__name__,
            base_url or os.environ.get("QITECH_API_URL", "http://127.0.0.1:9100"),
            timeout or float(os.environ.get("QITECH_TIMEOUT_S", "8")),
            internal_token="",
        )
        self.api_key = api_key or os.environ.get("QITECH_API_CLIENT_KEY", "")

    def request_pix_transfer_2fa(
        self,
        account_key: str,
        request_control_key: str,
        amount_cents: int,
        transfer: dict,
        approver_document_number: str,
        contact_type: str,
    ) -> QiPixTransfer:
        payload = {
            **transfer,
            "request_control_key": request_control_key,
            "transaction_amount": cents_to_reais(amount_cents),
            "tfa_info": {"approver_document_number": approver_document_number, "contact_type": contact_type},
        }
        return self._call("POST", f"/account/{account_key}/pix_transfer", payload)

    def validate_token(self, account_key: str, pix_transfer_key: str, token: str) -> QiPixTransfer:
        return self._call(
            "PUT", f"/account/{account_key}/pix_transfer/{pix_transfer_key}/validate_token", {"token": token}
        )

    def resend_token(self, account_key: str, pix_transfer_key: str) -> QiPixTransfer:
        return self._call("PATCH", f"/account/{account_key}/pix_transfer/{pix_transfer_key}/resend_token")

    def _call(self, method: str, endpoint: str, payload: dict | None = None) -> QiPixTransfer:
        headers = {"API-CLIENT-KEY": self.api_key} if self.api_key else {}
        try:
            response = self.send(endpoint, method, payload, headers)
        except requests.RequestException as error:
            raise QiTechUnavailable(str(error)) from error

        body = response.json or {}
        if response.status in (200, 201, 202):
            return QiPixTransfer.from_json(body)
        if response.status >= 500 or response.status == 408 or not body.get("code"):
            raise QiTechUnavailable(f"QI Tech respondeu {response.status}")

        transfer_data = (body.get("extra_fields") or {}).get("pix_transfer_data")
        raise QiTechError(
            http_status=response.status,
            code=body["code"],
            title=body.get("title", ""),
            description=body.get("description", ""),
            translation=body.get("translation", ""),
            transfer=QiPixTransfer.from_json(transfer_data) if transfer_data else None,
        )


def cents_to_reais(amount_cents: int) -> float:
    return float(f"{amount_cents // 100}.{amount_cents % 100:02d}")
