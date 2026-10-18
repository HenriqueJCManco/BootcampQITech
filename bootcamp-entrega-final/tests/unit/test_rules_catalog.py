from dataclasses import replace
from datetime import timedelta

import pytest

from domain import (
    APPROVED,
    REJECTED,
    TWO_FACTOR_REQUIRED,
    DestinationFlag,
    DestinationReputation,
    DeviceSnapshot,
    EngineConfig,
    Geolocation,
    MoneyMovement,
    OpenFinanceProfile,
    PastPix,
    RuleHit,
    evaluate,
)
from domain.entities import MARCADA, OBSERVACAO, QUARENTENA
from domain.facts import Facts
from domain.identity import destination_key, document_hash, mask_document, only_digits
from domain.payer_class import PJ, classify_payer
from domain.reputation import observation_triggers, plan_transition, quarantine_signals
from domain.rules import channel, eliminatory, scoring
from domain.statistics import percentile
from test_fraud_engine import DESTINATION_KEY, DEVICE, OTHER_KEY, at, build_context


HOME = Geolocation(-23.55, -46.63)
CAMPINAS_150KM = Geolocation(-22.10, -46.63)
BRASILIA_600KM = Geolocation(-18.00, -46.63)
PJ_DOCUMENT = "11222333000181"


def codes(decision) -> set[str]:
    return {hit.code for hit in decision.rules_fired}


def hit_for(decision, code: str) -> RuleHit | None:
    return next((hit for hit in decision.rules_fired if hit.code == code), None)


def known_destination_history(now, amount_cents: int = 8000):
    return tuple(
        PastPix(
            transaction_date=now - timedelta(days=3 + index * 4, hours=index % 3),
            amount_cents=amount_cents,
            destination_key=DESTINATION_KEY if index % 2 == 0 else OTHER_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
            geolocation=HOME,
        )
        for index in range(12)
    )


def routine_without_current_dest(now, amount_cents: int = 8000):
    return tuple(replace(pix, destination_key=OTHER_KEY) for pix in known_destination_history(now, amount_cents))


def make_context(now, amount_cents: int, **overrides):
    payer_overrides = overrides.pop("payer", {})
    destination_overrides = overrides.pop("destination", {})
    ctx = build_context(now, amount_cents, **overrides)
    if payer_overrides:
        ctx = replace(ctx, payer=replace(ctx.payer, **payer_overrides))
    if destination_overrides:
        ctx = replace(ctx, destination=replace(ctx.destination, **destination_overrides))
    return ctx


def with_flag(config: EngineConfig, name: str, value: bool) -> EngineConfig:
    params = {**config.params, "flags": {**config.params["flags"], name: value}}
    return EngineConfig(version=config.version, params=params)


def test_e1_vault_rejects_blocked_mcc_and_allows_unblocked(engine_config):
    now = at(17, 14)
    blocked_ctx = make_context(
        now,
        5000,
        payer={"blocked_mccs": frozenset({"7995"})},
        destination={"merchant_mcc": "7995"},
    )
    allowed_ctx = make_context(
        now,
        5000,
        payer={"blocked_mccs": frozenset({"7995"})},
        destination={"merchant_mcc": "5411"},
    )

    blocked_decision = evaluate(blocked_ctx, engine_config)
    allowed_decision = evaluate(allowed_ctx, engine_config)

    assert blocked_decision.status == REJECTED
    assert codes(blocked_decision) == {"E1"}
    assert blocked_decision.rules_fired[0].evidence == {"mcc": "7995"}
    assert "E1" not in codes(allowed_decision)


def test_e2_respects_bcb_587_feature_flag(engine_config):
    now = at(17, 14)
    flag = DestinationFlag(MARCADA, now - timedelta(days=2), now + timedelta(days=30))
    context = make_context(now, 5000, destination={"flags": (flag,)})

    disabled_config = with_flag(engine_config, "ENABLE_BCB_587_RULES", False)
    decision = evaluate(context, disabled_config)

    assert "E2" not in codes(decision)


