from fastapi import status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import CustomerController
from utils.schema_handler import SchemaHandler


class CustomerResource:
    @SchemaHandler.validate("post_customer.json")
    def on_post(self, payload: dict) -> JSONResponse:
        customer = CustomerController().create(payload)
        return JSONResponse(
            content=jsonable_encoder(customer),
            status_code=status.HTTP_201_CREATED,
        )

    def on_get_by_key(self, customer_key: str) -> JSONResponse:
        customer = CustomerController().get_by_key(customer_key)
        return JSONResponse(
            content=jsonable_encoder(customer),
            status_code=status.HTTP_200_OK,
        )
