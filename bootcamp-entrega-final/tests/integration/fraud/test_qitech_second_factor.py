from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.utils.qitech_mock import QiTechMock


PAYER_CPF = "529.982.247-25"
CONTACT_CPF = "111.444.777-35"
QI_ACCOUNT_KEY = "11111111-2222-4333-8444-555555555555"
TRANSFER = {"pix_transfer_type": "key", "target_pix_key": "neto@example.com", "end_to_end_id": "E" + "7" * 31}


@pytest.fixture
def qi(monkeypatch):
    mock = QiTechMock().start()
    monkeypatch.setenv("QITECH_API_URL", mock.url)
    monkeypatch.setenv("QITECH_TIMEOUT_S", "2")
    yield mock
    mock.stop()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import constants
    from app import create_app

    with TestClient(create_app()) as test_client:
        test_client.headers["INTERNAL-TOKEN"] = constants.INTERNAL_TOKEN
        yield test_client


def held_pix(client, **source) -> str:
    pix_id = str(uuid4())
    response = client.post("/pix/transaction", json={
        "id": pix_id,
        "amount": 45000,
        "transaction_date": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "source_account": {"document_number": PAYER_CPF},
        "destination_account": {"document_number": CONTACT_CPF, "participant": "60701190", "branch": "0001",
                                "number": "778899"},
        "source": {"channel": "celular", "device_id": "cel-maria", "call_in_progress": True, **source},
    })
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "two_factor_required"
    assert response.json()["metadata"]["challenge_type"] == "CUSTOMER_TOKEN_2FA"
    return pix_id


def open_challenge(client, pix_id: str, approver: str = PAYER_CPF):
    return client.post(f"/pix/transaction/{pix_id}/second_factor", json={
        "qi_account_key": QI_ACCOUNT_KEY,
        "approver": {"document_number": approver, "contact_type": "sms"},
        "transfer": TRANSFER,
    })


def confirm(client, pix_id: str, token: str, **extra):
    return client.put(f"/pix/transaction/{pix_id}/second_factor/token", json={"token": token, **extra})


def stored(session, pix_id: str) -> dict:
    row = session.execute(text(
        "SELECT a.status, sf.qi_pix_transfer_key, sf.qi_transfer_status, sf.qi_account_key, "
        "sf.challenge_expires_at, sf.second_factor_at "
        "FROM fraude.pix_analysis a "
        "LEFT JOIN fraude.pix_second_factor sf ON sf.analysis_id = a.id "
        "WHERE a.pix_id = :id"
    ), {"id": pix_id}).mappings().one()
    return dict(row)


def rules(session, pix_id: str) -> list[str]:
    return [code for (code,) in session.execute(text(
        "SELECT r.rule_code FROM fraude.pix_rule_result r JOIN fraude.pix_analysis a ON a.id = r.analysis_id "
        "WHERE a.pix_id = :id ORDER BY r.id"
    ), {"id": pix_id})]


def test_open_challenge_stores_pix_transfer_key(client, qi, session):
    pix_id = held_pix(client)

    response = open_challenge(client, pix_id)

    assert response.status_code == 201, response.json()
    second_factor = response.json()["second_factor"]
    assert second_factor["provider_status"] == "pending_2fa_approval"
    assert second_factor["contact_type"] == "sms"
    row = stored(session, pix_id)
    assert str(row["qi_pix_transfer_key"]) == second_factor["pix_transfer_key"]
    assert str(row["qi_account_key"]) == QI_ACCOUNT_KEY
    assert row["challenge_expires_at"] is not None

    sent = qi.calls("pix_transfer")[0]["body"]
    assert sent["transaction_amount"] == 450.0
    assert sent["tfa_info"]["approver_document_number"] == "52998224725"

    again = open_challenge(client, pix_id)
    assert again.status_code == 200
    assert again.json()["second_factor"]["pix_transfer_key"] == second_factor["pix_transfer_key"]
    assert len(qi.calls("pix_transfer")) == 1


