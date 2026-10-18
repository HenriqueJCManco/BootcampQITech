from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import AvaliarPixController, PixSecondFactorController
from utils.pix_validation import pix_schema_error
from utils.schema_handler import SchemaHandler


class PixResource:
    @SchemaHandler.validate("post_pix_transaction.json", error_mapper=pix_schema_error)
    def on_post_transaction(self, payload: dict) -> JSONResponse:
        result, replayed = AvaliarPixController().avaliar(payload)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )

    @SchemaHandler.validate_query_params("get_pix_transaction.json")
    def on_get_transaction(self, id: str, request: Request) -> JSONResponse:
        result = AvaliarPixController().get_by_id(id)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=status.HTTP_200_OK,
        )

    @SchemaHandler.validate("post_pix_feedback.json", error_mapper=pix_schema_error)
    def on_post_feedback(self, payload: dict) -> JSONResponse:
        result = AvaliarPixController().register_feedback(payload)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=status.HTTP_201_CREATED,
        )

    @SchemaHandler.validate("post_pix_second_factor.json", error_mapper=pix_schema_error)
    def on_post_second_factor(self, id: str, payload: dict) -> JSONResponse:
        result, created = PixSecondFactorController().open_challenge(id, payload)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @SchemaHandler.validate("put_pix_second_factor_token.json", error_mapper=pix_schema_error)
    def on_put_second_factor_token(self, id: str, payload: dict) -> JSONResponse:
        result = PixSecondFactorController().confirm_token(id, payload)
        return JSONResponse(content=jsonable_encoder(result), status_code=status.HTTP_200_OK)

    def on_patch_second_factor_token(self, id: str) -> JSONResponse:
        result = PixSecondFactorController().resend_token(id)
        return JSONResponse(content=jsonable_encoder(result), status_code=status.HTTP_200_OK)
