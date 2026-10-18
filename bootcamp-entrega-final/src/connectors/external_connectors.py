import os

from connectors.rest_connector import RestConnector
from constants import INTERNAL_TOKEN


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
