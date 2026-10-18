from dataclasses import replace
from datetime import datetime, timedelta, timezone

from domain import (
    APPROVED,
    REJECTED,
    TWO_FACTOR_REQUIRED,
    DestinationFlag,
    DestinationSnapshot,
    DeviceSnapshot,
    EvaluationContext,
    MoneyMovement,
    PastPix,
    PayerSnapshot,
    PixRequest,
    apply_second_factor,
    evaluate,
)
from domain.payer_class import MEI, PF, PJ, classify_payer
from domain.statistics import percentile


BRT = timezone(timedelta(hours=-3))
PAYER_CPF = "52998224725"
DESTINATION_CPF = "11144477735"
DESTINATION_KEY = "d" * 64
OTHER_KEY = "e" * 64
DEVICE = "device-1"


def at(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=BRT)


def routine_history(now: datetime) -> tuple[PastPix, ...]:
    return tuple(
        PastPix(
            transaction_date=now - timedelta(days=3 + index * 4, hours=index % 3),
            amount_cents=8000,
            destination_key=OTHER_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        )
        for index in range(12)
    )


def build_context(now: datetime, amount_cents: int, **overrides) -> EvaluationContext:
    history = overrides.pop("history", routine_history(now))
    pix = PixRequest(
        pix_id="pix-1",
        amount_cents=amount_cents,
        transaction_date=now,
        source_document=PAYER_CPF,
        destination_document=DESTINATION_CPF,
        destination_key=DESTINATION_KEY,
        channel="celular",
        device_id=DEVICE,
        remote_access_detected=False,
        call_in_progress=False,
        has_trusted_contact=False,
    )
    pix = replace(pix, **overrides.pop("pix", {}))
    payer = PayerSnapshot(
        source_hash="a" * 64,
        history=history,
        amount_history=tuple(MoneyMovement(item.transaction_date, item.amount_cents) for item in history),
        account_created_at=now - timedelta(days=900),
        **overrides.pop("payer", {}),
    )
    destination = DestinationSnapshot(
        destination_key=DESTINATION_KEY,
        document=DESTINATION_CPF,
        account_created_at=overrides.pop("destination_created_at", now - timedelta(days=400)),
        **overrides.pop("destination", {}),
    )
    device = overrides.pop("device", DeviceSnapshot(first_seen=now - timedelta(days=200), distinct_payers_7d=1))
    return EvaluationContext(pix=pix, payer=payer, destination=destination, device=device)


def codes(decision) -> set[str]:
    return {hit.code for hit in decision.rules_fired}


def test_p95_ignores_single_outlier():
    values = [20000] * 17 + [800000]
    assert round(percentile(values, 95)) == 137000


def test_night_pix_above_ceiling_to_unregistered_destination_is_rejected(engine_config):
    now = at(17, 22, 15)
    context = build_context(now, 150000, destination_created_at=now - timedelta(days=7))

    decision = evaluate(context, engine_config)

    assert decision.status == REJECTED
    assert codes(decision) == {"E4"}
    assert decision.customer_message_key == "BLOCKED_FOR_SAFETY"


def test_daytime_pix_to_young_destination_asks_two_factor(engine_config):
    now = at(17, 14)
    context = build_context(now, 150000, destination_created_at=now - timedelta(days=7))

    decision = evaluate(context, engine_config)

    assert decision.status == TWO_FACTOR_REQUIRED
    assert decision.value_band == "C"
    assert {"C1", "C2"} <= codes(decision)
    assert decision.challenge_type == "CUSTOMER_TOKEN_2FA"
    assert decision.friction_script_key == "CONFIRM_IDENTITY"


def test_monthly_rent_to_trusted_beneficiary_is_approved(engine_config):
    now = at(17, 14)
    rent = tuple(
        PastPix(
            transaction_date=at(10, 10, month=month),
            amount_cents=120000,
            destination_key=DESTINATION_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        )
        for month in (7, 8, 9)
    )
    history = routine_history(now) + rent
    context = build_context(now, 120000, history=history)

    decision = evaluate(context, engine_config)

    assert "C1" not in codes(decision)
    assert "H2" in codes(decision)
    assert decision.score == 0
    assert decision.status == APPROVED


