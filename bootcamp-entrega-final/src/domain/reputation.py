from datetime import datetime, timedelta

from domain.config import EngineConfig
from domain.entities import (
    MARCADA,
    NORMAL,
    OBSERVACAO,
    QUARENTENA,
    DestinationSnapshot,
    FlagChange,
)
from domain.identity import only_digits


STATUS_PRECEDENCE = (MARCADA, QUARENTENA, OBSERVACAO)


def current_status(destination: DestinationSnapshot, at: datetime) -> str:
    active = {flag.status for flag in destination.flags if flag.is_active(at)}
    for status in STATUS_PRECEDENCE:
        if status in active:
            return status
    return NORMAL


def observation_triggers(
    destination: DestinationSnapshot,
    amount_cents: int,
    payer_p95: float | None,
    at: datetime,
    config: EngineConfig,
) -> list[str]:
    params = config.reputation
    reasons = []

    if destination.account_created_at is not None:
        age = at - destination.account_created_at
        if age < timedelta(days=params["observacao_conta_dias"]):
            reasons.append("new_account")
        elif len(only_digits(destination.document)) == 14 and age < timedelta(days=params["observacao_pj_dias"]):
            reasons.append("new_pj_account")

    if amount_cents >= params["exorbitante_centavos"]:
        reasons.append("exorbitant_amount")
    elif payer_p95 is not None:
        limit = max(payer_p95 * params["exorbitante_multiplicador_p95"], params["exorbitante_piso_centavos"])
        if amount_cents >= limit:
            reasons.append("exorbitant_for_payer")

    return reasons


def quarantine_signals(destination: DestinationSnapshot, config: EngineConfig) -> list[str]:
    params = config.reputation
    reputation = destination.reputation
    signals = []

    if reputation.payers_24h >= params["quarentena_min_pagadores"]:
        signals.append("C5")
    if reputation.forwarded_ratio_1h >= config.rule("C6")["proporcao_min"]:
        signals.append("C6")
    if (
        reputation.analyses_count >= config.rule("C7")["min_analises"]
        and reputation.suspicious_ratio >= params["quarentena_min_proporcao_c7"]
    ):
        signals.append("C7")
    return signals


def plan_transition(
    destination: DestinationSnapshot,
    amount_cents: int,
    payer_p95: float | None,
    at: datetime,
    config: EngineConfig,
) -> tuple[str, list[FlagChange]]:
    status = current_status(destination, at)
    if status in (MARCADA, QUARENTENA):
        return status, []

    params = config.reputation
    observation_window = timedelta(days=params["observacao_saida_dias"])
    triggers = observation_triggers(destination, amount_cents, payer_p95, at, config)
    changes = []

    if triggers:
        changes.append(FlagChange(OBSERVACAO, ",".join(triggers), at, at + observation_window))
        status = OBSERVACAO

    if status != OBSERVACAO:
        return status, changes

    signals = quarantine_signals(destination, config)
    if signals:
        quarantine_end = at + timedelta(hours=params["quarentena_horas"])
        changes.append(FlagChange(QUARENTENA, ",".join(signals), at, quarantine_end))
        changes.append(FlagChange(OBSERVACAO, "after_quarantine", at, quarantine_end + observation_window))
        status = QUARENTENA

    return status, changes
