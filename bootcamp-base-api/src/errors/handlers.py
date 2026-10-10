from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from errors.base_error import (
    QIException,
    InternalError,
    InvalidSchema,
    MethodNotAllowed,
    NotFoundResource,
)
from utils.request_context import get_request_id
from utils.logger import get_logger


logger = get_logger(__name__)


def qi_exception_to_response(exception: QIException) -> JSONResponse:
    """Traduz um erro nosso para a resposta JSON que o cliente recebe.

    Este é o único lugar do projeto que sabe como um erro vira HTTP.
    Trocar de framework significa reescrever esta função — e mais nada.
    """
    body = {
        "title": exception.title,
        "description": exception.description,
        "translation": exception.translation,
        "code": exception.code,
        "request_id": get_request_id(),
        "errors": exception.errors,
    }
    return JSONResponse(status_code=exception.http_status, content=body)


def describe_validation_error(error: dict) -> str:
    return "The request contains an invalid value."


def validation_details(error: dict) -> list[dict]:
    location = [str(part) for part in error.get("loc", []) if part not in ("body", "query")]
    field = ".".join(location)
    rule = str(error.get("type", "invalid"))
    messages = {
        "missing": "Field is required.",
        "extra_forbidden": "Field is not allowed.",
        "string_type": "Value must be a string.",
        "int_type": "Value must be an integer.",
        "value_error": "Value is invalid.",
    }
    return [{"field": field, "rule": rule, "message": messages.get(rule, "Value is invalid.")}]


def register_error_handlers(application: FastAPI) -> None:
    """Ensina a aplicação a responder cada tipo de erro."""

    @application.exception_handler(QIException)
    def handle_qi_exception(request: Request, exception: QIException) -> JSONResponse:
        return qi_exception_to_response(exception)

    @application.exception_handler(StarletteHTTPException)
    def handle_http_exception(request: Request, exception: StarletteHTTPException) -> JSONResponse:
        if exception.status_code == 404:
            return qi_exception_to_response(NotFoundResource())

        if exception.status_code == 405:
            return qi_exception_to_response(MethodNotAllowed())

        logger.error(f"HTTP {exception.status_code} em {request.url.path}: {exception.detail}")
        return qi_exception_to_response(InternalError())

    @application.exception_handler(RequestValidationError)
    def handle_validation_error(request: Request, exception: RequestValidationError) -> JSONResponse:
        errors = exception.errors()

        if errors:
            first_error = errors[0]
        else:
            first_error = {}

        return qi_exception_to_response(
            InvalidSchema(describe_validation_error(first_error), validation_details(first_error))
        )

    @application.exception_handler(Exception)
    def handle_unexpected_error(request: Request, exception: Exception) -> JSONResponse:
        logger.exception(f"Erro inesperado em {request.method} {request.url.path}")
        return qi_exception_to_response(InternalError())