def test_e3_quarantine_rejects_untrusted_but_allows_trusted_beneficiary(engine_config):
    now = at(17, 14)
    quarantine_flag = DestinationFlag(QUARENTENA, now - timedelta(hours=2), now + timedelta(hours=48))

    untrusted_ctx = make_context(now, 5000, destination={"flags": (quarantine_flag,)})
    untrusted_decision = evaluate(untrusted_ctx, engine_config)

    assert untrusted_decision.status == REJECTED
    assert codes(untrusted_decision) == {"E3"}

    january_now = at(15, 14, month=1)
    rent_history = (
        PastPix(
            transaction_date=january_now.replace(year=2025, month=11, day=10),
            amount_cents=120000,
            destination_key=DESTINATION_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        ),
        PastPix(
            transaction_date=january_now.replace(year=2025, month=12, day=10),
            amount_cents=120000,
            destination_key=DESTINATION_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        ),
        PastPix(
            transaction_date=january_now.replace(year=2026, month=1, day=5),
            amount_cents=120000,
            destination_key=DESTINATION_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        ),
    )
    quarantine_jan = DestinationFlag(QUARENTENA, january_now - timedelta(hours=2), january_now + timedelta(hours=48))
    trusted_ctx = make_context(
        january_now,
        120000,
        history=routine_without_current_dest(january_now) + rent_history,
        destination={"flags": (quarantine_jan,)},
    )
    trusted_decision = evaluate(trusted_ctx, engine_config)

    assert "E3" not in codes(trusted_decision)
    assert "H2" not in codes(trusted_decision)


def test_e4_night_limit_exemptions_for_preregistered_destination_and_pj(engine_config):
    night = at(17, 22, 30)
    preregistered_pix = PastPix(
        transaction_date=night - timedelta(hours=30),
        amount_cents=5000,
        destination_key=DESTINATION_KEY,
        status=APPROVED,
        completed=True,
        device_id=DEVICE,
        channel="celular",
    )
    preregistered_ctx = make_context(
        now=night,
        amount_cents=150000,
        history=known_destination_history(night) + (preregistered_pix,),
    )
    assert "E4" not in codes(evaluate(preregistered_ctx, engine_config))

    pj_ctx = make_context(
        now=night,
        amount_cents=150000,
        pix={"source_document": PJ_DOCUMENT, "source_name": "PADARIA CENTRAL LTDA"},
    )
    assert "E4" not in codes(evaluate(pj_ctx, engine_config))

    pj_enforced_cfg = with_flag(engine_config, "APPLY_NIGHT_LIMIT_PJ", True)
    assert "E4" in codes(evaluate(pj_ctx, pj_enforced_cfg))

    mei_as_pj_cfg = with_flag(engine_config, "ENABLE_MEI_AS_PF", False)
    mei_ctx = make_context(
        now=night,
        amount_cents=150000,
        pix={"source_document": PJ_DOCUMENT, "source_name": "JOAO DA SILVA 52998224725"},
    )
    assert "E4" not in codes(evaluate(mei_ctx, mei_as_pj_cfg))
    assert eliminatory.e4_night_limit(Facts(pj_ctx, engine_config), "UNKNOWN_CLASS") is None


def test_e5_unknown_device_per_pix_floor_vs_daily_limit(engine_config):
    now = at(17, 14)
    unknown_device = DeviceSnapshot(first_seen=None, distinct_payers_7d=1)

    floor_ctx = make_context(
        now,
        30000,
        history=known_destination_history(now),
        device=unknown_device,
        pix={"geolocation": HOME},
    )
    floor_decision = evaluate(floor_ctx, engine_config)
    e5_hit = hit_for(floor_decision, "E5")

    assert e5_hit is not None
    assert e5_hit.floor is True
    assert e5_hit.eliminatory is False
    assert "E5" in floor_decision.floor_applied
    assert floor_decision.status == TWO_FACTOR_REQUIRED


