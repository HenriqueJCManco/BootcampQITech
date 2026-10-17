from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import joinedload, selectinload

from models import (
    Account,
    BankTransaction,
    BlockedMCC,
    Customer,
    LedgerEntry,
    Merchant,
    NotificationOutbox,
    TrustedContact,
)


class BankRepository:
    def __init__(self, session) -> None:
        self.session = session

    def get_customer_by_key(self, customer_key: UUID) -> Customer | None:
        return self.session.query(Customer).filter(Customer.customer_key == customer_key).first()

    def get_customer_by_document(self, document_number: str) -> Customer | None:
        return self.session.query(Customer).filter(Customer.document_number == document_number).first()

    def get_customer_by_email(self, email: str) -> Customer | None:
        return self.session.query(Customer).filter(Customer.email == email).first()

    def create_customer(self, payload: dict) -> Customer:
        customer = Customer(
            name=payload["name"],
            email=payload["email"],
            document_number=payload["document_number"],
        )
        self.session.add(customer)
        return customer

    def get_account_by_key(self, account_key: UUID) -> Account | None:
        return (
            self.session.query(Account)
            .options(joinedload(Account.customer))
            .filter(Account.account_key == account_key)
            .first()
        )

    def get_account_by_customer_id(self, customer_id: int) -> Account | None:
        return self.session.query(Account).filter(Account.customer_id == customer_id).first()

    def get_account_for_update(self, account_id: int) -> Account | None:
        return (
            self.session.query(Account)
            .options(selectinload(Account.blocked_mccs))
            .filter(Account.id == account_id)
            .with_for_update()
            .populate_existing()
            .first()
        )

    def lock_accounts(self, account_ids: list[int]) -> list[Account]:
        return (
            self.session.query(Account)
            .filter(Account.id.in_(account_ids))
            .order_by(Account.id)
            .with_for_update()
            .populate_existing()
            .all()
        )

    def create_account(self, customer: Customer, transfer_limit_cents: int) -> Account:
        account = Account(customer=customer, transfer_limit_cents=transfer_limit_cents)
        account.blocked_mccs.append(BlockedMCC(mcc="7995"))
        self.session.add(account)
        return account

    def replace_blocked_mccs(self, account: Account, mcc_list: list[str]) -> None:
        account.blocked_mccs.clear()
        account.blocked_mccs.extend(BlockedMCC(mcc=mcc) for mcc in mcc_list)

    def get_merchant_mcc(self, document_number: str) -> str | None:
        merchant = (
            self.session.query(Merchant)
            .filter(Merchant.document_number == document_number)
            .first()
        )
        return merchant.mcc if merchant is not None else None

    def create_trusted_contact(self, account: Account, payload: dict) -> TrustedContact:
        contact = TrustedContact(
            name=payload["name"],
            channel=payload["channel"],
            address=payload["address"],
        )
        account.trusted_contacts.append(contact)
        return contact

    def count_trusted_contacts(self, account_id: int) -> int:
        return (
            self.session.query(func.count(TrustedContact.id))
            .filter(TrustedContact.account_id == account_id)
            .scalar()
        )

    def reserve_transaction(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        transaction_type: str,
        amount_cents: int,
        fee_cents: int = 0,
        from_account_id: int | None = None,
        to_account_id: int | None = None,
    ) -> tuple[BankTransaction, bool]:
        statement = (
            insert(BankTransaction)
            .values(
                transaction_key=uuid4(),
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                type=transaction_type,
                amount_cents=amount_cents,
                fee_cents=fee_cents,
                from_account_id=from_account_id,
                to_account_id=to_account_id,
            )
            .on_conflict_do_nothing(index_elements=[BankTransaction.idempotency_key])
            .returning(BankTransaction.id)
        )
        transaction_id = self.session.execute(statement).scalar_one_or_none()

        if transaction_id is not None:
            transaction = self.session.get(BankTransaction, transaction_id)
            return transaction, True

        transaction = (
            self.session.query(BankTransaction)
            .filter(BankTransaction.idempotency_key == idempotency_key)
            .one()
        )
        return transaction, False

    def add_ledger_entry(
        self,
        *,
        account: Account,
        transaction: BankTransaction,
        direction: str,
        kind: str,
        amount_cents: int,
        balance_after_cents: int,
        mcc: str | None = None,
    ) -> LedgerEntry:
        entry = LedgerEntry(
            account_id=account.id,
            transaction=transaction,
            direction=direction,
            kind=kind,
            amount_cents=amount_cents,
            mcc=mcc,
            balance_after_cents=balance_after_cents,
        )
        self.session.add(entry)
        return entry

    def add_notifications(self, transaction: BankTransaction, account_ids: list[int]) -> None:
        contact_ids = {
            contact_id
            for (contact_id,) in (
                self.session.query(TrustedContact.id)
                .filter(TrustedContact.account_id.in_(set(account_ids)))
                .all()
            )
        }
        for contact_id in contact_ids:
            self.session.add(
                NotificationOutbox(transaction_id=transaction.id, contact_id=contact_id)
            )

    def get_replay_entries(self, transaction_id: int) -> list[LedgerEntry]:
        return (
            self.session.query(LedgerEntry)
            .filter(LedgerEntry.transaction_id == transaction_id)
            .order_by(LedgerEntry.id)
            .all()
        )

    def get_statement(self, account_id: int, limit: int, offset: int) -> list[LedgerEntry]:
        return (
            self.session.query(LedgerEntry)
            .options(joinedload(LedgerEntry.transaction))
            .filter(LedgerEntry.account_id == account_id)
            .order_by(LedgerEntry.entry_datetime.desc(), LedgerEntry.id.desc())
            .limit(limit + 1)
            .offset(offset)
            .all()
        )
