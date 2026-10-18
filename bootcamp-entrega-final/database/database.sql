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
CREATE INDEX ix_ledger_entry_transaction_id
    ON ledger_entry (transaction_id);

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

CREATE INDEX ix_bank_transaction_pair
    ON bank_transaction (from_account_id, to_account_id, created_at DESC);
CREATE INDEX ix_bank_transaction_destination
    ON bank_transaction (to_account_id, created_at DESC);

CREATE SCHEMA IF NOT EXISTS fraude;

CREATE TABLE fraude.engine_config (
    version INTEGER PRIMARY KEY,
    params JSONB NOT NULL,
    active_from TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_engine_config_version CHECK (version >= 1)
);
CREATE INDEX ix_engine_config_active_from
    ON fraude.engine_config (active_from DESC);

CREATE TABLE fraude.pix_analysis (
    id BIGSERIAL PRIMARY KEY,
    analysis_key UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    pix_id VARCHAR(255) NOT NULL,
    request_hash CHAR(64) NOT NULL,
    status VARCHAR(20),
    score INTEGER,
    value_band CHAR(1),
    engine_version INTEGER REFERENCES fraude.engine_config(version),
    type VARCHAR(10) NOT NULL DEFAULT 'payment',
    amount_cents BIGINT NOT NULL,
    transaction_date TIMESTAMPTZ NOT NULL,
    source_account_id BIGINT REFERENCES account(id),
    source_hash CHAR(64) NOT NULL,
    source_masked VARCHAR(20) NOT NULL,
    payer_class VARCHAR(3),
    destination_account_id BIGINT REFERENCES account(id),
    destination_key CHAR(64) NOT NULL,
    destination_masked VARCHAR(20) NOT NULL,
    device_id VARCHAR(255),
    channel VARCHAR(20),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geo_accuracy_m INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    second_factor_at TIMESTAMPTZ,
    challenge_type VARCHAR(30),
    friction_script_key VARCHAR(40),
    friction_answer VARCHAR(4),
    friction_answered_at TIMESTAMPTZ,
    second_factor_contact_id BIGINT REFERENCES trusted_contact(id),
    qi_account_key UUID,
    qi_request_control_key UUID,
    qi_pix_transfer_key UUID,
    qi_end_to_end_id VARCHAR(32),
    qi_transfer_status VARCHAR(30),
    qi_contact_type VARCHAR(5),
    challenge_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_pix_analysis_pix_id UNIQUE (pix_id),
    CONSTRAINT uq_pix_analysis_qi_pix_transfer_key UNIQUE (qi_pix_transfer_key),
    CONSTRAINT chk_pix_analysis_qi_transfer_status
        CHECK (qi_transfer_status IN ('pending_2fa_approval', 'sent', 'pending', 'rejected')),
    CONSTRAINT chk_pix_analysis_qi_contact_type CHECK (qi_contact_type IN ('sms', 'email')),
    CONSTRAINT chk_pix_analysis_status
        CHECK (status IN ('approved', 'two_factor_required', 'rejected')),
    CONSTRAINT chk_pix_analysis_value_band CHECK (value_band IN ('A', 'B', 'C', 'D')),
    CONSTRAINT chk_pix_analysis_type CHECK (type IN ('payment', 'refund')),
    CONSTRAINT chk_pix_analysis_amount CHECK (amount_cents >= 1),
    CONSTRAINT chk_pix_analysis_payer_class CHECK (payer_class IN ('PF', 'MEI', 'PJ')),
    CONSTRAINT chk_pix_analysis_channel
        CHECK (channel IN ('internet', 'celular', 'computador', 'tablet', 'relogio')),
    CONSTRAINT chk_pix_analysis_challenge_type
        CHECK (challenge_type IN ('CUSTOMER_TOKEN_2FA', 'TRUSTED_CONTACT_APPROVAL')),
    CONSTRAINT chk_pix_analysis_friction_answer CHECK (friction_answer IN ('YES', 'NO', 'SKIP')),
    CONSTRAINT chk_pix_analysis_geolocation CHECK ((latitude IS NULL) = (longitude IS NULL)),
    CONSTRAINT chk_pix_analysis_geo_accuracy CHECK (geo_accuracy_m IS NULL OR geo_accuracy_m >= 0)
);
CREATE INDEX ix_pix_analysis_source_date
    ON fraude.pix_analysis (source_hash, transaction_date DESC);
