CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE customer (
    id BIGSERIAL PRIMARY KEY,
    customer_key UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    document_number VARCHAR(18) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE account (
    id BIGSERIAL PRIMARY KEY,
    account_key UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    customer_id BIGINT NOT NULL UNIQUE REFERENCES customer(id),
    balance_cents BIGINT NOT NULL DEFAULT 0,
    transfer_limit_cents BIGINT NOT NULL DEFAULT 100000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_account_balance_non_negative CHECK (balance_cents >= 0),
    CONSTRAINT chk_account_transfer_limit_positive CHECK (transfer_limit_cents >= 1)
);

CREATE TABLE merchant (
    id BIGSERIAL PRIMARY KEY,
    document_number VARCHAR(18) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    mcc CHAR(4) NOT NULL
);

CREATE TABLE blocked_mcc (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    mcc CHAR(4) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_account_blocked_mcc UNIQUE (account_id, mcc)
);

CREATE TABLE trusted_contact (
    id BIGSERIAL PRIMARY KEY,
    contact_key UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    account_id BIGINT NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    channel VARCHAR(10) NOT NULL,
    address VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_contact_channel CHECK (channel IN ('SMS', 'EMAIL')),
    CONSTRAINT uq_trusted_contact_address UNIQUE (account_id, address)
);

CREATE TABLE bank_transaction (
    id BIGSERIAL PRIMARY KEY,
    transaction_key UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    request_hash CHAR(64) NOT NULL,
    type VARCHAR(20) NOT NULL,
    from_account_id BIGINT REFERENCES account(id),
    to_account_id BIGINT REFERENCES account(id),
    amount_cents BIGINT NOT NULL,
    fee_cents BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_bank_transaction_type CHECK (type IN ('DEPOSIT', 'PURCHASE', 'TRANSFER')),
    CONSTRAINT chk_bank_transaction_amount CHECK (amount_cents >= 1),
    CONSTRAINT chk_bank_transaction_fee CHECK (fee_cents >= 0)
);

CREATE TABLE ledger_entry (
    id BIGSERIAL PRIMARY KEY,
    entry_key UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    account_id BIGINT NOT NULL REFERENCES account(id),
    transaction_id BIGINT NOT NULL REFERENCES bank_transaction(id),
    direction VARCHAR(10) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    amount_cents BIGINT NOT NULL,
    mcc CHAR(4),
    balance_after_cents BIGINT NOT NULL,
    entry_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_ledger_direction CHECK (direction IN ('CREDIT', 'DEBIT')),
    CONSTRAINT chk_ledger_kind CHECK (kind IN ('DEPOSIT', 'PURCHASE', 'TRANSFER', 'FEE')),
    CONSTRAINT chk_ledger_amount CHECK (amount_cents >= 1),
    CONSTRAINT chk_ledger_balance_after CHECK (balance_after_cents >= 0)
);
CREATE INDEX ix_ledger_account_statement
    ON ledger_entry (account_id, entry_datetime DESC, id DESC);

CREATE TABLE notification_outbox (
    id BIGSERIAL PRIMARY KEY,
    transaction_id BIGINT NOT NULL REFERENCES bank_transaction(id),
    contact_id BIGINT NOT NULL REFERENCES trusted_contact(id),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMPTZ,
    CONSTRAINT chk_outbox_status CHECK (status IN ('PENDING', 'SENT')),
    CONSTRAINT uq_outbox_transaction_contact UNIQUE (transaction_id, contact_id)
);
CREATE INDEX ix_notification_outbox_pending
    ON notification_outbox (created_at, id)
    WHERE status = 'PENDING';
