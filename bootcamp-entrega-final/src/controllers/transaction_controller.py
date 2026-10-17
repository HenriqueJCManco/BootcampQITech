import hashlib
import json

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from controllers.base_controller import BaseController
from dtos import LedgerEntryDTO, TransactionDTO
from errors import (
    BlockedByVault,
    IdempotencyConflict,
    InsufficientFunds,
    InvalidAmount,
    InvalidMerchantDocument,
    LockWaitTimeout,
    NotFoundAccount,
    SameAccountTransfer,
    TransferLimitExceeded,
)
from repositories import BankRepository
from utils.document_number import is_valid_cnpj
from utils.identifiers import parse_uuid


TRANSFER_FEE_CENTS = 100
LOCK_TIMEOUT = "5s"


class TransactionController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = BankRepository(self.session)

    @staticmethod
    def _request_hash(route: str, payload: dict) -> str:
        canonical_request = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{route}\n{canonical_request}".encode("utf-8")).hexdigest()

    def _reserve(
        self,
        *,
        idempotency_key: str,
        route: str,
        payload: dict,
        transaction_type: str,
        amount_cents: int,
        fee_cents: int = 0,
        from_account_id: int | None = None,
        to_account_id: int | None = None,
    ):
        transaction, is_new = self.repository.reserve_transaction(
            idempotency_key=idempotency_key,
            request_hash=self._request_hash(route, payload),
            transaction_type=transaction_type,
            amount_cents=amount_cents,
            fee_cents=fee_cents,
            from_account_id=from_account_id,
            to_account_id=to_account_id,
        )
        if not is_new and transaction.request_hash != self._request_hash(route, payload):
            raise IdempotencyConflict()
        return transaction, is_new

    def _replay(self, transaction) -> dict:
        entries = self.repository.get_replay_entries(transaction.id)
        if not entries:
            raise RuntimeError("A committed transaction has no ledger entries.")
        return TransactionDTO.response(transaction, entries)

    def _lock_accounts(self, account_ids: list[int]):
        try:
            self.session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
            return self.repository.lock_accounts(account_ids)
        except DBAPIError as error:
            original = error.orig
            sqlstate = getattr(original, "pgcode", None) or getattr(original, "sqlstate", None)
            if sqlstate == "55P03":
                raise LockWaitTimeout() from error
            raise

    @staticmethod
    def _validate_amount(amount_cents: int) -> None:
        if amount_cents < 1:
            raise InvalidAmount()

    def deposit(
        self,
        account_key: str,
        idempotency_key: str,
        payload: dict,
    ) -> tuple[dict, bool]:
        account_uuid = parse_uuid(account_key, "account_key")
        amount_cents = payload["amount_cents"]
        self._validate_amount(amount_cents)
        account = self.repository.get_account_by_key(account_uuid)
        if account is None:
            raise NotFoundAccount()

        locked = self._lock_accounts([account.id])
        if not locked:
            raise NotFoundAccount()
        account = locked[0]

        transaction, is_new = self._reserve(
            idempotency_key=idempotency_key,
            route=f"/account/{account_key}/deposit",
            payload=payload,
            transaction_type="DEPOSIT",
            amount_cents=amount_cents,
            to_account_id=account.id,
        )
        if not is_new:
            return self._replay(transaction), True

        account.balance_cents += amount_cents
        entry = self.repository.add_ledger_entry(
            account=account,
            transaction=transaction,
            direction="CREDIT",
            kind="DEPOSIT",
            amount_cents=amount_cents,
            balance_after_cents=account.balance_cents,
        )
        self.repository.add_notifications(transaction, [account.id])
        self.session.flush()
        response = TransactionDTO.response(
            transaction,
            [entry],
        )
        self.session.commit()
        return response, False

    def purchase(
        self,
        account_key: str,
        idempotency_key: str,
        payload: dict,
    ) -> tuple[dict, bool]:
        account_uuid = parse_uuid(account_key, "account_key")
        amount_cents = payload["amount_cents"]
        self._validate_amount(amount_cents)
        if not is_valid_cnpj(payload["merchant_document_number"]):
            raise InvalidMerchantDocument()

        account = self.repository.get_account_by_key(account_uuid)
        if account is None:
            raise NotFoundAccount()

        merchant_mcc = self.repository.get_merchant_mcc(payload["merchant_document_number"])

        locked = self._lock_accounts([account.id])
        if not locked:
            raise NotFoundAccount()
        account = locked[0]

        transaction, is_new = self._reserve(
            idempotency_key=idempotency_key,
            route=f"/account/{account_key}/purchase",
            payload=payload,
            transaction_type="PURCHASE",
            amount_cents=amount_cents,
            from_account_id=account.id,
        )
        if not is_new:
            return self._replay(transaction), True
        blocked_mccs = {blocked.mcc.strip() for blocked in account.blocked_mccs}
        if payload["mcc"] in blocked_mccs or merchant_mcc in blocked_mccs:
            raise BlockedByVault()
        if account.balance_cents < amount_cents:
            raise InsufficientFunds(account.balance_cents, amount_cents)

        account.balance_cents -= amount_cents
        entry = self.repository.add_ledger_entry(
            account=account,
            transaction=transaction,
            direction="DEBIT",
            kind="PURCHASE",
            amount_cents=amount_cents,
            mcc=payload["mcc"],
            balance_after_cents=account.balance_cents,
        )
        self.repository.add_notifications(transaction, [account.id])
        self.session.flush()
        response = TransactionDTO.response(
            transaction,
            [entry],
        )
        self.session.commit()
        return response, False

    def transfer(self, idempotency_key: str, payload: dict) -> tuple[dict, bool]:
        amount_cents = payload["amount_cents"]
        self._validate_amount(amount_cents)

        from_account_uuid = parse_uuid(payload["from_account_key"], "from_account_key")
        to_account_uuid = parse_uuid(payload["to_account_key"], "to_account_key")
        from_account = self.repository.get_account_by_key(from_account_uuid)
        to_account = self.repository.get_account_by_key(to_account_uuid)
        if from_account is None or to_account is None:
            raise NotFoundAccount()
        if from_account.id == to_account.id:
            raise SameAccountTransfer()
        if amount_cents > from_account.transfer_limit_cents:
            raise TransferLimitExceeded()

        merchant_mcc = self.repository.get_merchant_mcc(to_account.customer.document_number)

        locked_accounts = self._lock_accounts([from_account.id, to_account.id])
        accounts_by_id = {account.id: account for account in locked_accounts}
        from_account = accounts_by_id.get(from_account.id)
        to_account = accounts_by_id.get(to_account.id)
        if from_account is None or to_account is None:
            raise NotFoundAccount()

        transaction, is_new = self._reserve(
            idempotency_key=idempotency_key,
            route="/transfer",
            payload=payload,
            transaction_type="TRANSFER",
            amount_cents=amount_cents,
            fee_cents=TRANSFER_FEE_CENTS,
            from_account_id=from_account.id,
            to_account_id=to_account.id,
        )
        if not is_new:
            return self._replay(transaction), True

        blocked_mccs = {blocked.mcc.strip() for blocked in from_account.blocked_mccs}
        if merchant_mcc in blocked_mccs:
            raise BlockedByVault()

        required_cents = amount_cents + TRANSFER_FEE_CENTS
        if from_account.balance_cents < required_cents:
            raise InsufficientFunds(from_account.balance_cents, required_cents)

        from_account.balance_cents -= amount_cents
        transfer_entry = self.repository.add_ledger_entry(
            account=from_account,
            transaction=transaction,
            direction="DEBIT",
            kind="TRANSFER",
            amount_cents=amount_cents,
            balance_after_cents=from_account.balance_cents,
        )
        from_account.balance_cents -= TRANSFER_FEE_CENTS
        fee_entry = self.repository.add_ledger_entry(
            account=from_account,
            transaction=transaction,
            direction="DEBIT",
            kind="FEE",
            amount_cents=TRANSFER_FEE_CENTS,
            balance_after_cents=from_account.balance_cents,
        )
        to_account.balance_cents += amount_cents
        recipient_entry = self.repository.add_ledger_entry(
            account=to_account,
            transaction=transaction,
            direction="CREDIT",
            kind="TRANSFER",
            amount_cents=amount_cents,
            balance_after_cents=to_account.balance_cents,
        )
        self.repository.add_notifications(transaction, [from_account.id, to_account.id])
        self.session.flush()
        response = TransactionDTO.response(
            transaction,
            [transfer_entry, fee_entry, recipient_entry],
        )
        self.session.commit()
        return response, False

    def statement(self, account_key: str, limit: int, page: int) -> dict:
        account_uuid = parse_uuid(account_key, "account_key")
        self.session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
        account = self.repository.get_account_by_key(account_uuid)
        if account is None:
            raise NotFoundAccount()

        entries = self.repository.get_statement(account.id, limit, page * limit)
        is_last_page = len(entries) <= limit
        if not is_last_page:
            entries = entries[:limit]

        return {
            "data": [LedgerEntryDTO.to_dict(entry) for entry in entries],
            "limit": limit,
            "page": page,
            "is_last_page": is_last_page,
            "balance_cents": account.balance_cents,
        }
