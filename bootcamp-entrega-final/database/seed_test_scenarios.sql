-- ============================================================================
-- SEED DE CENÁRIOS E PERSONAS DE TESTE (BOOTCAMP BANK & MOTOR ANTIFRAUDE)
-- ============================================================================
-- Este script popula a base com personas prontas para todos os testes:
-- 1. Maria Idosa (PF Vulnerável com Local Seguro, Contatos de Confiança e Cofre)
-- 2. João da Silva (MEI oficial com proteção noturna de PF)
-- 3. Comercial Distribuidora (PJ formal com limites corporativos altos)
-- 4. Carlos Eduardo (PF padrão para testes de mobilidade)
-- 5. Lojistas e Merchants (Farmácia, Padaria, Bets com MCC 7995)
-- 6. Destinos marcados (Quarentena policial e Mulas com dispersão em 24h)
-- ============================================================================

BEGIN;

-- Limpa análises e notificações anteriores para garantir baseline limpo nos testes
TRUNCATE TABLE notification_outbox, fraude.pix_rule_result, fraude.pix_shadow_result, fraude.pix_feedback, fraude.pix_analysis RESTART IDENTITY CASCADE;

-- 1. CLIENTES (PERSONAS DE TESTE)
INSERT INTO customer (id, customer_key, document_number, email, name, created_at)
VALUES 
    (1, '48ca1247-8967-4f79-8534-bb12e0262a4f', '408.463.867-63', 'maria.idosa@bootcampbank.com.br', 'Maria Idosa da Silva', NOW() - interval '360 days'),
    (2, 'a1b2c3d4-0001-4000-8000-000000000002', '11.222.333/0001-81', 'joao.mei@bootcampbank.com.br', 'JOAO DA SILVA 52998224725', NOW() - interval '180 days'),
    (3, 'a1b2c3d4-0001-4000-8000-000000000003', '33.024.468/0001-75', 'financeiro@distribuidora.com.br', 'COMERCIAL DISTRIBUIDORA LTDA', NOW() - interval '500 days'),
    (4, 'a1b2c3d4-0001-4000-8000-000000000004', '529.982.247-25', 'carlos.eduardo@bootcampbank.com.br', 'Carlos Eduardo dos Santos', NOW() - interval '90 days')
ON CONFLICT (id) DO UPDATE SET 
    document_number = EXCLUDED.document_number,
    name = EXCLUDED.name,
    email = EXCLUDED.email;

SELECT setval('customer_id_seq', (SELECT GREATEST(MAX(id), 4) FROM customer));

-- 2. CONTAS BANCÁRIAS E LIMITES
INSERT INTO account (id, account_key, customer_id, balance_cents, transfer_limit_cents, created_at)
VALUES 
    (1, '48ca1247-8967-4f79-8534-bb12e0262a4f', 1, 500000, 100000, NOW() - interval '360 days'),     -- Maria: R$ 5.000 saldo, R$ 1.000 limite
    (2, 'b1b2c3d4-0002-4000-8000-000000000002', 2, 1200000, 200000, NOW() - interval '180 days'),    -- MEI: R$ 12.000 saldo, R$ 2.000 limite
    (3, 'b1b2c3d4-0002-4000-8000-000000000003', 3, 25000000, 10000000, NOW() - interval '500 days'), -- PJ: R$ 250.000 saldo, R$ 100.000 limite
    (4, 'b1b2c3d4-0002-4000-8000-000000000004', 4, 350000, 100000, NOW() - interval '90 days')       -- Carlos: R$ 3.500 saldo, R$ 1.000 limite
ON CONFLICT (id) DO UPDATE SET 
    balance_cents = EXCLUDED.balance_cents,
    transfer_limit_cents = EXCLUDED.transfer_limit_cents;

SELECT setval('account_id_seq', (SELECT GREATEST(MAX(id), 4) FROM account));

-- 3. REDE DE APOIO FAMILIAR (CONTATOS DE CONFIANÇA COM CONSENTIMENTO ATIVO)
DELETE FROM notification_outbox WHERE contact_id IN (SELECT id FROM trusted_contact WHERE account_id = 1);
DELETE FROM trusted_contact WHERE account_id = 1;
INSERT INTO trusted_contact (account_id, name, channel, address, approval_consent_at)
VALUES 
    (1, 'Ana Paula (Filha)', 'EMAIL', 'anapaula.filha@segura.com.br', NOW() - interval '60 days'),
    (1, 'Lucas (Neto)', 'SMS', '+5511999887766', NOW() - interval '60 days');