CREATE INDEX ix_pix_analysis_destination_date
    ON fraude.pix_analysis (destination_key, transaction_date DESC);
CREATE INDEX ix_pix_analysis_device_date
    ON fraude.pix_analysis (device_id, transaction_date DESC)
    WHERE device_id IS NOT NULL;

CREATE TABLE fraude.pix_rule_result (
    id BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT NOT NULL REFERENCES fraude.pix_analysis(id) ON DELETE CASCADE,
    rule_code VARCHAR(10) NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_pix_rule_result_analysis
    ON fraude.pix_rule_result (analysis_id);
CREATE INDEX ix_pix_rule_result_rule_code
    ON fraude.pix_rule_result (rule_code, created_at DESC);

CREATE TABLE fraude.device_seen (
    device_id VARCHAR(255) NOT NULL,
    source_hash CHAR(64) NOT NULL,
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    tx_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (device_id, source_hash),
    CONSTRAINT chk_device_seen_tx_count CHECK (tx_count >= 1),
    CONSTRAINT chk_device_seen_dates CHECK (last_seen >= first_seen)
);
CREATE INDEX ix_device_seen_device_first_seen
    ON fraude.device_seen (device_id, first_seen);

CREATE TABLE fraude.destination_flag (
    id BIGSERIAL PRIMARY KEY,
    destination_key CHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL,
    reason VARCHAR(255) NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_destination_flag_status
        CHECK (status IN ('OBSERVACAO', 'QUARENTENA', 'MARCADA')),
    CONSTRAINT chk_destination_flag_period CHECK (expires_at > starts_at)
);
CREATE INDEX ix_destination_flag_key_expires
    ON fraude.destination_flag (destination_key, expires_at DESC);

CREATE TABLE fraude.destination_reputation (
    destination_key CHAR(64) PRIMARY KEY,
    analyses_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    two_factor_count INTEGER NOT NULL DEFAULT 0,
    payers_24h INTEGER NOT NULL DEFAULT 0,
    forwarded_ratio_1h NUMERIC(5, 4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_destination_reputation_counts CHECK (
        analyses_count >= 0
        AND rejected_count >= 0
        AND two_factor_count >= 0
        AND payers_24h >= 0
        AND rejected_count + two_factor_count <= analyses_count
    ),
    CONSTRAINT chk_destination_reputation_ratio
        CHECK (forwarded_ratio_1h >= 0 AND forwarded_ratio_1h <= 1)
);

CREATE TABLE fraude.bet_destination (
    cnpj CHAR(14) PRIMARY KEY,
    razao_social VARCHAR(255) NOT NULL,
    source VARCHAR(100) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_bet_destination_cnpj CHECK (cnpj ~ '^[0-9]{14}$')
);
CREATE INDEX ix_bet_destination_active
    ON fraude.bet_destination (cnpj)
    WHERE active;

INSERT INTO fraude.bet_destination (cnpj, razao_social, source) VALUES
    ('99000001000101', 'APOSTA FICTICIA UM LTDA', 'seed_demo'),
    ('99000002000148', 'BET FICTICIA DOIS LTDA', 'seed_demo'),
    ('99000003000192', 'CASSINO FICTICIO TRES LTDA', 'seed_demo');

CREATE TABLE fraude.of_payer_profile (
    account_id BIGINT PRIMARY KEY REFERENCES account(id) ON DELETE CASCADE,
    other_income_cents BIGINT NOT NULL DEFAULT 0,
    other_balance_cents BIGINT NOT NULL DEFAULT 0,
    other_balance_prev_cents BIGINT,
    prev_loaded_at TIMESTAMPTZ,
    loaded_at TIMESTAMPTZ NOT NULL,
    consent_expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT chk_of_payer_profile_values CHECK (
        other_income_cents >= 0
        AND other_balance_cents >= 0
        AND (other_balance_prev_cents IS NULL OR other_balance_prev_cents >= 0)
    )
);

CREATE TABLE fraude.pix_feedback (
    id BIGSERIAL PRIMARY KEY,
    transaction_id VARCHAR(255) NOT NULL REFERENCES fraude.pix_analysis(pix_id),
    is_fraud BOOLEAN NOT NULL,
    reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_pix_feedback_transaction
    ON fraude.pix_feedback (transaction_id);

CREATE TABLE fraude.pix_shadow_result (
    id BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT NOT NULL REFERENCES fraude.pix_analysis(id) ON DELETE CASCADE,
    shadow_score NUMERIC(7, 4) NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_pix_shadow_result_analysis
    ON fraude.pix_shadow_result (analysis_id);

ALTER TABLE notification_outbox
    ALTER COLUMN transaction_id DROP NOT NULL,
    ADD COLUMN analysis_id BIGINT REFERENCES fraude.pix_analysis(id),
    ADD CONSTRAINT chk_outbox_origin
        CHECK ((transaction_id IS NOT NULL AND analysis_id IS NULL)
            OR (transaction_id IS NULL AND analysis_id IS NOT NULL)),
    ADD CONSTRAINT uq_outbox_analysis_contact UNIQUE (analysis_id, contact_id);

CREATE INDEX idx_outbox_blocked_pix
    ON notification_outbox (analysis_id, created_at DESC)
    WHERE transaction_id IS NULL;

ALTER TABLE trusted_contact
    ADD COLUMN approval_consent_at TIMESTAMPTZ;

INSERT INTO fraude.engine_config (version, active_from, params) VALUES (
    1,
    '2026-01-01T00:00:00Z',
    '{
        "percentil_95_valor": {
            "percentil": 95,
            "janela_dias": 90,
            "min_observacoes": 10,
            "piso_centavos": 50000
        },
        "janela_noite_inicio": "20:00",
        "janela_noite_fim": "06:00",
        "timezone_regra": "America/Sao_Paulo",
        "teto_noturno_pf_centavos": 100000,
        "histograma_horas_tolerancia": 0.05,
        "segmentos_canal": {
            "mobile": ["celular", "tablet"],
            "desktop": ["internet", "computador"],
            "relogio": ["relogio"]
        },
        "faixas": [
            {"faixa": "A", "ate_centavos": 20000, "dois_fatores": 45, "reprova": 85},
            {"faixa": "B", "ate_centavos": 100000, "dois_fatores": 35, "reprova": 75},
            {"faixa": "C", "ate_centavos": 500000, "dois_fatores": 30, "reprova": 65},
            {"faixa": "D", "ate_centavos": null, "dois_fatores": 25, "reprova": 55}
        ],
        "mei": {
            "sufixos_veto": ["LTDA", "EIRELI", "SLU", "EPP", "S/A", "S.A."],
            "cpf_no_fim_do_nome": true,
            "raiz_cnpj_no_fim_do_nome": true
        },
        "eliminatorias": {
            "E2": {"expiracao_marca_anos": 5},
            "E3": {"quarentena_horas": 72},
            "E4": {"pre_cadastro_horas": 24},
            "E5": {"limite_diario_centavos": 100000, "limite_por_pix_centavos": 20000}
        },
        "regras": {
            "D1": {"maturacao_horas": 24, "pontos_desconhecido": 40, "pontos_maturando": 20},
            "D2": {"janela_dias": 7, "min_documentos": 3, "pontos": 35},
            "D3": {"pontos": 5},
            "G1": {
                "janela_dias": 90,
                "min_pontos": 5,
                "faixas": [{"acima_km": 500, "pontos": 25}, {"acima_km": 100, "pontos": 15}]
            },
            "G2": {
                "intervalo_min_s": 60,
                "precisao_max_m": 5000,
                "idade_max_horas": 6,
                "niveis": [
                    {"distancia_min_km": 100, "velocidade_kmh": 800, "pontos": 35, "piso": true},
                    {"distancia_min_km": 20, "velocidade_kmh": 300, "pontos": 35, "piso": true}
                ]
            },
            "G4": {"canais": ["celular", "tablet"], "pontos": 5},
            "K1": {"janela_dias": 90, "min_transacoes": 5, "proporcao_max": 0.10, "pontos": 10},
            "K2": {"canal": "relogio", "acima_centavos": 20000},
            "C1": {"pontos": 15},
            "C2": {
                "faixas": [
                    {"menos_de_dias": 7, "pontos": 30},
                    {"menos_de_dias": 30, "pontos": 20},
                    {"menos_de_dias": 90, "pontos": 5}
                ]
            },
            "C5": {"faixas": [{"min_pagadores": 5, "pontos": 25}, {"min_pagadores": 3, "pontos": 15}]},
            "C6": {"janela_min": 60, "proporcao_min": 0.5, "pontos": 25},
            "C7": {
                "min_analises": 4,
                "faixas": [{"proporcao_min": 0.5, "pontos": 30}, {"proporcao_min": 0.3, "pontos": 15}]
            },
            "C8": {
                "teste_max_centavos": 1000,
                "janela_horas": 72,
                "alto_min_centavos": 50000,
                "alto_multiplicador": 20,
                "pontos": 30
            },
            "P1": {"pontos_acima": 20, "multiplicador_alto": 3, "pontos_acima_alto": 30, "pontos_sem_historico": 10},
            "P2": {"min_observacoes": 10, "pontos": 10},
            "M1": {"janela_horas": 24, "multiplicador": 3, "pontos": 20},
            "M2": {
                "janela_horas": 24,
                "min_pix": 3,
                "faixa_min": 0.8,
                "faixa_max": 1.0,
                "tetos_centavos": [20000, 100000],
                "pontos": 30
            },
            "V1": {"janela_min": 10, "faixas": [{"min_pix": 5, "pontos": 40}, {"min_pix": 3, "pontos": 25}]},
            "V2": {"janela_min": 60, "min_destinos": 3, "pontos": 30},
            "O1": {"menos_de_dias": 30, "pontos": 10},
            "R1": {"pontos_acesso_remoto": 30, "pontos_ligacao": 30},
            "R2": {
                "canais": ["internet", "computador"],
                "pontos": 40,
                "min_sinais": 1,
                "cadencia_digitacao_max_std_ms": 15,
                "escalar_com": ["V1", "C1"],
                "escalar_para": "rejected"
            },
            "F1": {"janela_renda_dias": 30, "faixas": [{"acima_x": 2, "pontos": 25}, {"acima_x": 1, "pontos": 15}]},
            "F2": {"proporcao_min": 0.8, "pontos": 15},
            "H2": {"min_pix": 3, "meses_distintos": 3, "janela_meses": 3, "tolerancia": 0.2, "pontos": -25}
        },
        "pisos": {
            "X1": {"min_sinais": 3, "pontos_min_sinal_fraco": 10, "pontos_max_sinal_fraco": 20},
            "X2": {"faixa": "D"}
        },
        "reputacao": {
            "observacao_conta_dias": 7,
            "observacao_pj_dias": 30,
            "observacao_saida_dias": 7,
            "exorbitante_centavos": 1000000,
            "exorbitante_multiplicador_p95": 10,
            "exorbitante_piso_centavos": 300000,
            "quarentena_min_pagadores": 5,
            "quarentena_min_proporcao_c7": 0.5,
            "quarentena_horas": 72
        },
        "antifraude": {
            "timeout_ms": 300,
            "indisponivel": "fechar",
            "abrir_ate_centavos": 0
        },
        "social_2fa": {
            "sinais": ["R1", "C1", "F2"],
            "prazo_min": 15,
            "aprovacoes_minimas": 1,
            "negacao_encerra": true,
            "exige_consentimento_contato": true
        },
        "drenagem": {
            "janela_min": 30,
            "valor_minimo_pct": 90,
            "pontos": 30,
            "pontos_reforco": 15,
            "reforco_max_idade_horas": 24
        },
        "friction": {
            "precedencia": ["R1", "F3", "C6", "C5"],
            "resposta_sim_sem_contato": "rejected"
        },
        "familias": {
            "aparelho": {"regras": ["D1", "D2", "D3"], "teto": 45},
            "geografia": {"regras": ["G1", "G2", "G4"], "teto": 40},
            "destino": {"regras": ["C1", "C2", "C5", "C6", "C7", "C8"], "teto": 55},
            "comportamento": {"regras": ["K1", "P1", "P2", "M1", "M2", "V1", "V2"], "teto": 60}
        },
        "flags": {
            "ENABLE_BETS_BAN": true,
            "ENABLE_FAMILY_CAPS": true,
            "ENABLE_BCB_587_RULES": true,
            "APPLY_NIGHT_LIMIT_PJ": false,
            "ENABLE_MEI_AS_PF": true
        }
    }'::jsonb
);
