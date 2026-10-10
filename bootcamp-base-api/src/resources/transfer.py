from typing import Optional

from fastapi import Header, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import TransactionController
from resources.account import require_idempotency_key
from utils.schema_handler import SchemaHandler


class TransferResource:
    @SchemaHandler.validate("post_transfer.json")
    def on_post(
        self,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        key = require_idempotency_key(idempotency_key)
        result, replayed = TransactionController().transfer(key, payload)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )
