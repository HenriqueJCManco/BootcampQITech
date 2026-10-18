from datetime import timedelta

from domain.entities import MARCADA, QUARENTENA, REFUND, REJECTED, RuleHit
from domain.facts import KNOWN, Facts
from domain.payer_class import MEI, PF, PJ


def e1_vault(facts: Facts) -> RuleHit | None:
    mcc = facts.destination.merchant_mcc
    if mcc is None or mcc not in facts.payer.blocked_mccs:
        return None
    return RuleHit("E1", evidence={"mcc": mcc}, eliminatory=True)


def e2_flagged_destination(facts: Facts, destination_status: str) -> RuleHit | None:
    if not facts.config.flag("ENABLE_BCB_587_RULES"):
        return None
    if destination_status != MARCADA or facts.pix.type == REFUND:
        return None
    return RuleHit("E2", evidence={"destination_status": MARCADA}, eliminatory=True)


def e3_quarantine(facts: Facts, destination_status: str, trusted_beneficiary: bool) -> RuleHit | None:
    if destination_status != QUARENTENA or trusted_beneficiary:
        return None
    return RuleHit("E3", evidence={"destination_status": QUARENTENA}, eliminatory=True)


def e4_night_limit(facts: Facts, payer_class: str) -> RuleHit | None:
    config = facts.config
    if payer_class == MEI and not config.flag("ENABLE_MEI_AS_PF"):
        payer_class = PJ
    if payer_class == PJ and not config.flag("APPLY_NIGHT_LIMIT_PJ"):
        return None
    if payer_class not in (PF, MEI, PJ):
        return None

    ceiling = config.params["teto_noturno_pf_centavos"]
    if not config.is_night(facts.now) or facts.pix.amount_cents <= ceiling:
        return None

    registration = timedelta(hours=config.eliminatory("E4")["pre_cadastro_horas"])
    if facts.completed_to_destination(before=facts.now - registration):
        return None

    return RuleHit(
        "E4",
        evidence={
            "amount_cents": facts.pix.amount_cents,
            "ceiling_cents": ceiling,
            "local_time": config.local_time(facts.now).strftime("%H:%M"),
            "payer_class": payer_class,
        },
        eliminatory=True,
    )


def e5_unknown_device(facts: Facts) -> RuleHit | None:
    stage = facts.device_stage
    if stage is None:
        facts.missing("source.device_id")
        return None
    if stage == KNOWN or facts.is_cold_start:
        return None

    params = facts.config.eliminatory("E5")
    day_start = facts.config.local_day_start(facts.now)
    day_sum = facts.pix.amount_cents + sum(
        pix.amount_cents
        for pix in facts.payer.history
        if pix.device_id == facts.pix.device_id
        and pix.status != REJECTED
        and day_start <= pix.transaction_date <= facts.now
    )
    evidence = {"device_stage": stage, "day_sum_cents": day_sum}

    if day_sum > params["limite_diario_centavos"]:
        evidence["daily_limit_cents"] = params["limite_diario_centavos"]
        return RuleHit("E5", evidence=evidence, eliminatory=True)

    if facts.pix.amount_cents > params["limite_por_pix_centavos"]:
        evidence["per_pix_limit_cents"] = params["limite_por_pix_centavos"]
        return RuleHit("E5", evidence=evidence, floor=True)

    return None
