from dataclasses import dataclass
from datetime import datetime, time, tzinfo


@dataclass(frozen=True)
class EngineConfig:
    version: int
    params: dict

    def rule(self, code: str) -> dict:
        return self.params["regras"][code]

    def eliminatory(self, code: str) -> dict:
        return self.params["eliminatorias"][code]

    def floor(self, code: str) -> dict:
        return self.params["pisos"][code]

    def flag(self, name: str) -> bool:
        return bool(self.params["flags"].get(name, False))

    @property
    def reputation(self) -> dict:
        return self.params["reputacao"]

    @property
    def p95(self) -> dict:
        return self.params["percentil_95_valor"]

    def band_for(self, amount_cents: int) -> dict:
        for band in self.params["faixas"]:
            if band["ate_centavos"] is None or amount_cents <= band["ate_centavos"]:
                return band
        raise ValueError("engine_config.faixas must end with an open band.")

    def rule_timezone(self) -> tzinfo | None:
        name = self.params.get("timezone_regra")
        if not name:
            return None
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:
            return None

    def local_time(self, moment: datetime) -> datetime:
        zone = self.rule_timezone()
        if zone is None:
            return moment
        return moment.astimezone(zone)

    def is_night(self, moment: datetime) -> bool:
        start = _parse_time(self.params["janela_noite_inicio"])
        end = _parse_time(self.params["janela_noite_fim"])
        current = self.local_time(moment).time()
        if start <= end:
            return start <= current < end
        return current >= start or current < end

    def local_day_start(self, moment: datetime) -> datetime:
        local = self.local_time(moment)
        return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
