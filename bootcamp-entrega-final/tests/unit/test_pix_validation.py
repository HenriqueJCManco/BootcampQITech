from datetime import datetime, timedelta, timezone

import pytest

from controllers.avaliar_pix_controller import AvaliarPixController
from errors import (
    PixInvalidAmount,
    PixInvalidChannel,
    PixInvalidDocument,
    PixInvalidSchema,
    PixInvalidTransactionDate,
)
from utils.pix_validation import pix_schema_error
from utils.schema_handler import SchemaHandler


RECENT = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()


@SchemaHandler.validate("post_pix_transaction.json", error_mapper=pix_schema_error)
def validated(payload: dict) -> dict:
    return payload


def payload(**overrides) -> dict:
    body = {
        "id": "pix-1",
        "amount": 1500,
        "transaction_date": RECENT,
        "source_account": {"document_number": "529.982.247-25", "owner": {"name": "Maria"}},
        "destination_account": {"document_number": "11144477735", "participant": "60701190"},
        "source": {"channel": "app", "geolocation": {"latitude": -23.5, "longitude": -46.6}},
    }
    body.update(overrides)
    return body


def test_valid_payload_passes_schema():
    assert validated(payload=payload())["source"]["channel"] == "app"


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"source": {"channel": "smart_tv"}}, PixInvalidChannel),
        ({"amount": 0}, PixInvalidAmount),
        ({"amount": "100"}, PixInvalidAmount),
        ({"unexpected": True}, PixInvalidSchema),
        ({"source_account": {"document_number": "abc"}}, PixInvalidSchema),
    ],
)
def test_schema_errors_map_to_afp_codes(overrides, error):
    with pytest.raises(error):
        validated(payload=payload(**overrides))


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"amount": 10.5}, PixInvalidAmount),
        ({"amount": True}, PixInvalidAmount),
        ({"transaction_date": "2026-10-17T14:00:00"}, PixInvalidTransactionDate),
        ({"transaction_date": "17/10/2026"}, PixInvalidTransactionDate),
        ({"transaction_date": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}, PixInvalidTransactionDate),
        ({"destination_account": {"document_number": "11144477700"}}, PixInvalidDocument),
    ],
)
def test_controller_validation_maps_to_afp_codes(overrides, error):
    with pytest.raises(error):
        AvaliarPixController._validate(payload(**overrides))


def test_app_alias_is_normalized_before_hashing():
    as_app = AvaliarPixController._normalize(payload())
    as_celular = AvaliarPixController._normalize(payload(source={**payload()["source"], "channel": "celular"}))

    assert as_app["source"]["channel"] == "celular"
    assert AvaliarPixController._request_hash(as_app) == AvaliarPixController._request_hash(as_celular)


def test_second_factor_fields_do_not_change_request_hash():
    retry = payload(second_factor_passed=True, friction_answer="NO")

    assert AvaliarPixController._request_hash(retry) == AvaliarPixController._request_hash(payload())
