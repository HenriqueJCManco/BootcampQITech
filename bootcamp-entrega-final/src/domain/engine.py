from domain.rules import channel, eliminatory, scoring
from domain.config import EngineConfig
from domain.entities import (
    APPROVED,
    BIOMETRIC_2FA,
    MARCADA,
    QUARENTENA,
    REJECTED,
    TRUSTED_CONTACT_APPROVAL,
    TWO_FACTOR_REQUIRED,
    Decision,
    EvaluationContext,
    RuleHit,
)
from domain.facts import Facts
from domain.payer_class import classify_payer
from domain.reputation import plan_transition


CALL_COACHING_CHECK = "CALL_COACHING_CHECK"
MULE_DESTINATION_CHECK = "MULE_DESTINATION_CHECK"
PASSTHROUGH_CHECK = "PASSTHROUGH_CHECK"
CONFIRM_IDENTITY = "CONFIRM_IDENTITY"
BLOCKED_FOR_SAFETY = "BLOCKED_FOR_SAFETY"

FRICTION_SCRIPTS = {
    "R1": CALL_COACHING_CHECK,
    "F3": PASSTHROUGH_CHECK,
    "C6": MULE_DESTINATION_CHECK,
    "C5": MULE_DESTINATION_CHECK,
}


def evaluate(context: EvaluationContext, config: EngineConfig) -> Decision:
    facts = Facts(context, config)
    pix = context.pix

    payer_class, class_evidence = classify_payer(pix.source_document, pix.source_name, config)
    if class_evidence.get("reason") == "name_missing":
        facts.missing("source_account.owner.name")
    if pix.has_trusted_contact is None:
        facts.missing("source_account.has_trusted_contact")

    _, _, payer_p95 = facts.p1_threshold()
    destination_status, flag_changes = plan_transition(
        context.destination, pix.amount_cents, payer_p95, facts.now, config
    )
    trusted, trusted_evidence = facts.trusted_beneficiary()

    band = config.band_for(pix.amount_cents)
    thresholds = {"two_factor": band["dois_fatores"], "reject": band["reprova"]}

    eliminatory_hits = [
        hit
        for hit in (
            eliminatory.e1_vault(facts),
            eliminatory.e6_bets_ban(facts),
            eliminatory.e2_flagged_destination(facts, destination_status),
            eliminatory.e3_quarantine(facts, destination_status, trusted),
            eliminatory.e4_night_limit(facts, payer_class),
            eliminatory.e5_unknown_device(facts),
        )
        if hit is not None
    ]

    decision = Decision(
        status=APPROVED,
        score=0,
        value_band=band["faixa"],
        thresholds=thresholds,
        engine_version=config.version,
        payer_class=payer_class,
        destination_status=destination_status,
        flag_changes=flag_changes,
    )

    blocking = [hit for hit in eliminatory_hits if hit.eliminatory]
    if blocking:
        decision.status = decide(0, band, [], blocked=True)
        decision.rules_fired = blocking
    else:
        hits = eliminatory_hits + _score_hits(facts, destination_status, trusted, trusted_evidence)
        hits, escalated_status = channel.r2_escalation(hits, config)
        decision.rules_fired = hits
        decision.score, decision.family_caps_applied = capped_score(hits, config)
        decision.floor_applied = _floors(hits, band["faixa"], config)
        decision.status = decide(decision.score, band, decision.floor_applied)

        if escalated_status == REJECTED or (escalated_status and decision.status == APPROVED):
            decision.status = escalated_status

    decision.inputs_missing = facts.inputs_missing
    _finish(decision, context, config)
    return decision


def _score_hits(facts: Facts, destination_status: str, trusted: bool, trusted_evidence: dict) -> list[RuleHit]:
    c1 = scoring.c1_new_beneficiary(facts)
    c8 = scoring.c8_test_and_drain(facts)
    hits = [
        scoring.d3_cold_start(facts),
        scoring.d1_device_stage(facts),
        scoring.d2_shared_device(facts),
        scoring.g1_distance_from_usual(facts),
        scoring.g2_impossible_travel(facts),
        channel.g4_missing_geolocation(facts),
        channel.k1_unusual_channel(facts),
        channel.k2_watch(facts),
        c1,
        scoring.c2_destination_age(facts),
        scoring.c5_many_payers(facts),
        scoring.c6_fast_forward(facts),
        scoring.c7_endogenous_reputation(facts),
        c8,
        scoring.p1_amount_outlier(facts),
        scoring.p2_unusual_hour(facts),
        scoring.m1_accumulated(facts),
        scoring.m2_splitting(facts),
        scoring.v1_burst(facts),
        scoring.v2_new_destinations(facts),
        scoring.o1_new_source_account(facts),
        channel.r1_remote_or_call(facts),
        channel.r2_desktop_automation(facts),
        scoring.f1_amount_vs_income(facts),
        scoring.f2_balance_drain(facts),
        scoring.f3_pass_through(facts, c1 is not None),
    ]

    h2_allowed = trusted and destination_status not in (MARCADA, QUARENTENA) and c8 is None
    hits.append(scoring.h2_trusted_beneficiary(facts, h2_allowed, trusted_evidence))
    return [hit for hit in hits if hit is not None]


