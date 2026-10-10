from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import create_engine, text

from tests.utils import DbUtils, INTERNAL_TOKEN, RandomGenerator
from tests.utils.requisition import ClientRequisition


def api_request(method, endpoint, payload=None, key=None, query_params=None, token=True):
    headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN} if token else {}
    if key is not None:
        headers["Idempotency-Key"] = key
    return ClientRequisition.send(
        method,
        endpoint,
        payload=payload,
        headers=headers,
        query_params=query_params,
    )


def create_account():
    customer_payload = {
        "name": "Pessoa de Teste",
        "email": f"{uuid4()}@example.test",
        "document_number": RandomGenerator.generate_cpf(),
    }
    response = api_request("POST", "/customer", customer_payload)
    assert response.response_status == 201, response.response_json

    account_response = api_request(
        "POST",
        "/account",
        {"customer_key": response.response_json["customer_key"]},
    )
    assert account_response.response_status == 201, account_response.response_json
    return account_response.response_json


def test_customer_account_and_trusted_contact_contract():
    account = create_account()
    assert account["balance_cents"] == 0
    assert account["transfer_limit_cents"] == 100000
    assert account["blocked_mcc_list"] == ["7995"]

    for index in range(2):
        response = api_request(
            "POST",
            f"/account/{account['account_key']}/trusted_contact",
            {
                "name": f"Contato {index}",
                "channel": "EMAIL",
                "address": f"{uuid4()}@example.test",
            },
        )
        assert response.response_status == 201

    response = api_request(
        "POST",
        f"/account/{account['account_key']}/trusted_contact",
        {"name": "Terceiro", "channel": "EMAIL", "address": "third@example.test"},
    )
    assert response.response_status == 409
    assert response.response_json["code"] == "BNK003001"


def test_concurrent_trusted_contacts_respect_account_limit():
    account = create_account()

    def add_contact(index):
        return api_request(
            "POST",
            f"/account/{account['account_key']}/trusted_contact",
            {
                "name": f"Concorrente {index}",
                "channel": "EMAIL",
                "address": f"{uuid4()}@example.test",
            },
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        responses = list(executor.map(add_contact, range(3)))

    assert sum(response.response_status == 201 for response in responses) == 2
    rejected = [response for response in responses if response.response_status == 409]
    assert len(rejected) == 1
    assert rejected[0].response_json["code"] == "BNK003001"


def test_deposit_idempotency_and_statement_replay():
    account = create_account()
    endpoint = f"/account/{account['account_key']}/deposit"
    payload = {"amount_cents": 2500}
    key = str(uuid4())

    first = api_request("POST", endpoint, payload, key)
    replay = api_request("POST", endpoint, payload, key)
    assert first.response_status == 201
    assert replay.response_status == 200
    assert replay.response_json == first.response_json

    changed_payload = {"amount_cents": 3000}
    conflict = api_request("POST", endpoint, changed_payload, key)
    assert conflict.response_status == 409
    assert conflict.response_json["code"] == "BNK000012"

    statement = api_request(
        "GET",
        f"/account/{account['account_key']}/statement",
        query_params={"limit": "10", "page": "0"},
    )
    assert statement.response_status == 200
    assert statement.response_json["balance_cents"] == 2500
    assert len(statement.response_json["data"]) == 1
    assert statement.response_json["data"][0]["kind"] == "DEPOSIT"


def test_concurrent_replays_apply_deposit_once():
    account = create_account()
    endpoint = f"/account/{account['account_key']}/deposit"
    payload = {"amount_cents": 1250}
    key = str(uuid4())

    def deposit(_):
        return api_request("POST", endpoint, payload, key)

    with ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(deposit, range(5)))

    assert sum(response.response_status == 201 for response in responses) == 1
    assert sum(response.response_status == 200 for response in responses) == 4
    assert all(response.response_json == responses[0].response_json for response in responses)

    current = api_request("GET", f"/account/{account['account_key']}")
    assert current.response_json["balance_cents"] == 1250


def test_statement_rejects_non_uuid_account_key():
    response = api_request(
        "GET",
        "/account/not-a-uuid/statement",
        query_params={"limit": "10", "page": "0"},
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "BNK000001"


def test_purchase_checks_registered_merchant_mcc_and_releases_failed_key():
    account = create_account()
    cnpj = RandomGenerator.generate_cnpj()
    engine = create_engine(DbUtils.database_url())
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO merchant (document_number, name, mcc) VALUES (:document, :name, :mcc)"),
                {"document": cnpj, "name": "Merchant test", "mcc": "7995"},
            )
    finally:
        engine.dispose()

    deposit = api_request(
        "POST",
        f"/account/{account['account_key']}/deposit",
        {"amount_cents": 1000},
        str(uuid4()),
    )
    assert deposit.response_status == 201

    endpoint = f"/account/{account['account_key']}/purchase"
    payload = {
        "amount_cents": 500,
        "mcc": "5411",
        "merchant_document_number": cnpj,
    }
    key = str(uuid4())
    blocked = api_request("POST", endpoint, payload, key)
    assert blocked.response_status == 422
    assert blocked.response_json["code"] == "BNK004004"

    updated = api_request(
        "PUT",
        f"/account/{account['account_key']}/blocked_mcc",
        {"mcc_list": []},
    )
    assert updated.response_status == 200

    retried = api_request("POST", endpoint, payload, key)
    assert retried.response_status == 201
    assert retried.response_json["balance_cents"] == 500


def test_transfer_is_atomic_and_serializes_competing_requests():
    source = create_account()
    destination = create_account()
    deposit = api_request(
        "POST",
        f"/account/{source['account_key']}/deposit",
        {"amount_cents": 1000},
        str(uuid4()),
    )
    assert deposit.response_status == 201

    def transfer(index):
        return api_request(
            "POST",
            "/transfer",
            {
                "from_account_key": source["account_key"],
                "to_account_key": destination["account_key"],
                "amount_cents": 100,
            },
            f"concurrent-{index}-{uuid4()}",
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        responses = list(executor.map(transfer, range(10)))

    assert sum(response.response_status == 201 for response in responses) == 5
    assert sum(response.response_status == 409 for response in responses) == 5
    assert all(
        response.response_json["code"] == "BNK004001"
        for response in responses
        if response.response_status == 409
    )

    source_result = api_request("GET", f"/account/{source['account_key']}")
    destination_result = api_request("GET", f"/account/{destination['account_key']}")
    assert source_result.response_json["balance_cents"] == 0
    assert destination_result.response_json["balance_cents"] == 500


def test_missing_idempotency_key_and_validation_errors_are_safe():
    account = create_account()
    missing_key = api_request(
        "POST",
        f"/account/{account['account_key']}/deposit",
        {"amount_cents": 10},
    )
    assert missing_key.response_status == 400
    assert missing_key.response_json["code"] == "BNK000011"
    assert missing_key.response_json["request_id"]
    assert isinstance(missing_key.response_json["errors"], list)

    invalid = api_request(
        "POST",
        "/customer",
        {
            "name": "Test",
            "email": "private-address",
            "document_number": RandomGenerator.generate_cpf(),
        },
    )
    assert invalid.response_status == 400
    assert invalid.response_json["code"] == "BNK000001"
    assert "private-address" not in str(invalid.response_json)
