from fastapi import FastAPI

from constants import check_variables
from errors import register_error_handlers
from errors.base_error import error_verification
from middlewares import (
    register_internal_token_middleware,
    register_request_context_middleware,
    register_request_logger_middleware,
    register_session_manager_middleware,
)
from resources import AccountResource, CustomerResource, HealthCheckResource, PixResource, TransferResource
from utils.logger import setup_logging


def create_app() -> FastAPI:
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    register_session_manager_middleware(application)
    register_internal_token_middleware(application)
    register_request_logger_middleware(application)
    register_request_context_middleware(application)

    health = HealthCheckResource()
    customer = CustomerResource()
    account = AccountResource()
    transfer = TransferResource()
    pix = PixResource()

    application.add_api_route("/", health.on_get_home, methods=["GET"])
    application.add_api_route("/health_check", health.on_get_health_check, methods=["GET"])
    application.add_api_route("/customer", customer.on_post, methods=["POST"])
    application.add_api_route("/customer/{customer_key}", customer.on_get_by_key, methods=["GET"])
    application.add_api_route("/account", account.on_post, methods=["POST"])
    application.add_api_route("/account/{account_key}", account.on_get_by_key, methods=["GET"])
    application.add_api_route(
        "/account/{account_key}/blocked_mcc",
        account.on_put_blocked_mcc,
        methods=["PUT"],
    )
    application.add_api_route(
        "/account/{account_key}/trusted_contact",
        account.on_post_trusted_contact,
        methods=["POST"],
    )
    application.add_api_route(
        "/account/{account_key}/deposit",
        account.on_post_deposit,
        methods=["POST"],
    )
    application.add_api_route(
        "/account/{account_key}/purchase",
        account.on_post_purchase,
        methods=["POST"],
    )
    application.add_api_route("/transfer", transfer.on_post, methods=["POST"])
    application.add_api_route(
        "/account/{account_key}/statement",
        account.on_get_statement,
        methods=["GET"],
    )
    application.add_api_route("/pix/transaction", pix.on_post_transaction, methods=["POST"])
    application.add_api_route("/pix/transaction/{id}", pix.on_get_transaction, methods=["GET"])
    application.add_api_route("/pix/feedback", pix.on_post_feedback, methods=["POST"])
    application.add_api_route("/pix/transaction/{id}/second_factor", pix.on_post_second_factor, methods=["POST"])
    application.add_api_route(
        "/pix/transaction/{id}/second_factor/token", pix.on_put_second_factor_token, methods=["PUT"]
    )
    application.add_api_route(
        "/pix/transaction/{id}/second_factor/token", pix.on_patch_second_factor_token, methods=["PATCH"]
    )

    register_error_handlers(application)
    return application


def main() -> FastAPI:
    check_variables()
    error_verification()
    setup_logging()
    return create_app()


app = main()
