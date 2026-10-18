from datetime import datetime
from typing import Any, Protocol

from domain.entities import Decision, DestinationSnapshot, DeviceSnapshot, EvaluationContext, PayerSnapshot


class FraudAnalysisRepository(Protocol):
    def reserve_analysis(self, **fields) -> tuple[Any, bool]:
        ...

    def lock_payer(self, source_hash: str) -> None:
        ...

    def load_payer_snapshot(
        self, source_hash: str, account: Any, at: datetime, exclude_pix_id: str
    ) -> PayerSnapshot:
        ...

    def load_destination_snapshot(
        self, destination_key: str, document: str, account: Any, at: datetime
    ) -> DestinationSnapshot:
        ...

    def load_device_snapshot(self, device_id: str | None, source_hash: str, at: datetime) -> DeviceSnapshot:
        ...

    def persist_analysis(
        self,
        analysis: Any,
        decision: Decision,
        context: EvaluationContext,
        source_account_id: int | None,
        destination_account_id: int | None,
    ) -> None:
        ...