def test_test_then_drain_hits_c8_floor(engine_config):
    now = at(17, 14, 30)
    test_pix = PastPix(
        transaction_date=now - timedelta(minutes=30),
        amount_cents=200,
        destination_key=DESTINATION_KEY,
        status=APPROVED,
        device_id=DEVICE,
        channel="celular",
    )
    context = build_context(
        now,
        400000,
        history=routine_history(now) + (test_pix,),
        destination_created_at=now - timedelta(days=3),
    )

    decision = evaluate(context, engine_config)

    assert "C8" in decision.floor_applied
    assert decision.status in (TWO_FACTOR_REQUIRED, REJECTED)


def test_flagged_destination_rejects_payment_but_not_refund(engine_config):
    now = at(17, 14)
    flag = DestinationFlag("MARCADA", now - timedelta(days=10), now + timedelta(days=365 * 5))
    payment = build_context(now, 5000, destination={"flags": (flag,)})
    refund = build_context(now, 5000, destination={"flags": (flag,)}, pix={"type": "refund"})

    assert evaluate(payment, engine_config).status == REJECTED
    assert "E2" not in codes(evaluate(refund, engine_config))


def test_burst_of_pix_in_ten_minutes_fires_v1(engine_config):
    now = at(17, 14)
    burst = tuple(
        PastPix(
            transaction_date=now - timedelta(minutes=minute),
            amount_cents=5000,
            destination_key=OTHER_KEY,
            status=APPROVED,
            completed=True,
            device_id=DEVICE,
            channel="celular",
        )
        for minute in (1, 2, 3, 4)
    )
    context = build_context(now, 5000, history=routine_history(now) + burst)

    hit = next(hit for hit in evaluate(context, engine_config).rules_fired if hit.code == "V1")

    assert hit.points == 40
    assert hit.evidence == {"pix_10min": 5}


def test_unknown_device_over_daily_limit_is_rejected(engine_config):
    now = at(17, 14)
    context = build_context(now, 120000, device=DeviceSnapshot(first_seen=None, distinct_payers_7d=1))

    decision = evaluate(context, engine_config)

    assert decision.status == REJECTED
    assert codes(decision) == {"E5"}


def test_call_in_progress_with_consented_contact_uses_social_2fa(engine_config):
    now = at(17, 14)
    context = build_context(
        now,
        45000,
        pix={"call_in_progress": True, "has_trusted_contact": True},
        payer={"balance_cents": 50000, "has_consented_trusted_contact": True},
    )

    decision = evaluate(context, engine_config)

    assert decision.status == TWO_FACTOR_REQUIRED
    assert {"R1", "C1", "F2"} <= codes(decision)
    assert decision.challenge_type == "TRUSTED_CONTACT_APPROVAL"
    assert decision.friction_script_key == "CALL_COACHING_CHECK"
    assert decision.notify_trusted_contact is True


def test_missing_optional_fields_are_reported(engine_config):
    now = at(17, 14)
    context = build_context(
        now, 5000, pix={"device_id": None, "remote_access_detected": None, "call_in_progress": None}
    )

    missing = evaluate(context, engine_config).inputs_missing

    assert {"source.device_id", "source.remote_access_detected", "source.call_in_progress"} <= set(missing)


def test_friction_yes_escalates_and_never_relaxes(engine_config):
    assert apply_second_factor(TWO_FACTOR_REQUIRED, "CALL_COACHING_CHECK", "YES", False, engine_config) == (
        REJECTED,
        None,
    )
    assert apply_second_factor(TWO_FACTOR_REQUIRED, "CALL_COACHING_CHECK", "YES", True, engine_config) == (
        TWO_FACTOR_REQUIRED,
        "TRUSTED_CONTACT_APPROVAL",
    )
    assert apply_second_factor(TWO_FACTOR_REQUIRED, "CALL_COACHING_CHECK", "NO", False, engine_config) == (
        APPROVED,
        None,
    )
    assert apply_second_factor(REJECTED, None, None, True, engine_config) == (REJECTED, None)


def test_mei_recognition(engine_config):
    cnpj = "11222333000181"
    assert classify_payer(PAYER_CPF, None, engine_config)[0] == PF
    assert classify_payer(cnpj, "JOAO DA SILVA 52998224725", engine_config)[0] == MEI
    assert classify_payer(cnpj, "Maria de Sá 52998224725", engine_config)[0] == MEI
    assert classify_payer(cnpj, "MARIA SOUZA 11222333", engine_config)[0] == MEI
    assert classify_payer(cnpj, "PADARIA SOL LTDA", engine_config)[0] == PJ
    assert classify_payer(cnpj, "COMERCIAL XYZ", engine_config)[0] == PJ
    assert classify_payer(cnpj, "CONSTRUTORA S.A.", engine_config)[0] == PJ
