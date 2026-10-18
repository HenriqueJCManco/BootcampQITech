from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text

from tests.utils import INTERNAL_TOKEN, RandomGenerator
from tests.utils.requisition import ClientRequisition


def api_request(method, endpoint, payload=None, token=True):
    headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN} if token else {}
    return ClientRequisition.send(method, endpoint, payload=payload, headers=headers)


def create_payer(with_contact: bool = True) -> dict:
    document = RandomGenerator.generate_cpf()
    customer = api_request(
        "POST",
        "/customer",
        {"name": "Maria Idosa", "email": f"{uuid4()}@example.test", "document_number": document},
    )
    assert customer.response_status == 201, customer.response_json
    account = api_request("POST", "/account", {"customer_key": customer.response_json["customer_key"]})
    assert account.response_status == 201, account.response_json
    if with_contact:
        contact = api_request(
            "POST",
            f"/account/{account.response_json['account_key']}/trusted_contact",
            {"name": "Filha", "channel": "EMAIL", "address": f"{uuid4()}@example.test"},
        )
        assert contact.response_status == 201, contact.response_json
    return {"document_number": document, "account_key": account.response_json["account_key"]}


def pix_payload(payer: dict, **source) -> dict:
    return {
        "id": str(uuid4()),
        "amount": 15000,
        "transaction_date": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "source_account": {"document_number": payer["document_number"], "has_trusted_contact": True},
        "destination_account": {
            "document_number": RandomGenerator.generate_cpf(),
            "participant": "60701190",
            "branch": "0001",
            "number": str(uuid4().int)[:8],
        },
        "source": {"device_id": "device-maria", "remote_access_detected": False, "call_in_progress": False, **source},
    }


def post_pix(payload: dict):
    return api_request("POST", "/pix/transaction", payload)


def rules(response) -> dict:
    return {rule["code"]: rule for rule in response.response_json["metadata"]["rules_fired"]}


def analysis_id(session, pix_id: str) -> int:
    return session.execute(text("SELECT id FROM fraude.pix_analysis WHERE pix_id = :id"), {"id": pix_id}).scalar_one()


def test_mobile_app_pix_held_writes_outbox_without_transaction(session):
    payload = pix_payload(create_payer(), channel="app", call_in_progress=True)

    response = post_pix(payload)

    assert response.response_status == 201, response.response_json
    body = response.response_json
    assert body["status"] == "two_factor_required"
    assert body["metadata"]["customer_message_key"] == "CONFIRM_IDENTITY"
    assert body["metadata"]["friction_script_key"] == "CALL_COACHING_CHECK"
    assert body["metadata"]["notify_trusted_contact"] is True
    assert rules(response)["R1"]["evidence"]["call_in_progress"] is True

    stored_id = analysis_id(session, payload["id"])
    channel = session.execute(
        text("SELECT channel FROM fraude.pix_analysis WHERE id = :id"), {"id": stored_id}
    ).scalar_one()
    assert channel == "celular"
    outbox = session.execute(
        text("SELECT transaction_id, analysis_id FROM notification_outbox WHERE transaction_id IS NULL")
    ).all()
    assert outbox == [(None, stored_id)]

    from repositories import FraudRepository

    blocked = FraudRepository(session).list_blocked_pix()
    assert [row["pix_id"] for row in blocked] == [payload["id"]]
    assert {rule["rule"] for rule in blocked[0]["rules_metadata"]} == set(rules(response))


def test_mobile_pix_without_geolocation_fires_g4(session):
    payload = pix_payload(create_payer(), channel="celular")

    response = post_pix(payload)

    assert response.response_status == 201, response.response_json
    assert rules(response)["G4"]["points"] == 5
    assert "geolocation" in response.response_json["metadata"]["inputs_missing"]
    stored = session.execute(
        text("SELECT points FROM fraude.pix_rule_result WHERE analysis_id = :id AND rule_code = 'G4'"),
        {"id": analysis_id(session, payload["id"])},
    ).scalar_one()
    assert stored == 5


