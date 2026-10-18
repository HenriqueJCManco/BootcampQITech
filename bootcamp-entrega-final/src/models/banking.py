from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    BigInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class Customer(Base):
    __tablename__ = "customer"

    id = Column(BigInteger, primary_key=True)
    customer_key = Column(UUID(as_uuid=True), nullable=False, unique=True, server_default=text("gen_random_uuid()"))
    document_number = Column(String(18), nullable=False, unique=True)
    email = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    account = relationship("Account", back_populates="customer", uselist=False)


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint("balance_cents >= 0", name="chk_account_balance_non_negative"),
        CheckConstraint("transfer_limit_cents >= 1", name="chk_account_transfer_limit_positive"),
    )

    id = Column(BigInteger, primary_key=True)
    account_key = Column(UUID(as_uuid=True), nullable=False, unique=True, server_default=text("gen_random_uuid()"))
    customer_id = Column(BigInteger, ForeignKey("customer.id"), nullable=False, unique=True)
    balance_cents = Column(BigInteger, nullable=False, server_default="0")
    transfer_limit_cents = Column(BigInteger, nullable=False, server_default="100000")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    customer = relationship("Customer", back_populates="account")
    blocked_mccs = relationship("BlockedMCC", back_populates="account", cascade="all, delete-orphan")
    trusted_contacts = relationship("TrustedContact", back_populates="account", cascade="all, delete-orphan")


class Merchant(Base):
    __tablename__ = "merchant"

    id = Column(BigInteger, primary_key=True)
    document_number = Column(String(18), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    mcc = Column(CHAR(4), nullable=False)


class BlockedMCC(Base):
    __tablename__ = "blocked_mcc"
    __table_args__ = (UniqueConstraint("account_id", "mcc", name="uq_account_blocked_mcc"),)

    id = Column(BigInteger, primary_key=True)
    account_id = Column(BigInteger, ForeignKey("account.id", ondelete="CASCADE"), nullable=False)
    mcc = Column(CHAR(4), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    account = relationship("Account", back_populates="blocked_mccs")


class TrustedContact(Base):
    __tablename__ = "trusted_contact"
    __table_args__ = (
        CheckConstraint("channel IN ('SMS', 'EMAIL')", name="chk_contact_channel"),
        UniqueConstraint("account_id", "address", name="uq_trusted_contact_address"),
    )

    id = Column(BigInteger, primary_key=True)
    contact_key = Column(UUID(as_uuid=True), nullable=False, unique=True, server_default=text("gen_random_uuid()"))
    account_id = Column(BigInteger, ForeignKey("account.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    channel = Column(String(10), nullable=False)
    address = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    approval_consent_at = Column(DateTime(timezone=True))

    account = relationship("Account", back_populates="trusted_contacts")


class BankTransaction(Base):
    __tablename__ = "bank_transaction"
    __table_args__ = (
        CheckConstraint("type IN ('DEPOSIT', 'PURCHASE', 'TRANSFER')", name="chk_bank_transaction_type"),
        CheckConstraint("amount_cents >= 1", name="chk_bank_transaction_amount"),
        CheckConstraint("fee_cents >= 0", name="chk_bank_transaction_fee"),
        Index("ix_bank_transaction_pair", "from_account_id", "to_account_id", text("created_at DESC")),
        Index("ix_bank_transaction_destination", "to_account_id", text("created_at DESC")),
    )

    id = Column(BigInteger, primary_key=True)
    transaction_key = Column(UUID(as_uuid=True), nullable=False, unique=True, server_default=text("gen_random_uuid()"))
    idempotency_key = Column(String(255), nullable=False, unique=True)
    request_hash = Column(CHAR(64), nullable=False)
    type = Column(String(20), nullable=False)
    from_account_id = Column(BigInteger, ForeignKey("account.id"))
    to_account_id = Column(BigInteger, ForeignKey("account.id"))
    amount_cents = Column(BigInteger, nullable=False)
    fee_cents = Column(BigInteger, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    ledger_entries = relationship("LedgerEntry", back_populates="transaction")


class LedgerEntry(Base):
    __tablename__ = "ledger_entry"
    __table_args__ = (
        CheckConstraint("direction IN ('CREDIT', 'DEBIT')", name="chk_ledger_direction"),
        CheckConstraint("kind IN ('DEPOSIT', 'PURCHASE', 'TRANSFER', 'FEE')", name="chk_ledger_kind"),
        CheckConstraint("amount_cents >= 1", name="chk_ledger_amount"),
        CheckConstraint("balance_after_cents >= 0", name="chk_ledger_balance_after"),
        Index(
            "ix_ledger_account_statement",
            "account_id",
            text("entry_datetime DESC"),
            text("id DESC"),
        ),
        Index("ix_ledger_entry_transaction_id", "transaction_id"),
    )

    id = Column(BigInteger, primary_key=True)
    entry_key = Column(UUID(as_uuid=True), nullable=False, unique=True, server_default=text("gen_random_uuid()"))
    account_id = Column(BigInteger, ForeignKey("account.id"), nullable=False)
    transaction_id = Column(BigInteger, ForeignKey("bank_transaction.id"), nullable=False)
    direction = Column(String(10), nullable=False)
    kind = Column(String(20), nullable=False)
    amount_cents = Column(BigInteger, nullable=False)
    mcc = Column(CHAR(4))
    balance_after_cents = Column(BigInteger, nullable=False)
    entry_datetime = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    transaction = relationship("BankTransaction", back_populates="ledger_entries")


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'SENT')", name="chk_outbox_status"),
        CheckConstraint(
            "(transaction_id IS NOT NULL AND analysis_id IS NULL) "
            "OR (transaction_id IS NULL AND analysis_id IS NOT NULL)",
            name="chk_outbox_origin",
        ),
        UniqueConstraint("transaction_id", "contact_id", name="uq_outbox_transaction_contact"),
        UniqueConstraint("analysis_id", "contact_id", name="uq_outbox_analysis_contact"),
        Index(
            "ix_notification_outbox_pending",
            "created_at",
            "id",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "idx_outbox_blocked_pix",
            "analysis_id",
            text("created_at DESC"),
            postgresql_where=text("transaction_id IS NULL"),
        ),
    )

    id = Column(BigInteger, primary_key=True)
    transaction_id = Column(BigInteger, ForeignKey("bank_transaction.id"))
    analysis_id = Column(BigInteger, ForeignKey("fraude.pix_analysis.id"))
    contact_id = Column(BigInteger, ForeignKey("trusted_contact.id"), nullable=False)
    status = Column(String(20), nullable=False, server_default="PENDING")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at = Column(DateTime(timezone=True))
