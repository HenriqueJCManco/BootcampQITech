-- Script de Carga Massiva: 1 Milhão de Clientes e Contas
-- Otimizado para PostgreSQL com geração vetorial via generate_series
\timing on

BEGIN;

-- 1. Inserir 1.000.000 de clientes com CPFs únicos padronizados e tipificação PF, PJ e MEI
INSERT INTO customer (document_number, email, name, created_at)
SELECT 
    lpad(i::text, 11, '0') AS document_number,
    'cliente_' || i || '@bootcampbank.com.br' AS email,
    CASE 
        WHEN i % 10 = 0 THEN 'EMPRESA COMERCIAL ' || i || ' LTDA'
        WHEN i % 7 = 0 THEN 'JOAO SILVA ' || lpad(i::text, 11, '0') -- Padrão MEI com CPF no nome
        ELSE 'Cliente Correntista ' || i
    END AS name,
    NOW() - ((i % 365) || ' days')::interval AS created_at
FROM generate_series(2, 1000001) AS i
ON CONFLICT (document_number) DO NOTHING;

-- 2. Inserir 1.000.000 de contas bancárias vinculadas a cada cliente
INSERT INTO account (customer_id, balance_cents, transfer_limit_cents, created_at)
SELECT 
    c.id,
    ((c.id * 12345) % 1500000 + 25000)::bigint AS balance_cents, -- Saldo entre R$ 250 e R$ 15.000
    CASE 
        WHEN c.name LIKE '%LTDA%' THEN 10000000 -- PJ: Limite R$ 100.000
        ELSE 100000 -- PF/MEI: Limite R$ 1.000
    END AS transfer_limit_cents,
    c.created_at
FROM customer c
WHERE c.id >= 2 AND NOT EXISTS (
    SELECT 1 FROM account a WHERE a.customer_id = c.id
);

COMMIT;

ANALYZE customer;
ANALYZE account;

SELECT 
    (SELECT count(*) FROM customer) AS total_clientes,
    (SELECT count(*) FROM account) AS total_contas;