def decide(score: int, band: dict, floors: list[str], blocked: bool = False) -> str:
    if blocked or score >= band["reprova"]:
        return REJECTED
    if score >= band["dois_fatores"] or floors:
        return TWO_FACTOR_REQUIRED
    return APPROVED


def capped_score(hits: list[RuleHit], config: EngineConfig) -> tuple[int, dict]:
    families = config.params.get("familias", {})
    if not config.flag("ENABLE_FAMILY_CAPS") or not families:
        return max(0, sum(hit.points for hit in hits)), {}

    family_of = {code: name for name, family in families.items() for code in family["regras"]}
    positive_by_family: dict[str, int] = {}
    uncapped = 0
    for hit in hits:
        family = family_of.get(hit.code)
        if family is None or hit.points <= 0:
            uncapped += hit.points
        else:
            positive_by_family[family] = positive_by_family.get(family, 0) + hit.points

    applied = {}
    total = uncapped
    for family, points in positive_by_family.items():
        ceiling = families[family]["teto"]
        if points > ceiling:
            applied[family] = {"raw": points, "cap": ceiling}
        total += min(points, ceiling)
    return max(0, total), applied


def _floors(hits: list[RuleHit], value_band: str, config: EngineConfig) -> list[str]:
    floors = [hit.code for hit in hits if hit.floor]

    x1 = config.floor("X1")
    weak = [
        hit.code
        for hit in hits
        if x1.get("pontos_min_sinal_fraco", 1) <= hit.points < x1["pontos_max_sinal_fraco"]
    ]
    if len(weak) >= x1["min_sinais"]:
        floors.append("X1")

    codes = {hit.code for hit in hits}
    if value_band == config.floor("X2")["faixa"] and "C1" in codes:
        floors.append("X2")

    return floors


def _finish(decision: Decision, context: EvaluationContext, config: EngineConfig) -> None:
    has_contact = bool(context.pix.has_trusted_contact)
    decision.notify_trusted_contact = has_contact and decision.status in (TWO_FACTOR_REQUIRED, REJECTED)

    if decision.status == REJECTED:
        decision.customer_message_key = BLOCKED_FOR_SAFETY
        return
    if decision.status != TWO_FACTOR_REQUIRED:
        return

    codes = {hit.code for hit in decision.rules_fired}
    social = config.params["social_2fa"]
    coercion = all(code in codes for code in social["sinais"]) and bool(context.pix.call_in_progress)
    consent_ok = context.payer.has_consented_trusted_contact or not social["exige_consentimento_contato"]
    if coercion and has_contact and consent_ok:
        decision.challenge_type = TRUSTED_CONTACT_APPROVAL
    else:
        decision.challenge_type = BIOMETRIC_2FA

    decision.friction_script_key = CONFIRM_IDENTITY
    for code in config.params["friction"]["precedencia"]:
        if code in codes:
            decision.friction_script_key = FRICTION_SCRIPTS[code]
            break
    if decision.friction_script_key == MULE_DESTINATION_CHECK:
        decision.friction_params = {"payers_24h_band": "SEVERAL"}

    decision.customer_message_key = CONFIRM_IDENTITY


def apply_second_factor(
    original_status: str,
    friction_script_key: str | None,
    friction_answer: str | None,
    has_consented_contact: bool,
    config: EngineConfig,
) -> tuple[str, str | None]:
    if original_status != TWO_FACTOR_REQUIRED:
        return original_status, None

    if friction_script_key == CALL_COACHING_CHECK and friction_answer == "YES":
        if has_consented_contact:
            return TWO_FACTOR_REQUIRED, TRUSTED_CONTACT_APPROVAL
        return config.params["friction"]["resposta_sim_sem_contato"], None

    return APPROVED, None
