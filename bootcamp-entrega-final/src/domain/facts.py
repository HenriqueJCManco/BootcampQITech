from datetime import datetime, timedelta

from domain.config import EngineConfig
from domain.entities import APPROVED, REJECTED, EvaluationContext, PastPix
from domain.statistics import median, percentile


UNKNOWN = "unknown"
MATURING = "maturing"
KNOWN = "known"


class Facts:
    def __init__(self, context: EvaluationContext, config: EngineConfig) -> None:
        self.context = context
        self.config = config
        self.pix = context.pix
        self.payer = context.payer
        self.destination = context.destination
        self.now: datetime = context.pix.transaction_date
        self.inputs_missing: list[str] = []

    def missing(self, field: str) -> None:
        if field not in self.inputs_missing:
            self.inputs_missing.append(field)

    def history_since(self, delta: timedelta) -> list[PastPix]:
        start = self.now - delta
        return [pix for pix in self.payer.history if start <= pix.transaction_date <= self.now]

    def live_history_since(self, delta: timedelta) -> list[PastPix]:
        return [pix for pix in self.history_since(delta) if pix.status != REJECTED]

    @property
    def is_cold_start(self) -> bool:
        return not self.payer.history and not self.payer.amount_history

    def completed_to_destination(self, before: datetime | None = None) -> list[PastPix]:
        limit = before or self.now
        return [
            pix
            for pix in self.payer.history
            if pix.destination_key == self.destination.destination_key
            and pix.completed
            and pix.status == APPROVED
            and pix.transaction_date < limit
        ]

    @property
    def is_new_destination(self) -> bool:
        return not self.completed_to_destination()

    def is_new_destination_at(self, destination_key: str, moment: datetime) -> bool:
        return not any(
            pix.destination_key == destination_key
            and pix.completed
            and pix.status == APPROVED
            and pix.transaction_date < moment
            for pix in self.payer.history
        )

    @property
    def device_stage(self) -> str | None:
        if self.pix.device_id is None:
            return None
        first_seen = self.context.device.first_seen
        if first_seen is None or first_seen > self.now:
            return UNKNOWN
        maturation = timedelta(hours=self.config.rule("D1")["maturacao_horas"])
        if self.now - first_seen < maturation:
            return MATURING
        return KNOWN

    def p1_threshold(self) -> tuple[float, int, float | None]:
        params = self.config.p95
        window = timedelta(days=params["janela_dias"])
        amounts = [
            movement.amount_cents
            for movement in self.payer.amount_history
            if self.now - window <= movement.occurred_at <= self.now
        ]
        floor = params["piso_centavos"]
        if len(amounts) < params["min_observacoes"]:
            return float(floor), len(amounts), None
        p95 = percentile(amounts, params["percentil"])
        return max(p95, float(floor)), len(amounts), p95

    def trusted_beneficiary(self) -> tuple[bool, dict]:
        params = self.config.rule("H2")
        pair = self.completed_to_destination()
        months = {(pix.transaction_date.year, pix.transaction_date.month) for pix in pair}
        recent_months = self._last_calendar_months(params["janela_meses"])
        months_in_window = months & recent_months
        if len(pair) < params["min_pix"] or len(months_in_window) < params["meses_distintos"]:
            return False, {}

        pair_median = median([pix.amount_cents for pix in pair])
        tolerance = params["tolerancia"]
        within = abs(self.pix.amount_cents - pair_median) <= pair_median * tolerance
        return within, {"pair_pix": len(pair), "distinct_months": len(months_in_window)}

    def _last_calendar_months(self, count: int) -> set[tuple[int, int]]:
        year, month = self.now.year, self.now.month
        months = set()
        for _ in range(count + 1):
            months.add((year, month))
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        return months
