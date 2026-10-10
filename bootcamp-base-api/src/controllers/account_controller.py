import re

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import AccountDTO, TrustedContactDTO
from errors import (
    CustomerAlreadyHasAccount,
    DuplicateTrustedContact,
    InvalidMCCList,
    InvalidTransferLimit,
    NotFoundAccount,
    NotFoundCustomer,
    TrustedContactLimitReached,
)
from repositories import BankRepository
from utils.identifiers import parse_uuid


class AccountController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = BankRepository(self.session)

    def create(self, payload: dict) -> dict:
        transfer_limit_cents = payload.get("transfer_limit_cents", 100000)
        if transfer_limit_cents < 1:
            raise InvalidTransferLimit()

        customer = self.repository.get_customer_by_key(
            parse_uuid(payload["customer_key"], "customer_key")
        )
        if customer is None:
            raise NotFoundCustomer()

        if self.repository.get_account_by_customer_id(customer.id) is not None:
            raise CustomerAlreadyHasAccount()

        account = self.repository.create_account(customer, transfer_limit_cents)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            if self.repository.get_account_by_customer_id(customer.id) is not None:
                raise CustomerAlreadyHasAccount() from None
            raise

        response = AccountDTO.to_dict(account)
        self.session.commit()
        return response

    def get_by_key(self, account_key: str) -> dict:
        account = self.repository.get_account_by_key(parse_uuid(account_key, "account_key"))
        if account is None:
            raise NotFoundAccount()
        return AccountDTO.to_dict(account)

    def replace_blocked_mccs(self, account_key: str, mcc_list: list[str]) -> dict:
        if any(re.fullmatch(r"\d{4}", mcc) is None for mcc in mcc_list):
            raise InvalidMCCList()

        account = self.repository.get_account_by_key(parse_uuid(account_key, "account_key"))
        if account is None:
            raise NotFoundAccount()

        account = self.repository.get_account_for_update(account.id)
        if account is None:
            raise NotFoundAccount()

        normalized_mccs = sorted(set(mcc_list))
        self.repository.replace_blocked_mccs(account, normalized_mccs)
        self.session.flush()
        response = {
            "account_key": str(account.account_key),
            "mcc_list": normalized_mccs,
        }
        self.session.commit()
        return response

    def add_trusted_contact(self, account_key: str, payload: dict) -> dict:
        account = self.repository.get_account_by_key(parse_uuid(account_key, "account_key"))
        if account is None:
            raise NotFoundAccount()

        account = self.repository.get_account_for_update(account.id)
        if account is None:
            raise NotFoundAccount()

        if self.repository.count_trusted_contacts(account.id) >= 2:
            raise TrustedContactLimitReached()

        if any(contact.address == payload["address"] for contact in account.trusted_contacts):
            raise DuplicateTrustedContact()

        contact = self.repository.create_trusted_contact(account, payload)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            raise DuplicateTrustedContact() from None

        response = TrustedContactDTO.to_dict(contact)
        self.session.commit()
        return response