def test_d1_maturing_and_unknown_device_points(engine_config):
    now = at(17, 14)
    maturing_ctx = make_context(
        now,
        5000,
        history=known_destination_history(now),
        device=DeviceSnapshot(first_seen=now - timedelta(hours=6), distinct_payers_7d=1),
        pix={"geolocation": HOME},
    )
    unknown_ctx = make_context(
        now,
        5000,
        history=known_destination_history(now),
        device=DeviceSnapshot(first_seen=None, distinct_payers_7d=1),
        pix={"geolocation": HOME},
    )

    assert hit_for(evaluate(maturing_ctx, engine_config), "D1").points == 20
    assert hit_for(evaluate(unknown_ctx, engine_config), "D1").points == 40


def test_d2_shared_device_fires_with_three_distinct_payers(engine_config):
    now = at(17, 14)
    shared_ctx = make_context(
        now,
        5000,
        history=known_destination_history(now),
        device=DeviceSnapshot(first_seen=now - timedelta(days=30), distinct_payers_7d=3),
        pix={"geolocation": HOME},
    )
    decision = evaluate(shared_ctx, engine_config)
    d2 = hit_for(decision, "D2")

    assert d2 is not None
    assert d2.points == 35
    assert d2.evidence == {"documents_7d": 3}


def test_d3_cold_start_suppresses_d1_and_e5(engine_config):
    now = at(17, 14)
    cold_ctx = make_context(
        now,
        5000,
        history=(),
        payer={"amount_history": ()},
        device=DeviceSnapshot(first_seen=None, distinct_payers_7d=1),
        pix={"geolocation": HOME},
    )
    decision = evaluate(cold_ctx, engine_config)

    assert "D3" in codes(decision)
    assert hit_for(decision, "D3").points == 5
    assert "D1" not in codes(decision)
    assert "E5" not in codes(decision)


@pytest.mark.parametrize(
    "location, expected_points",
    [
        (CAMPINAS_150KM, 15),
        (BRASILIA_600KM, 25),
    ],
)
def test_g1_distance_from_usual_bands(engine_config, location, expected_points):
    now = at(17, 14)
    context = make_context(
        now,
        5000,
        history=known_destination_history(now),
        pix={"geolocation": location},
    )
    decision = evaluate(context, engine_config)
    g1 = hit_for(decision, "G1")

    assert g1 is not None
    assert g1.points == expected_points
    assert g1.evidence["distance_km"] > 100


def test_g2_legacy_single_speed_config_branch(engine_config):
    now = at(17, 14)
    last = PastPix(
        transaction_date=now - timedelta(minutes=5),
        amount_cents=5000,
        destination_key=OTHER_KEY,
        status=APPROVED,
        completed=True,
        device_id=DEVICE,
        channel="celular",
        geolocation=HOME,
    )
    legacy_params = {
        **engine_config.params,
        "regras": {
            **engine_config.params["regras"],
            "G2": {"distancia_min_km": 100, "velocidade_kmh": 500, "pontos": 35},
        },
    }
    legacy_cfg = EngineConfig(version=1, params=legacy_params)
    ctx = make_context(now, 5000, history=known_destination_history(now) + (last,), pix={"geolocation": BRASILIA_600KM})

    g2 = scoring.g2_impossible_travel(Facts(ctx, legacy_cfg))
    assert g2 is not None
    assert g2.points == 35


