from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import CustomerDTO
from errors import DuplicateCustomer, InvalidCustomerDocument, NotFoundCustomer
from repositories import BankRepository
from utils.document_number import is_valid_document_number
from utils.identifiers import parse_uuid


class CustomerController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = BankRepository(self.session)

    def create(self, payload: dict) -> dict:
        if not is_valid_document_number(payload["document_number"]):
            raise InvalidCustomerDocument()

        if (
            self.repository.get_customer_by_document(payload["document_number"]) is not None
            or self.repository.get_customer_by_email(payload["email"]) is not None
        ):
            raise DuplicateCustomer()

        customer = self.repository.create_customer(payload)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            if (
                self.repository.get_customer_by_document(payload["document_number"]) is not None
                or self.repository.get_customer_by_email(payload["email"]) is not None
            ):
                raise DuplicateCustomer() from None
            raise

        response = CustomerDTO.to_dict(customer)
        self.session.commit()
        return response

    def get_by_key(self, customer_key: str) -> dict:
        customer = self.repository.get_customer_by_key(parse_uuid(customer_key, "customer_key"))
        if customer is None:
            raise NotFoundCustomer()
        return CustomerDTO.to_dict(customer)