def test_wrong_then_right_token_approves_pix(client, qi, session):
    pix_id = held_pix(client)
    open_challenge(client, pix_id)

    wrong = confirm(client, pix_id, "ZZZZZZ")
    assert (wrong.status_code, wrong.json()["code"]) == (422, "AFP000011")

    right = confirm(client, pix_id, qi.token, friction_answer="NO")
    assert right.status_code == 200, right.json()
    assert right.json()["status"] == "approved"
    assert right.json()["second_factor"]["provider_status"] == "sent"
    assert right.json()["second_factor"]["completed_at"] is not None
    assert client.get(f"/pix/transaction/{pix_id}").json()["status"] == "approved"
    assert stored(session, pix_id)["second_factor_at"] is not None


def test_five_wrong_tokens_reject_the_pix(client, qi, session):
    pix_id = held_pix(client)
    open_challenge(client, pix_id)

    for _ in range(4):
        assert confirm(client, pix_id, "ZZZZZZ").json()["code"] == "AFP000011"
    last = confirm(client, pix_id, "ZZZZZZ")

    assert (last.status_code, last.json()["code"]) == (422, "AFP000013")
    row = stored(session, pix_id)
    assert (row["status"], row["qi_transfer_status"]) == ("rejected", "rejected")
    assert rules(session, pix_id)[-1] == "QI2FA"


def test_friction_yes_without_contact_rejects_without_calling_qi(client, qi, session):
    pix_id = held_pix(client)
    open_challenge(client, pix_id)

    response = confirm(client, pix_id, qi.token, friction_answer="YES")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert qi.calls("validate_token") == []
    assert rules(session, pix_id)[-1] == "ESCALATION"


def test_expired_token_is_resent(client, qi):
    pix_id = held_pix(client)
    key = open_challenge(client, pix_id).json()["second_factor"]["pix_transfer_key"]
    qi.expire(key)

    expired = confirm(client, pix_id, qi.token)
    assert (expired.status_code, expired.json()["code"]) == (422, "AFP000012")

    resent = client.patch(f"/pix/transaction/{pix_id}/second_factor/token")
    assert resent.status_code == 200
    assert confirm(client, pix_id, qi.token).json()["status"] == "approved"


def test_approver_must_match_challenge_type(client, qi):
    pix_id = held_pix(client)

    other_person = open_challenge(client, pix_id, approver=CONTACT_CPF)
    assert (other_person.status_code, other_person.json()["code"]) == (422, "AFP000016")

    invalid_cpf = open_challenge(client, pix_id, approver="111.444.777-00")
    assert (invalid_cpf.status_code, invalid_cpf.json()["code"]) == (422, "AFP000005")

    qi.approvers = {"11144477735"}
    not_registered = open_challenge(client, pix_id)
    assert (not_registered.status_code, not_registered.json()["code"]) == (422, "AFP000016")
    assert qi.calls("pix_transfer")


def test_provider_outage_keeps_pix_on_hold(client, qi, session):
    pix_id = held_pix(client)
    qi.unavailable = True

    response = open_challenge(client, pix_id)

    assert (response.status_code, response.json()["code"]) == (503, "AFP000014")
    assert stored(session, pix_id)["status"] == "two_factor_required"


def test_second_factor_only_for_held_pix(client, qi):
    pix_id = held_pix(client)
    open_challenge(client, pix_id)
    confirm(client, pix_id, qi.token)

    reopen = open_challenge(client, pix_id)
    assert (reopen.status_code, reopen.json()["code"]) == (409, "AFP000010")

    unknown = confirm(client, "nao-existe", qi.token)
    assert (unknown.status_code, unknown.json()["code"]) == (404, "AFP000003")

    bad_token = confirm(client, pix_id, "12")
    assert (bad_token.status_code, bad_token.json()["code"]) == (400, "AFP000001")
