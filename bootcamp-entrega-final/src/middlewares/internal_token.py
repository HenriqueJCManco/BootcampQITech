import hmac

from fastapi import FastAPI, Request

from constants import BYPASS_ENDPOINTS, INTERNAL_TOKEN
from errors.base_error import ForbiddenNotInternal
from errors.fraud_errors import PixForbidden
from errors.handlers import qi_exception_to_response


PIX_PREFIX = "/pix/"


def is_valid_token(received: str | None) -> bool:
    if received is None or not INTERNAL_TOKEN:
        return False
    return hmac.compare_digest(received.encode("utf-8"), INTERNAL_TOKEN.encode("utf-8"))


def register_internal_token_middleware(application: FastAPI) -> None:
    @application.middleware("http")
    async def check_internal_token(request: Request, call_next):
        is_public = request.url.path in BYPASS_ENDPOINTS

        if request.method == "OPTIONS" or is_public:
            return await call_next(request)

        if not is_valid_token(request.headers.get("INTERNAL-TOKEN")):
            if request.url.path.startswith(PIX_PREFIX):
                return qi_exception_to_response(PixForbidden())
            return qi_exception_to_response(ForbiddenNotInternal())

        return await call_next(request)