-- 4. LOCAIS SEGUROS (GEOFENCING RESIDENCIAL)
DELETE FROM trusted_location WHERE account_id = 1;
INSERT INTO trusted_location (account_id, name, latitude, longitude, radius_meters)
VALUES 
    (1, 'Residência da Dona Maria (Casa)', -23.550520, -46.633308, 1000);

-- 5. LOJISTAS / MERCHANTS
INSERT INTO merchant (id, document_number, name, mcc)
VALUES 
    (1, '03.180.365/0001-33', 'Farmacia Popular Saude LTDA', '5912'),
    (2, '31.372.324/0001-84', 'Padaria e Confeitaria Central', '5411'),
    (3, '99.000.001/0001-01', 'Aposta e Jogos de Azar Online', '7995')
ON CONFLICT (id) DO UPDATE SET 
    name = EXCLUDED.name,
    mcc = EXCLUDED.mcc;

SELECT setval('merchant_id_seq', (SELECT GREATEST(MAX(id), 3) FROM merchant));

-- 6. COFRE ANTIVÍCIOS (BLOQUEIO PREVENTIVO DE MCC 7995 PARA A DONA MARIA)
INSERT INTO blocked_mcc (account_id, mcc)
VALUES (1, '7995')
ON CONFLICT DO NOTHING;

-- 7. DISPOSITIVO HISTÓRICO HABITUAL
INSERT INTO fraude.device_seen (device_id, source_hash, first_seen, last_seen, tx_count)
VALUES 
    ('device-maria-phone-01', encode(digest('40846386763', 'sha256'), 'hex'), NOW() - interval '120 days', NOW() - interval '1 day', 25),
    ('device-carlos-phone-04', encode(digest('52998224725', 'sha256'), 'hex'), NOW() - interval '90 days', NOW() - interval '1 day', 15)
ON CONFLICT (device_id, source_hash) DO UPDATE SET 
    last_seen = EXCLUDED.last_seen,
    tx_count = EXCLUDED.tx_count;

-- 8. DESTINOS MARCADOS (QUARENTENA POLICIAL / REPUTAÇÃO DEGRADADA)
INSERT INTO fraude.destination_flag (destination_key, status, reason, starts_at, expires_at)
VALUES 
    (encode(digest('chave.mula.policia@alerta.org', 'sha256'), 'hex'), 'QUARENTENA', 'Marcacao policial de conta receptora', NOW() - interval '2 hours', NOW() + interval '72 hours'),
    (encode(digest('golpe.confirmado@bloqueio.com', 'sha256'), 'hex'), 'MARCADA', 'Fraude confirmada por multiplos pagadores', NOW() - interval '10 days', NOW() + interval '300 days')
ON CONFLICT DO NOTHING;

INSERT INTO fraude.destination_reputation (destination_key, analyses_count, rejected_count, two_factor_count, payers_24h, forwarded_ratio_1h)
VALUES 
    (encode(digest('chave.mula.dispersao@alerta.org', 'sha256'), 'hex'), 15, 6, 4, 8, 0.8500),
    (encode(digest('03180365000133', 'sha256'), 'hex'), 120, 0, 2, 45, 0.0000)
ON CONFLICT (destination_key) DO UPDATE SET 
    payers_24h = EXCLUDED.payers_24h,
    analyses_count = EXCLUDED.analyses_count;

COMMIT;

ANALYZE customer;
ANALYZE account;
ANALYZE trusted_location;
ANALYZE trusted_contact;
ANALYZE merchant;
ANALYZE blocked_mcc;
ANALYZE fraude.pix_analysis;

SELECT 
    'Base de testes estruturada com sucesso!' AS status,
    (SELECT count(*) FROM customer) AS clientes,
    (SELECT count(*) FROM account) AS contas,
    (SELECT count(*) FROM trusted_location) AS locais_seguros,
    (SELECT count(*) FROM trusted_contact) AS contatos_confianca,
    (SELECT count(*) FROM merchant) AS lojistas;
