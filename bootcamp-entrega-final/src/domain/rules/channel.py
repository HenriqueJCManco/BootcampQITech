from dataclasses import replace
from datetime import timedelta

from domain.config import EngineConfig
from domain.entities import RuleHit
from domain.facts import Facts


MOBILE = "mobile"
DESKTOP = "desktop"


def segment_of(channel: str | None, config: EngineConfig) -> str | None:
    for segment, channels in config.params["segmentos_canal"].items():
        if channel in channels:
            return segment
    return None


def g4_missing_geolocation(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("G4")
    if facts.pix.geolocation is not None or facts.pix.channel not in params["canais"]:
        return None
    facts.missing("geolocation")
    evidence = {"channel": facts.pix.channel, "segment": segment_of(facts.pix.channel, facts.config)}
    return RuleHit("G4", params["pontos"], evidence)


def k1_unusual_channel(facts: Facts) -> RuleHit | None:
    channel = facts.pix.channel
    if channel is None:
        facts.missing("source.channel")
        return None
    params = facts.config.rule("K1")
    past = [pix for pix in facts.history_since(timedelta(days=params["janela_dias"])) if pix.channel is not None]
    if len(past) < params["min_transacoes"]:
        return None

    segment = segment_of(channel, facts.config)
    share = sum(1 for pix in past if segment_of(pix.channel, facts.config) == segment) / len(past)
    if share >= params["proporcao_max"]:
        return None
    return RuleHit("K1", params["pontos"], {"channel": channel, "segment": segment, "share": round(share, 3)})


def k2_watch(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("K2")
    if facts.pix.channel != params["canal"] or facts.pix.amount_cents <= params["acima_centavos"]:
        return None
    return RuleHit("K2", 0, {"channel": facts.pix.channel}, floor=True)


def r1_remote_or_call(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("R1")
    points = 0
    evidence = {"channel": facts.pix.channel}
    if facts.pix.remote_access_detected is None:
        facts.missing("source.remote_access_detected")
    elif facts.pix.remote_access_detected:
        points += params["pontos_acesso_remoto"]
        evidence["remote_access_detected"] = True
    if facts.pix.call_in_progress is None:
        facts.missing("source.call_in_progress")
    elif facts.pix.call_in_progress:
        points += params["pontos_ligacao"]
        evidence["call_in_progress"] = True
    if points == 0:
        return None
    return RuleHit("R1", points, evidence, floor=True)


def r2_desktop_automation(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("R2")
    if facts.pix.channel not in params["canais"]:
        return None
    interaction = facts.pix.interaction
    if interaction is None:
        facts.missing("source.interaction")
        return None

    signals = []
    if interaction.is_robotic_movement:
        signals.append("is_robotic_movement")
    cadence = interaction.typing_cadence_std_ms
    if cadence is not None and cadence <= params["cadencia_digitacao_max_std_ms"]:
        signals.append("typing_cadence_std_ms")
    if interaction.session_idle_then_burst:
        signals.append("session_idle_then_burst")
    if len(signals) < params["min_sinais"]:
        return None

    evidence = {"channel": facts.pix.channel, "signals": signals, "interaction": interaction.raw}
    return RuleHit("R2", params["pontos"], evidence, floor=True)


def r2_escalation(hits: list[RuleHit], config: EngineConfig) -> tuple[list[RuleHit], str | None]:
    params = config.rule("R2")
    codes = {hit.code for hit in hits}
    if "R2" not in codes:
        return hits, None
    combined = [code for code in params["escalar_com"] if code in codes]
    if not combined:
        return hits, None

    escalated = [
        replace(hit, evidence={**hit.evidence, "escalated_with": combined}) if hit.code == "R2" else hit
        for hit in hits
    ]
    return escalated, params["escalar_para"]
