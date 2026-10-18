import uuid

import pytest

from connectors import QITechConnector, QiTechError, QiTechUnavailable
from connectors.qitech_connector import cents_to_reais
from tests.utils.qitech_mock import QiTechMock


ACCOUNT_KEY = "11111111-2222-4333-8444-555555555555"
APPROVER = "52998224725"
TRANSFER = {"pix_transfer_type": "key", "target_pix_key": "neto@example.com", "end_to_end_id": "E" + "1" * 31}


@pytest.fixture
def qi():
    mock = QiTechMock().start()
    yield mock
    mock.stop()


@pytest.fixture
def connector(qi):
    return QITechConnector(base_url=qi.url, api_key="chave-de-teste", timeout=2)


def request(connector, amount_cents=123456):
    return connector.request_pix_transfer_2fa(
        ACCOUNT_KEY, str(uuid.uuid4()), amount_cents, TRANSFER, APPROVER, "sms"
    )


@pytest.mark.parametrize("cents, reais", [(1, 0.01), (50065, 500.65), (100000, 1000.0), (123456, 1234.56)])
def test_cents_are_sent_as_reais_with_two_decimals(cents, reais):
    assert cents_to_reais(cents) == reais


def test_request_opens_transfer_waiting_for_token(qi, connector):
    transfer = request(connector)

    assert transfer.status == "pending_2fa_approval"
    sent = qi.calls("pix_transfer")[0]
    assert sent["path"] == f"/account/{ACCOUNT_KEY}/pix_transfer"
    assert sent["body"]["transaction_amount"] == 1234.56
    assert sent["body"]["tfa_info"] == {"approver_document_number": APPROVER, "contact_type": "sms"}
    assert sent["body"]["target_pix_key"] == "neto@example.com"
    assert sent["headers"]["API-CLIENT-KEY"] == "chave-de-teste"
    assert "INTERNAL-TOKEN" not in sent["headers"]


def test_correct_token_completes_transfer(qi, connector):
    transfer = request(connector)

    validated = connector.validate_token(ACCOUNT_KEY, transfer.pix_transfer_key, qi.token)

    assert validated.status == "sent"
    assert validated.end_to_end_id == transfer.end_to_end_id


def test_asynchronous_completion_returns_pending(qi, connector):
    qi.completion_status = "pending"
    transfer = request(connector)

    assert connector.validate_token(ACCOUNT_KEY, transfer.pix_transfer_key, qi.token).status == "pending"


def test_wrong_token_raises_incorrect_and_fifth_rejects(qi, connector):
    transfer = request(connector)

    for attempt in range(4):
        with pytest.raises(QiTechError) as error:
            connector.validate_token(ACCOUNT_KEY, transfer.pix_transfer_key, "ZZZZZZ")
        assert error.value.code == "PXT000173"

    with pytest.raises(QiTechError) as error:
        connector.validate_token(ACCOUNT_KEY, transfer.pix_transfer_key, "ZZZZZZ")
    assert error.value.code == "PXT000171"
    assert error.value.transfer.status == "rejected"


def test_expired_token_can_be_resent(qi, connector):
    transfer = request(connector)
    qi.expire(transfer.pix_transfer_key)

    with pytest.raises(QiTechError) as error:
        connector.validate_token(ACCOUNT_KEY, transfer.pix_transfer_key, qi.token)
    assert error.value.code == "PXT000172"

    assert connector.resend_token(ACCOUNT_KEY, transfer.pix_transfer_key).status == "pending_2fa_approval"
    assert connector.validate_token(ACCOUNT_KEY, transfer.pix_transfer_key, qi.token).status == "sent"


def test_approver_without_permission_is_refused(qi, connector):
    qi.approvers = {"11144477735"}

    with pytest.raises(QiTechError) as error:
        request(connector)

    assert error.value.code == "PXT000168"


def test_provider_outage_and_network_errors_are_unavailable(qi, connector):
    qi.unavailable = True
    with pytest.raises(QiTechUnavailable):
        request(connector)

    offline = QITechConnector(base_url="http://127.0.0.1:9", timeout=1)
    with pytest.raises(QiTechUnavailable):
        request(offline)
