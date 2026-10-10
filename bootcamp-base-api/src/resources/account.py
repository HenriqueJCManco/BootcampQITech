from typing import Optional

from fastapi import Header, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import AccountController, TransactionController
from errors import InvalidSchema, MissingIdempotencyKey
from utils.schema_handler import SchemaHandler


MAX_BIGINT = 9223372036854775807


def require_idempotency_key(idempotency_key: Optional[str]) -> str:
    if idempotency_key is None or not idempotency_key.strip():
        raise MissingIdempotencyKey()
    if len(idempotency_key) > 255:
        raise InvalidSchema(
            "Request validation failed.",
            [{"field": "Idempotency-Key", "rule": "maxLength", "message": "Value is too long."}],
        )
    return idempotency_key


class AccountResource:
    @SchemaHandler.validate("post_account.json")
    def on_post(self, payload: dict) -> JSONResponse:
        account = AccountController().create(payload)
        return JSONResponse(
            content=jsonable_encoder(account),
            status_code=status.HTTP_201_CREATED,
        )

    def on_get_by_key(self, account_key: str) -> JSONResponse:
        account = AccountController().get_by_key(account_key)
        return JSONResponse(
            content=jsonable_encoder(account),
            status_code=status.HTTP_200_OK,
        )

    @SchemaHandler.validate("put_blocked_mcc.json")
    def on_put_blocked_mcc(self, account_key: str, payload: dict) -> JSONResponse:
        account = AccountController().replace_blocked_mccs(account_key, payload["mcc_list"])
        return JSONResponse(
            content=jsonable_encoder(account),
            status_code=status.HTTP_200_OK,
        )

    @SchemaHandler.validate("post_trusted_contact.json")
    def on_post_trusted_contact(self, account_key: str, payload: dict) -> JSONResponse:
        contact = AccountController().add_trusted_contact(account_key, payload)
        return JSONResponse(
            content=jsonable_encoder(contact),
            status_code=status.HTTP_201_CREATED,
        )

    @SchemaHandler.validate("post_deposit.json")
    def on_post_deposit(
        self,
        account_key: str,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        key = require_idempotency_key(idempotency_key)
        result, replayed = TransactionController().deposit(account_key, key, payload)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )

    @SchemaHandler.validate("post_purchase.json")
    def on_post_purchase(
        self,
        account_key: str,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        key = require_idempotency_key(idempotency_key)
        result, replayed = TransactionController().purchase(account_key, key, payload)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )

    @SchemaHandler.validate_query_params("get_statement.json")
    def on_get_statement(self, account_key: str, request: Request) -> JSONResponse:
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "0"))
        if page > MAX_BIGINT // limit:
            raise InvalidSchema(
                "Request validation failed.",
                [{"field": "page", "rule": "maximum", "message": "Page is too large."}],
            )
        result = TransactionController().statement(account_key, limit, page)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=status.HTTP_200_OK,
        )
