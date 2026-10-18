from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text

from domain.identity import destination_key
from tests.utils import INTERNAL_TOKEN, RandomGenerator
from tests.utils.requisition import ClientRequisition


def api_request(method, endpoint, payload=None, token=True):
    headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN} if token else {}
    return ClientRequisition.send(method, endpoint, payload=payload, headers=headers)


def test_scenario_routine_happy_path():
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    payer_cpf = RandomGenerator.generate_cpf()
    dest_cpf = RandomGenerator.generate_cpf()

    payload = {
        "id": f"PIX-ROUTINE-{uuid4().hex[:8]}",
        "amount": 2500,
        "transaction_date": now.isoformat(),
        "type": "payment",
        "source": {
            "channel": "celular",
            "device_id": "device-trusted-home-001",
        },
        "source_account": {
            "document_number": payer_cpf,
            "owner": {"name": "Cliente Comum"},
        },
        "destination_account": {
            "document_number": dest_cpf,
            "owner": {"name": "Padaria Confiavel"},
        },
    }

    resp = api_request("POST", "/pix/transaction", payload)
    assert resp.response_status == 201
    assert resp.response_json["status"] == "approved"
    assert "score" not in resp.response_json
    assert "rules_fired" not in resp.response_json


def test_scenario_quarantine_destination_blocked(session):
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    payer_cpf = RandomGenerator.generate_cpf()
    mula_cpf = RandomGenerator.generate_cpf()

    mula_key = destination_key("BANCO60", "0001", "", mula_cpf)
    session.execute(
        text(
            """
            INSERT INTO fraude.destination_flag (destination_key, status, reason, starts_at, expires_at)
            VALUES (:key, 'QUARENTENA', 'Alerta policial de conta receptora', NOW() - interval '1 hour', NOW() + interval '48 hours')
            """
        ),
        {"key": mula_key},
    )
    session.commit()

    payload = {
        "id": f"PIX-QUARENTENA-{uuid4().hex[:8]}",
        "amount": 15000,
        "transaction_date": now.isoformat(),
        "type": "payment",
        "source": {
            "channel": "celular",
            "device_id": "device-regular-002",
        },
        "source_account": {
            "document_number": payer_cpf,
            "owner": {"name": "Cliente Vitima"},
        },
        "destination_account": {
            "document_number": mula_cpf,
            "owner": {"name": "Receptor Marcado"},
        },
    }

    resp = api_request("POST", "/pix/transaction", payload)
    assert resp.response_status == 201
    assert resp.response_json["status"] == "rejected"
    assert resp.response_json.get("metadata", {}).get("customer_message_key") == "BLOCKED_FOR_SAFETY"


def test_scenario_second_factor_flow():
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    pix_id = f"PIX-2FA-FLOW-{uuid4().hex[:8]}"
    payer_cpf = RandomGenerator.generate_cpf()
    dest_cpf = RandomGenerator.generate_cpf()

    payload = {
        "id": pix_id,
        "amount": 30000,
        "transaction_date": now.isoformat(),
        "type": "payment",
        "second_factor_passed": False,
        "source": {
            "channel": "celular",
            "device_id": "device-novo-003",
            "call_in_progress": True,
        },
        "source_account": {
            "document_number": payer_cpf,
            "has_trusted_contact": False,
            "owner": {"name": "Carlos Eduardo"},
        },
        "destination_account": {
            "document_number": dest_cpf,
            "owner": {"name": "Loja Desconhecida"},
        },
    }

    resp1 = api_request("POST", "/pix/transaction", payload)
    assert resp1.response_status == 201
    assert resp1.response_json["status"] == "two_factor_required"
    assert "challenge_type" in resp1.response_json["metadata"]

    payload["second_factor_passed"] = True
    payload["friction_answer"] = "NO"
    resp2 = api_request("POST", "/pix/transaction", payload)
    assert resp2.response_status == 200
    assert resp2.response_json["status"] == "approved"


def test_scenario_mei_protected_at_night():
    night_time = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=23, minute=15)
    pix_id = f"PIX-MEI-NIGHT-{uuid4().hex[:8]}"

    payload = {
        "id": pix_id,
        "amount": 300000,
        "transaction_date": night_time.isoformat(),
        "type": "payment",
        "source": {
            "channel": "celular",
            "device_id": "device-mei-001",
        },
        "source_account": {
            "document_number": "11222333000181",
            "owner": {"name": "JOAO DA SILVA 52998224725"},
        },
        "destination_account": {
            "document_number": RandomGenerator.generate_cpf(),
            "owner": {"name": "Fornecedor da Madrugada"},
        },
    }

    resp = api_request("POST", "/pix/transaction", payload)
    assert resp.response_status == 201
    assert resp.response_json["status"] == "rejected"
    assert resp.response_json.get("metadata", {}).get("customer_message_key") == "BLOCKED_FOR_SAFETY"


def test_scenario_robotic_movement_escalation():
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    pix_id = f"PIX-BOT-{uuid4().hex[:8]}"

    payload = {
        "id": pix_id,
        "amount": 95000,
        "transaction_date": now.isoformat(),
        "type": "payment",
        "source": {
            "channel": "computador",
            "device_id": "device-headless-chrome-01",
            "interaction": {
                "is_robotic_movement": True,
                "typing_cadence_std_ms": 5.0,
                "session_idle_then_burst": True,
            },
        },
        "source_account": {
            "document_number": RandomGenerator.generate_cpf(),
            "owner": {"name": "Carlos Eduardo"},
        },
        "destination_account": {
            "document_number": RandomGenerator.generate_cpf(),
            "owner": {"name": "Destino Bot"},
        },
    }

    resp = api_request("POST", "/pix/transaction", payload)
    assert resp.response_status == 201
    assert resp.response_json["status"] in ("rejected", "two_factor_required")