@pytest.mark.parametrize(
    "days_old, expected_points",
    [
        (3, 30),
        (15, 20),
        (45, 5),
        (120, None),
    ],
)
def test_c2_destination_age_bands_and_missing(engine_config, days_old, expected_points):
    now = at(17, 14)
    ctx = make_context(
        now,
        5000,
        history=known_destination_history(now),
        destination_created_at=now - timedelta(days=days_old),
        pix={"geolocation": HOME},
    )
    c2 = hit_for(evaluate(ctx, engine_config), "C2")
    assert (c2.points if c2 else None) == expected_points

    missing_ctx = make_context(
        now,
        5000,
        history=known_destination_history(now),
        destination_created_at=None,
        pix={"geolocation": HOME},
    )
    missing_decision = evaluate(missing_ctx, engine_config)
    assert "destination_account.created_at" in missing_decision.inputs_missing


def test_c5_and_c6_mule_signals_set_friction_script_and_params(engine_config):
    now = at(17, 14)
    reputation = DestinationReputation(
        analyses_count=3,
        rejected_count=0,
        two_factor_count=0,
        payers_24h=5,
        forwarded_ratio_1h=0.75,
    )
    ctx = make_context(
        now,
        5000,
        history=routine_without_current_dest(now),
        destination={"reputation": reputation},
        pix={"geolocation": HOME},
    )
    decision = evaluate(ctx, engine_config)
    meta = decision.metadata(ctx)

    assert hit_for(decision, "C5").points == 25
    assert hit_for(decision, "C6").points == 25
    assert decision.status == TWO_FACTOR_REQUIRED
    assert decision.friction_script_key == "MULE_DESTINATION_CHECK"
    assert decision.friction_params == {"payers_24h_band": "SEVERAL"}
    assert meta["friction_params"] == {"payers_24h_band": "SEVERAL"}
    assert meta["family_caps_applied"] == {"destino": {"raw": 65, "cap": 55}}


def test_c7_endogenous_reputation_bands(engine_config):
    now = at(17, 14)
    low_sample = DestinationReputation(analyses_count=3, rejected_count=3)
    clean_rep = DestinationReputation(analyses_count=10, rejected_count=0, two_factor_count=1)
    band_30 = DestinationReputation(analyses_count=10, rejected_count=2, two_factor_count=1)
    band_50 = DestinationReputation(analyses_count=10, rejected_count=3, two_factor_count=3)

    ctx_low = make_context(now, 5000, history=known_destination_history(now), destination={"reputation": low_sample})
    ctx_clean = make_context(now, 5000, history=known_destination_history(now), destination={"reputation": clean_rep})
    ctx_30 = make_context(now, 5000, history=known_destination_history(now), destination={"reputation": band_30})
    ctx_50 = make_context(now, 5000, history=known_destination_history(now), destination={"reputation": band_50})

    assert hit_for(evaluate(ctx_low, engine_config), "C7") is None
    assert hit_for(evaluate(ctx_clean, engine_config), "C7") is None
    assert hit_for(evaluate(ctx_30, engine_config), "C7").points == 15
    assert hit_for(evaluate(ctx_50, engine_config), "C7").points == 30


def test_c8_does_not_fire_when_follow_up_amount_is_not_high(engine_config):
    now = at(17, 14, 30)
    test_pix = PastPix(
        transaction_date=now - timedelta(minutes=20),
        amount_cents=500,
        destination_key=DESTINATION_KEY,
        status=APPROVED,
        device_id=DEVICE,
        channel="celular",
    )
    ctx = make_context(now, 10000, history=routine_without_current_dest(now) + (test_pix,), pix={"geolocation": HOME})
    assert hit_for(evaluate(ctx, engine_config), "C8") is None


