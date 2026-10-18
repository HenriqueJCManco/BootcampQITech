from dataclasses import replace
from datetime import timedelta

from domain import (
    APPROVED,
    REJECTED,
    TWO_FACTOR_REQUIRED,
    Geolocation,
    Interaction,
    PastPix,
    evaluate,
)
from test_fraud_engine import DESTINATION_KEY, DEVICE, OTHER_KEY, at, build_context


ROBOTIC = {"is_robotic_movement": True, "typing_cadence_std_ms": 1.2, "session_idle_then_burst": True}


def hit(decision, code):
    return next((rule for rule in decision.rules_fired if rule.code == code), None)


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


def test_mobile_without_geolocation_fires_g4_and_reports_missing_input(engine_config):
    now = at(17, 14)
    context = build_context(now, 5000, history=known_destination_history(now), pix={"channel": "celular"})

    decision = evaluate(context, engine_config)

    assert hit(decision, "G4").points == engine_config.rule("G4")["pontos"]
    assert "geolocation" in decision.inputs_missing
    assert decision.status == APPROVED


def test_mobile_with_geolocation_does_not_fire_g4(engine_config):
    now = at(17, 14)
    context = build_context(
        now, 5000, history=known_destination_history(now), pix={"geolocation": Geolocation(-23.55, -46.63)}
    )

    assert hit(evaluate(context, engine_config), "G4") is None


def test_mobile_call_in_progress_holds_pix_and_flags_trusted_contact(engine_config):
    now = at(17, 14)
    context = build_context(
        now,
        5000,
        history=known_destination_history(now),
        pix={"call_in_progress": True, "has_trusted_contact": True},
    )

    decision = evaluate(context, engine_config)
    metadata = decision.metadata(context)

    assert decision.status == TWO_FACTOR_REQUIRED
    assert "R1" in decision.floor_applied
    assert metadata["customer_message_key"] == "CONFIRM_IDENTITY"
    assert metadata["friction_script_key"] == "CALL_COACHING_CHECK"
    assert metadata["notify_trusted_contact"] is True


def test_desktop_robotic_session_to_new_destination_is_rejected(engine_config):
    now = at(17, 14)
    context = build_context(
        now,
        5000,
        pix={"channel": "computador", "interaction": Interaction(raw=ROBOTIC, **ROBOTIC)},
    )

    decision = evaluate(context, engine_config)
    r2 = hit(decision, "R2")

    assert decision.status == REJECTED
    assert r2.points == 40
    assert r2.evidence["signals"] == ["is_robotic_movement", "typing_cadence_std_ms", "session_idle_then_burst"]
    assert r2.evidence["interaction"] == ROBOTIC
    assert r2.evidence["escalated_with"] == ["C1"]
    assert hit(decision, "C1") is not None
    assert decision.metadata(context)["inputs"] == {"interaction": ROBOTIC}


def test_desktop_robotic_session_to_known_destination_asks_two_factor(engine_config):
    now = at(17, 14)
    signal = {"is_robotic_movement": True}
    context = build_context(
        now,
        5000,
        history=known_destination_history(now),
        pix={"channel": "internet", "interaction": Interaction(raw=signal, **signal)},
    )

    decision = evaluate(context, engine_config)

    assert decision.status == TWO_FACTOR_REQUIRED
    assert "R2" in decision.floor_applied
    assert "escalated_with" not in hit(decision, "R2").evidence


def test_desktop_after_mobile_routine_fires_k1_by_segment(engine_config):
    now = at(17, 14)
    human = {"is_robotic_movement": False, "typing_cadence_std_ms": 140.0}
    context = build_context(
        now,
        5000,
        history=known_destination_history(now),
        pix={"channel": "computador", "interaction": Interaction(raw=human, **human)},
    )

    decision = evaluate(context, engine_config)

    assert hit(decision, "K1").evidence["segment"] == "desktop"
    assert hit(decision, "R2") is None


def test_desktop_without_interaction_reports_missing_input(engine_config):
    now = at(17, 14)
    context = build_context(now, 5000, history=known_destination_history(now), pix={"channel": "internet"})

    assert "source.interaction" in evaluate(context, engine_config).inputs_missing


def test_robotic_signal_on_mobile_is_not_scored_by_r2(engine_config):
    now = at(17, 14)
    context = build_context(now, 5000, history=known_destination_history(now))
    context = replace(context, pix=replace(context.pix, interaction=Interaction(raw=ROBOTIC, **ROBOTIC)))

    assert hit(evaluate(context, engine_config), "R2") is None