def test_desktop_robotic_session_to_new_destination_is_rejected(session):
    interaction = {"is_robotic_movement": True, "typing_cadence_std_ms": 0.8, "session_idle_then_burst": True}
    payload = pix_payload(create_payer(), channel="computador", remote_access_detected=True, interaction=interaction)

    response = post_pix(payload)

    assert response.response_status == 201, response.response_json
    assert response.response_json["status"] == "rejected"
    assert response.response_json["metadata"]["customer_message_key"] == "BLOCKED_FOR_SAFETY"
    r2 = rules(response)["R2"]
    assert r2["points"] == 40
    assert r2["evidence"]["escalated_with"] == ["C1"]
    evidence = session.execute(
        text("SELECT evidence FROM fraude.pix_rule_result WHERE analysis_id = :id AND rule_code = 'R2'"),
        {"id": analysis_id(session, payload["id"])},
    ).scalar_one()
    assert evidence["interaction"] == interaction


def test_resend_returns_original_analysis_and_one_row(session):
    payload = pix_payload(create_payer(with_contact=False), channel="celular")

    first = post_pix(payload)
    second = post_pix(payload)

    assert (first.response_status, second.response_status) == (201, 200)
    assert second.response_json == first.response_json
    count = session.execute(
        text("SELECT count(*) FROM fraude.pix_analysis WHERE pix_id = :id"), {"id": payload["id"]}
    ).scalar_one()
    assert count == 1

    fetched = api_request("GET", f"/pix/transaction/{payload['id']}")
    assert fetched.response_status == 200
    assert fetched.response_json == first.response_json


def test_same_id_with_different_body_is_conflict():
    payload = pix_payload(create_payer(with_contact=False), channel="celular")
    assert post_pix(payload).response_status == 201

    payload["amount"] = payload["amount"] + 1
    response = post_pix(payload)

    assert response.response_status == 409
    assert response.response_json["code"] == "AFP000004"


def test_friction_yes_without_consented_contact_escalates_to_rejected():
    payload = pix_payload(create_payer(), channel="celular", call_in_progress=True)
    assert post_pix(payload).response_json["status"] == "two_factor_required"

    retry = {**payload, "second_factor_passed": True, "friction_answer": "YES"}
    response = post_pix(retry)

    assert response.response_status == 200
    assert response.response_json["status"] == "rejected"


def test_second_factor_approves_held_pix():
    payload = pix_payload(create_payer(), channel="celular", call_in_progress=True)
    assert post_pix(payload).response_json["status"] == "two_factor_required"

    response = post_pix({**payload, "second_factor_passed": True, "friction_answer": "NO"})

    assert response.response_status == 200
    assert response.response_json["status"] == "approved"


def test_invalid_inputs_map_to_afp_codes():
    payer = create_payer(with_contact=False)
    cases = [
        ({"source": {"channel": "smart_tv"}}, 422, "AFP000007"),
        ({"amount": 10.5}, 400, "AFP000008"),
        ({"amount": 0}, 400, "AFP000008"),
        ({"transaction_date": "2026-10-17T14:00:00"}, 400, "AFP000006"),
        ({"transaction_date": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}, 400, "AFP000006"),
        ({"unexpected": True}, 400, "AFP000001"),
    ]
    for override, status, code in cases:
        response = post_pix({**pix_payload(payer), **override})
        assert (response.response_status, response.response_json["code"]) == (status, code), override

    payload = pix_payload(payer)
    payload["destination_account"]["document_number"] = "11144477700"
    response = post_pix(payload)
    assert (response.response_status, response.response_json["code"]) == (422, "AFP000005")


def test_token_and_not_found_use_afp_codes():
    response = api_request("GET", "/pix/transaction/does-not-exist", token=False)
    assert (response.response_status, response.response_json["code"]) == (403, "AFP000002")

    response = api_request("GET", "/pix/transaction/does-not-exist")
    assert (response.response_status, response.response_json["code"]) == (404, "AFP000003")


def test_feedback_is_recorded_for_existing_analysis():
    payload = pix_payload(create_payer(with_contact=False), channel="celular")
    post_pix(payload)

    response = api_request("POST", "/pix/feedback", {"transaction_id": payload["id"], "is_fraud": True, "reason": "golpe"})
    assert response.response_status == 201, response.response_json

    missing = api_request("POST", "/pix/feedback", {"transaction_id": "nope", "is_fraud": False})
    assert missing.response_status == 404