def test_reputation_observation_and_quarantine_transitions(engine_config):
    now = at(17, 14)
    mule_rep = DestinationReputation(
        analyses_count=6,
        rejected_count=4,
        two_factor_count=0,
        payers_24h=6,
        forwarded_ratio_1h=0.8,
    )
    ctx = make_context(
        now,
        1200000,
        destination_created_at=now - timedelta(days=15),
        destination={"document": PJ_DOCUMENT, "reputation": mule_rep},
    )

    triggers = observation_triggers(ctx.destination, ctx.pix.amount_cents, 8000.0, now, engine_config)
    assert "new_pj_account" in triggers
    assert "exorbitant_amount" in triggers

    signals = quarantine_signals(ctx.destination, engine_config)
    assert signals == ["C5", "C6", "C7"]

    status, changes = plan_transition(ctx.destination, ctx.pix.amount_cents, 8000.0, now, engine_config)
    assert status == QUARENTENA
    assert [change.status for change in changes] == [OBSERVACAO, QUARENTENA, OBSERVACAO]
    assert changes[2].reason == "after_quarantine"


def test_p1_amount_outlier_tiers(engine_config):
    now = at(17, 14)
    short_history = known_destination_history(now)[:3]
    short_ctx = make_context(
        now,
        60000,
        history=short_history,
        payer={"amount_history": tuple(MoneyMovement(p.transaction_date, p.amount_cents) for p in short_history)},
        pix={"geolocation": HOME},
    )
    assert hit_for(evaluate(short_ctx, engine_config), "P1").points == 10

    above_ctx = make_context(now, 80000, history=known_destination_history(now), pix={"geolocation": HOME})
    assert hit_for(evaluate(above_ctx, engine_config), "P1").points == 20

    high_ctx = make_context(now, 200000, history=known_destination_history(now), pix={"geolocation": HOME})
    assert hit_for(evaluate(high_ctx, engine_config), "P1").points == 30


def test_p2_unusual_hour_fires_when_outside_habitual_window_and_skips_short_history(engine_config):
    now = at(17, 4)
    short_ctx = make_context(now, 8000, history=known_destination_history(now)[:4], pix={"geolocation": HOME})
    assert hit_for(evaluate(short_ctx, engine_config), "P2") is None

    daytime_history = tuple(
        PastPix(
            transaction_date=at(1 + idx, 14),
            amount_cents=8000,
            destination_key=DESTINATION_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
            geolocation=HOME,
        )
        for idx in range(12)
    )
    ctx = make_context(now, 8000, history=daytime_history, pix={"geolocation": HOME})
    decision = evaluate(ctx, engine_config)
    p2 = hit_for(decision, "P2")

    assert p2 is not None
    assert p2.points == 10
    assert p2.evidence == {"hour": 4, "share": 0.0}


def test_m1_accumulated_24h_fires_above_three_times_threshold(engine_config):
    now = at(17, 14)
    recent_24h = tuple(
        PastPix(
            transaction_date=now - timedelta(hours=hour),
            amount_cents=45000,
            destination_key=DESTINATION_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
            geolocation=HOME,
        )
        for hour in (1, 2, 3)
    )
    ctx = make_context(now, 45000, history=known_destination_history(now) + recent_24h, pix={"geolocation": HOME})
    m1 = hit_for(evaluate(ctx, engine_config), "M1")

    assert m1 is not None
    assert m1.points == 20
    assert m1.evidence["sum_24h_cents"] == 180000


def test_m2_splitting_near_ceiling_fires_with_three_transactions(engine_config):
    now = at(17, 14)
    splits = (
        PastPix(
            transaction_date=now - timedelta(hours=2),
            amount_cents=18000,
            destination_key=DESTINATION_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        ),
        PastPix(
            transaction_date=now - timedelta(hours=1),
            amount_cents=19000,
            destination_key=DESTINATION_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        ),
    )
    ctx = make_context(now, 19500, history=known_destination_history(now) + splits, pix={"geolocation": HOME})
    m2 = hit_for(evaluate(ctx, engine_config), "M2")

    assert m2 is not None
    assert m2.points == 30
    assert m2.evidence == {"ceiling_cents": 20000, "pix_near_ceiling": 3}


