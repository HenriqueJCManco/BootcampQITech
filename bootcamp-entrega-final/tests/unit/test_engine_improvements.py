from dataclasses import replace
from datetime import timedelta

import pytest

from domain import (
    APPROVED,
    REJECTED,
    TWO_FACTOR_REQUIRED,
    EngineConfig,
    Geolocation,
    PastPix,
    RuleHit,
    evaluate,
)
from domain.engine import _floors, capped_score, decide
from test_fraud_engine import DESTINATION_KEY, DEVICE, OTHER_KEY, at, build_context


KM_PER_DEGREE_LATITUDE = 111.195
HOME = Geolocation(-23.55, -46.63)


def codes(decision) -> set[str]:
    return {hit.code for hit in decision.rules_fired}


def with_flag(config: EngineConfig, name: str, value: bool) -> EngineConfig:
    params = {**config.params, "flags": {**config.params["flags"], name: value}}
    return EngineConfig(version=config.version, params=params)


def known_destination_history(now):
    return tuple(
        PastPix(
            transaction_date=now - timedelta(days=2 + day),
            amount_cents=5000,
            destination_key=DESTINATION_KEY if day % 2 == 0 else OTHER_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        )
        for day in range(12)
    )


@pytest.mark.parametrize("amount, band", [(20000, "A"), (20001, "B"), (100000, "B"), (100001, "C"), (500001, "D")])
def test_value_bands_are_inclusive(engine_config, amount, band):
    assert engine_config.band_for(amount)["faixa"] == band


@pytest.mark.parametrize(
    "score, floors, status",
    [
        (44, [], APPROVED),
        (45, [], TWO_FACTOR_REQUIRED),
        (84, [], TWO_FACTOR_REQUIRED),
        (85, [], REJECTED),
        (0, ["R1"], TWO_FACTOR_REQUIRED),
        (90, ["R1"], REJECTED),
    ],
)
def test_decision_boundaries_in_band_a(engine_config, score, floors, status):
    assert decide(score, engine_config.band_for(20000), floors) == status


def test_eliminatory_rejects_regardless_of_score(engine_config):
    assert decide(0, engine_config.band_for(100), [], blocked=True) == REJECTED


def test_pix_to_five_day_old_account_asks_two_factor_in_band_c(engine_config):
    now = at(17, 14)
    in_pattern = tuple(replace(pix, amount_cents=150000) for pix in known_destination_history(now))
    history = tuple(replace(pix, destination_key=OTHER_KEY) for pix in in_pattern)
    context = build_context(
        now, 150000, history=history, destination_created_at=now - timedelta(days=5), pix={"geolocation": HOME}
    )

    decision = evaluate(context, engine_config)

    assert codes(decision) == {"C1", "C2"}
    assert decision.score == 45
    assert decision.value_band == "C"
    assert decision.status == TWO_FACTOR_REQUIRED


def test_r1_alone_is_a_two_factor_floor(engine_config):
    now = at(17, 14)
    context = build_context(
        now, 5000, history=known_destination_history(now), pix={"call_in_progress": True, "geolocation": HOME}
    )

    decision = evaluate(context, engine_config)

    assert decision.score < decision.thresholds["two_factor"]
    assert decision.floor_applied == ["R1"]
    assert decision.status == TWO_FACTOR_REQUIRED


def test_registered_bet_destination_is_rejected_by_e6(engine_config):
    now = at(17, 14)
    context = build_context(now, 5000, history=known_destination_history(now), destination={"bet_registered": True})

    decision = evaluate(context, engine_config)

    assert decision.status == REJECTED
    assert codes(decision) == {"E6"}
    assert "990" not in str(decision.rules_fired[0].evidence)


def test_bet_refund_and_disabled_flag_do_not_fire_e6(engine_config):
    now = at(17, 14)
    refund = build_context(
        now, 5000, history=known_destination_history(now), destination={"bet_registered": True}, pix={"type": "refund"}
    )
    payment = build_context(now, 5000, history=known_destination_history(now), destination={"bet_registered": True})

    assert "E6" not in codes(evaluate(refund, engine_config))
    assert "E6" not in codes(evaluate(payment, with_flag(engine_config, "ENABLE_BETS_BAN", False)))


def moved(km: float) -> Geolocation:
    return Geolocation(HOME.latitude + km / KM_PER_DEGREE_LATITUDE, HOME.longitude)


def travel_context(now, km: float, minutes_ago: float, accuracy_m: float | None = None):
    last = PastPix(
        transaction_date=now - timedelta(minutes=minutes_ago),
        amount_cents=5000,
        destination_key=OTHER_KEY,
        status=APPROVED,
        completed=True,
        device_id=DEVICE,
        channel="celular",
        geolocation=replace(HOME, accuracy_m=accuracy_m),
    )
    history = known_destination_history(now) + (last,)
    return build_context(now, 5000, history=history, pix={"geolocation": moved(km)})


@pytest.mark.parametrize(
    "km, minutes_ago, accuracy_m, fires",
    [
        (100, 2, None, True),
        (60, 2, None, True),
        (15, 2, None, False),
        (60, 60, None, False),
        (100, 2, 6000, False),
        (100, 7 * 60, None, False),
    ],
)
def test_impossible_travel_levels_and_filters(engine_config, km, minutes_ago, accuracy_m, fires):
    now = at(17, 14)
    decision = evaluate(travel_context(now, km, minutes_ago, accuracy_m), engine_config)

    assert ("G2" in codes(decision)) is fires
    if fires:
        assert "G2" in decision.floor_applied


def test_family_cap_limits_positive_points_only(engine_config):
    hits = [RuleHit("C1", 15), RuleHit("C2", 30), RuleHit("C8", 30), RuleHit("R1", 30), RuleHit("H2", -25)]

    score, applied = capped_score(hits, engine_config)

    assert score == 55 + 30 - 25
    assert applied == {"destino": {"raw": 75, "cap": 55}}
    assert capped_score(hits, with_flag(engine_config, "ENABLE_FAMILY_CAPS", False)) == (80, {})


def test_x1_counts_only_signals_between_ten_and_twenty(engine_config):
    small = [RuleHit("G4", 5), RuleHit("D3", 5), RuleHit("K1", 5)]
    medium = [RuleHit("C1", 15), RuleHit("K1", 10), RuleHit("O1", 10)]

    assert "X1" not in _floors(small, "A", engine_config)
    assert "X1" in _floors(medium, "A", engine_config)
