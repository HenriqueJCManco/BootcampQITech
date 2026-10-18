import os

from connectors.rest_connector import RestConnector
from constants import INTERNAL_TOKEN


class QITechConnector(RestConnector):
    """Conector com a camada terceirizada da QI Tech (2FA e biometria).
    Configurado com timeout rigoroso de 300 ms conforme especificado na RFC.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 0.3) -> None:
        url = base_url or os.environ.get("QITECH_API_URL", "http://127.0.0.1:3000")
        token = os.environ.get("QITECH_INTERNAL_TOKEN", INTERNAL_TOKEN or "default_token")
        super().__init__(self.__class__.__name__, url, timeout, token)

    def verify_second_factor_proof(self, proof: str, challenge_ref: str | None = None) -> bool:
        try:
            resp = self.send(
                endpoint="/v1/challenges/verify",
                method="POST",
                payload={"proof": proof, "challenge_ref": challenge_ref},
            )
            return resp.status == 200
        except Exception as ex:
            self.logger.warning(f"QI Tech verification timeout/error: {ex}")
            return False


class OpenFinanceConnector(RestConnector):
    """Conector com os serviços de Open Finance.
    Configurado com timeout rigoroso para não prender a esteira de análise.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 0.3) -> None:
        url = base_url or os.environ.get("OPENFINANCE_API_URL", "http://127.0.0.1:3000")
        token = os.environ.get("OPENFINANCE_INTERNAL_TOKEN", INTERNAL_TOKEN or "default_token")
        super().__init__(self.__class__.__name__, url, timeout, token)

    def fetch_payer_profile(self, document_number: str) -> dict | None:
        try:
            resp = self.send(
                endpoint=f"/v1/customers/{document_number}/profile",
                method="GET",
            )
            if resp.status == 200 and resp.json:
                return resp.json
        except Exception as ex:
            self.logger.warning(f"Open Finance fetch timeout/error: {ex}")
        return None