def test_v2_three_new_destinations_in_one_hour(engine_config):
    now = at(17, 14)
    recent_new = (
        PastPix(
            transaction_date=now - timedelta(minutes=40),
            amount_cents=5000,
            destination_key="1" * 64,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        ),
        PastPix(
            transaction_date=now - timedelta(minutes=20),
            amount_cents=5000,
            destination_key="2" * 64,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        ),
    )
    ctx = make_context(now, 5000, history=routine_without_current_dest(now) + recent_new, pix={"geolocation": HOME})
    v2 = hit_for(evaluate(ctx, engine_config), "V2")

    assert v2 is not None
    assert v2.points == 30
    assert v2.evidence == {"new_destinations_1h": 3}


def test_o1_new_source_account_under_30_days_and_missing(engine_config):
    now = at(17, 14)
    ctx = make_context(
        now,
        5000,
        history=known_destination_history(now),
        payer={"account_created_at": now - timedelta(days=10)},
        pix={"geolocation": HOME},
    )
    o1 = hit_for(evaluate(ctx, engine_config), "O1")

    assert o1 is not None
    assert o1.points == 10
    assert o1.evidence == {"source_age_days": 10}

    none_ctx = make_context(
        now,
        5000,
        history=known_destination_history(now),
        payer={"account_created_at": None},
        pix={"geolocation": HOME},
    )
    assert hit_for(evaluate(none_ctx, engine_config), "O1") is None


def test_k1_short_history_and_unknown_segment_and_r1_remote_access(engine_config):
    now = at(17, 14)
    short_ctx = make_context(
        now,
        5000,
        history=known_destination_history(now)[:3],
        pix={"channel": "computador", "remote_access_detected": True, "geolocation": HOME},
    )
    decision = evaluate(short_ctx, engine_config)

    assert hit_for(decision, "K1") is None
    assert hit_for(decision, "R1").points == 30
    assert hit_for(decision, "R1").evidence["remote_access_detected"] is True
    assert channel.segment_of("canal_inexistente", engine_config) is None


def test_x2_floor_applies_in_band_d_with_new_beneficiary(engine_config):
    now = at(17, 14)
    high_routine = routine_without_current_dest(now, amount_cents=600000)
    ctx = make_context(
        now,
        600000,
        history=high_routine,
        pix={"geolocation": HOME},
    )
    decision = evaluate(ctx, engine_config)

    assert decision.value_band == "D"
    assert "C1" in codes(decision)
    assert "X2" in decision.floor_applied
    assert decision.status == TWO_FACTOR_REQUIRED


def test_f1_amount_vs_income_with_deposits_and_open_finance(engine_config):
    now = at(17, 14)
    deposits = (MoneyMovement(now - timedelta(days=5), 100000),)
    of_profile = OpenFinanceProfile(
        other_income_cents=50000,
        other_balance_cents=200000,
        loaded_at=now - timedelta(hours=2),
        consent_expires_at=now + timedelta(days=30),
    )
    ctx = make_context(
        now,
        350000,
        history=known_destination_history(now),
        payer={"deposits": deposits, "open_finance": of_profile},
        pix={"geolocation": HOME},
    )
    f1 = hit_for(evaluate(ctx, engine_config), "F1")

    assert f1 is not None
    assert f1.points == 25
    assert f1.evidence == {"amount_to_income": 2.33}

    low_ctx = make_context(
        now,
        50000,
        history=known_destination_history(now),
        payer={"deposits": deposits, "open_finance": of_profile},
        pix={"geolocation": HOME},
    )
    assert hit_for(evaluate(low_ctx, engine_config), "F1") is None


def test_f2_balance_drain_combines_local_and_open_finance_balances(engine_config):
    now = at(17, 14)
    of_profile = OpenFinanceProfile(
        other_income_cents=100000,
        other_balance_cents=50000,
        loaded_at=now - timedelta(hours=2),
        consent_expires_at=now + timedelta(days=30),
    )
    ctx = make_context(
        now,
        85000,
        history=known_destination_history(now),
        payer={"balance_cents": 50000, "open_finance": of_profile},
        pix={"geolocation": HOME},
    )
    f2 = hit_for(evaluate(ctx, engine_config), "F2")

    assert f2 is not None
    assert f2.points == 15
    assert f2.evidence == {"amount_to_balance": 0.85}

    safe_ctx = make_context(
        now,
        20000,
        history=known_destination_history(now),
        payer={"balance_cents": 50000, "open_finance": of_profile},
        pix={"geolocation": HOME},
    )
    assert hit_for(evaluate(safe_ctx, engine_config), "F2") is None


def test_f3_pass_through_with_open_finance_balance_drop_reinforcement(engine_config):
    now = at(17, 14)
    recent_deposit = (MoneyMovement(now - timedelta(minutes=12), 100000),)
    of_profile = OpenFinanceProfile(
        other_income_cents=200000,
        other_balance_cents=5000,
        other_balance_prev_cents=105000,
        prev_loaded_at=now - timedelta(hours=4),
        loaded_at=now - timedelta(minutes=5),
        consent_expires_at=now + timedelta(days=10),
    )
    ctx = make_context(
        now,
        95000,
        history=routine_without_current_dest(now, amount_cents=100000),
        payer={"deposits": recent_deposit, "open_finance": of_profile, "balance_cents": 500000},
        pix={"geolocation": HOME},
    )
    decision = evaluate(ctx, engine_config)
    f3 = hit_for(decision, "F3")

    assert f3 is not None
    assert f3.points == 45
    assert f3.floor is True
    assert f3.evidence == {"deposit_minutes_ago": 12, "open_finance_drop": True}
    assert "F3" in decision.floor_applied
    assert decision.status == TWO_FACTOR_REQUIRED
    assert decision.friction_script_key == "PASSTHROUGH_CHECK"


def test_missing_pj_name_and_trusted_contact_flag_are_reported(engine_config):
    now = at(17, 14)
    ctx = make_context(
        now,
        5000,
        history=known_destination_history(now),
        pix={
            "source_document": PJ_DOCUMENT,
            "source_name": None,
            "has_trusted_contact": None,
            "channel": None,
            "geolocation": HOME,
        },
    )
    decision = evaluate(ctx, engine_config)

    assert {
        "source_account.owner.name",
        "source_account.has_trusted_contact",
        "source.channel",
    } <= set(decision.inputs_missing)
    assert classify_payer(PJ_DOCUMENT, "EMPRESA COM NUMERO 99999999", engine_config)[0] == PJ


def test_identity_helpers_mask_and_hash():
    assert only_digits("529.982.247-25") == "52998224725"
    assert len(document_hash("529.982.247-25")) == 64
    assert mask_document("529.982.247-25") == "529******25"
    assert mask_document("1234") == "****"
    assert len(destination_key("BANCO60", "0001", "12345", "529.982.247-25")) == 64


def test_empty_percentile_raises_value_error():
    with pytest.raises(ValueError):
        percentile([], 95)


def test_config_timezone_and_same_day_night_window_edge_cases(engine_config):
    now = at(17, 3)
    no_tz_cfg = EngineConfig(version=1, params={**engine_config.params, "timezone_regra": None})
    bad_tz_cfg = EngineConfig(version=1, params={**engine_config.params, "timezone_regra": "Invalid/Zone"})
    day_window_cfg = EngineConfig(
        version=1,
        params={**engine_config.params, "janela_noite_inicio": "01:00", "janela_noite_fim": "05:00"},
    )

    assert no_tz_cfg.local_time(now) == now
    assert bad_tz_cfg.local_time(now) == now
    assert day_window_cfg.is_night(now) is True

    bad_bands_cfg = EngineConfig(
        version=1,
        params={**engine_config.params, "faixas": [{"faixa": "A", "ate_centavos": 100, "dois_fatores": 10, "reprova": 20}]},
    )
    with pytest.raises(ValueError):
        bad_bands_cfg.band_for(500)
