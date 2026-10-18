<<<<<<< HEAD
# BANCO 60+ | Core Bancário & Motor Antifraude Pix Seguro 60+
=======
# Pix Seguro 60+
>>>>>>> dd3a26cccfde9cdbed8f9d44aa646efbc8b42bca

**Integrantes:** Isadora de Francisco, Henrique Manco e Vitor Robusti — Hackathon QI Tech 2026 · motor v0.1 (`engine_config` versão 1)

<<<<<<< HEAD
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL_16-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Deploy-Docker_Compose-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Pytest](https://img.shields.io/badge/Tests-123%20Passed%20(100%25%20Domain%20Cov)-success.svg?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![SLA](https://img.shields.io/badge/Latency%20P50-38.4ms%20(SLA%20%3C%20300ms)-brightgreen.svg)](./docs/politica-resiliencia-sla-antifraude.md)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)

> **Documento Base:** RFC: BANCO 60+, com saldo protegido, Cofre Antivícios, Contato de Confiança e Motor Antifraude Pix Seguro 60+  
> **Autores da RFC:** Isadora de Francisco, Henrique Manco e Viitor Robusti  
=======
Antifraude de Pix para um banco de público 60+ (aposentados e pensionistas, renda estável, pouca fluência digital). A fricção só aparece onde há dúvida: aprovar é o padrão, 2FA é o meio-termo e reprovar exige risco claro.

> Tudo que não vem da pesquisa do time está marcado como **hipótese**. Os limiares se ancoram em limites reais do Banco Central, mas precisam de calibração (ver [Resultado do backtest](#resultado-do-backtest)). A API bancária sobre a qual o motor roda está descrita em [docs/banco-60.md](docs/banco-60.md).
>>>>>>> dd3a26cccfde9cdbed8f9d44aa646efbc8b42bca

## Como o motor de decisão funciona

<<<<<<< HEAD
## Sumário
1. [Contextualização e Proposta do Projeto](#1-contextualização-e-proposta-do-projeto)
2. [As Seis Garantias Fundamentais](#2-as-seis-garantias-fundamentais)
3. [Arquitetura da Solução e Decisões Técnicas](#3-arquitetura-da-solução-e-decisões-técnicas)
4. [Modelo de Dados (PostgreSQL — Schemas `public` e `fraude`)](#4-modelo-de-dados-postgresql)
5. [Passo a Passo de Instalação e Execução](#5-passo-a-passo-de-instalação-e-execução)
6. [Execução dos Testes Automatizados e Cobertura (123 Testes)](#6-execução-dos-testes-automatizados)
7. [Catálogo de Endpoints da API (Core Bancário + Antifraude Pix)](#7-catálogo-de-endpoints-da-api)
8. [Exemplos Práticos de Uso](#8-exemplos-práticos-de-uso)
9. [Matriz de Códigos de Erro (`BNK` e `AFP`)](#9-matriz-de-códigos-de-erro-bnk-e-afp)
10. [Motor Antifraude Pix Seguro 60+ (Regras, Banco de Dados e Telemetria)](#10-motor-antifraude-pix-seguro-60-regras-banco-de-dados-e-telemetria)
11. [Estrutura do Projeto](#11-estrutura-do-projeto)
=======
O motor recebe o Pix **antes de o dinheiro sair** e responde `approved`, `two_factor_required` ou `rejected`. Tudo acontece em **uma passagem síncrona, sem chamada externa e sem analista**. Ele roda sobre o banco do Banco 60+ (RFC anterior) como o **passo 4b** do funil de transferência: depois do Cofre Antivícios e antes da trava das contas.
>>>>>>> dd3a26cccfde9cdbed8f9d44aa646efbc8b42bca

### Onde o motor entra no Banco 60+ (passo 4b) e o 2FA

![Integração do motor no passo 4b do Banco 60+ e fluxo do 2FA](docs/diagramas/01-integracao-passo-4b.svg)

<details>
<summary>Código Mermaid deste diagrama</summary>

```mermaid
flowchart TD
    A["App: POST /transfer<br/>com Idempotency-Key"] --> B["transaction-api, passos 1 a 4<br/>valida, busca contas, reserva a chave, Cofre"]
    B --> C["4b: chama o motor<br/>id do Pix = Idempotency-Key"]
    C --> D{"Resposta do motor"}
    D -- approved --> E["Passos 5 a 8: trava as contas,<br/>confere saldo, grava o ledger, COMMIT"]
    E --> F["201 para o app"]
    D -- rejected --> G["ROLLBACK<br/>422 BNK004008 BLOCKED_FOR_SAFETY"]
    D -- "sem resposta ou 5xx" --> H["503 BNK004010<br/>repetir com a mesma chave"]
    D -- two_factor_required --> I["ROLLBACK, 422 BNK004009<br/>challenge_type e friction_script_key"]
    I --> J["POST .../second_factor<br/>QI Tech: pix_transfer com tfa_info"]
    J --> K["QI envia token de 6 caracteres por SMS ou e-mail<br/>ao cliente ou ao Contato de Confiança"]
    K --> L["PUT .../second_factor/token<br/>token e friction_answer"]
    L --> M{"Respondeu YES em<br/>CALL_COACHING_CHECK?"}
    M -- "sim, sem Contato" --> G
    M -- "sim, com Contato consentido" --> O["TRUSTED_CONTACT_APPROVAL<br/>novo desafio para o Contato"]
    O --> J
    M -- não --> P{"QI valida o token"}
    P -- "sent ou pending" --> N["approved, grava second_factor_at"]
    N --> E
    P -- "token errado ou expirado" --> L
    P -- "5 tentativas erradas" --> G
```

</details>

A análise é gravada no schema `fraude` com `COMMIT` próprio, antes da trava das contas. O `ROLLBACK` da `transaction-api` não apaga o rastro de um Pix barrado.

### Fluxo de um Pix dentro do motor

![Fluxo de um Pix dentro do motor](docs/diagramas/02-fluxo-do-pix.svg)

<details>
<summary>Código Mermaid deste diagrama</summary>

```mermaid
flowchart TD
    A["POST /pix/transaction"] --> B{"Token, JSON Schema,<br/>fuso e CPF/CNPJ válidos?"}
    B -- não --> X["400, 403 ou 422 (AFP)<br/>nada é gravado"]
    B -- sim --> C["Reserva o id<br/>INSERT ... ON CONFLICT DO NOTHING"]
    C --> D{"O id já existia?"}
    D -- "sim, mesmo corpo" --> R1["200: devolve a análise original<br/>ou aplica o 2FA concluído"]
    D -- "sim, outro corpo" --> R2["409 AFP000004"]
    D -- não --> E["Trava só o pagador<br/>pg_advisory_xact_lock"]
    E -- "espera maior que 2 s" --> R3["503 AFP000009, ROLLBACK"]
    E --> F["Lê histórico, ledger, aparelho,<br/>reputação do destino e Open Finance"]
    F --> G{"Alguma eliminatória<br/>E1 a E6?"}
    G -- sim --> REJ["rejected"]
    G -- não --> H["Soma os pontos<br/>com teto por família"]
    H --> I{"score maior ou igual ao<br/>corte de reprovar da faixa?"}
    I -- sim --> REJ
    I -- não --> J{"score maior ou igual ao corte<br/>de 2FA ou algum piso ativo?"}
    J -- sim --> TFA["two_factor_required"]
    J -- não --> APR["approved"]
    REJ --> K["Grava análise, regras, aparelho, reputação,<br/>marcações e aviso na outbox, COMMIT"]
    TFA --> K
    APR --> K
    K --> L["201 com key, status e metadata"]
```

</details>

Dentro da trava só há consulta ao banco e regras em memória; nada externo é chamado. Pagadores diferentes não esperam um pelo outro.

### Arquitetura do código

Seguimos a estrutura do Base Service. A regra de negócio fica em `src/domain/`, sem dependência de banco nem de framework.

![Arquitetura do código](docs/diagramas/03-arquitetura.svg)

<details>
<summary>Código Mermaid deste diagrama</summary>

```mermaid
flowchart TD
    TA["transaction-api<br/>do Banco 60+"] -- "INTERNAL-TOKEN" --> MW["middlewares<br/>token, sessão, log"]
    MW --> RS["resources/pix.py<br/>schemas/post_pix_transaction.json"]
    RS --> CT["controllers/<br/>avaliar_pix_controller.py"]
    CT --> EN
    subgraph DM["domain/, sem banco nem framework"]
        direction TB
        EN["engine.py<br/>ordem, teto, pisos, decide"]
        RU["rules/<br/>eliminatory, scoring, channel"]
        FA["facts, reputation,<br/>payer_class, statistics"]
        EN --> RU
        RU --> FA
    end
    CT --> RP["repositories/<br/>fraud_repository.py"]
    RP --> BK
    RP --> FR
    subgraph PG["PostgreSQL do Banco 60+"]
        BK[("schema do banco<br/>customer, account, ledger_entry,<br/>notification_outbox")]
        FR[("schema fraude<br/>pix_analysis, pix_rule_result,<br/>engine_config, reputação")]
    end
    CT --> DT["dtos/pix_dto.py"]
    DT -- "key, status, metadata" --> TA
```

</details>

O repositório é o único ponto que fala com o banco. O motor só lê as tabelas do Banco 60+ e só escreve no schema `fraude` e na `notification_outbox`.

### Garantias

1. **Decisão em uma passagem, sem chamada externa.** O Open Finance entra por carga assíncrona em tabela local, e o 2FA roda depois da resposta.
2. **Fricção só onde há dúvida.** Aprovar é o padrão.
3. **Cofre antes do score.** As eliminatórias rodam antes da pontuação.
4. **Nada em dobro.** O `id` do Pix é único, e reenviar devolve a análise existente.
5. **Histórico completo.** Cada Pix fica gravado com decisão, pontos e a evidência numérica de cada regra.
6. **Motivo claro sem ensinar o golpista.** O status é simples. Os motivos ficam na `metadata`, que só a `transaction-api` lê (com `INTERNAL-TOKEN`). O app recebe apenas a `customer_message_key`.

### Rotas

| Método | Caminho | O que faz |
| --- | --- | --- |
| `POST` | `/pix/transaction` | Analisa o Pix, grava e responde. `201` na primeira vez; `200` na repetição do mesmo corpo |
| `GET` | `/pix/transaction/{id}` | Devolve a análise gravada; `404` se não existe |
| `POST` | `/pix/feedback` | Grava o rótulo `{ transaction_id, is_fraud, reason }` (evolução: massa rotulada) |
| `POST` | `/pix/transaction/{id}/second_factor` | Abre o 2FA na QI Tech para um Pix em `two_factor_required`: `201` na primeira vez, `200` se o desafio já está aberto |
| `PUT` | `/pix/transaction/{id}/second_factor/token` | Confirma o token na QI Tech (com `friction_answer` opcional) |
| `PATCH` | `/pix/transaction/{id}/second_factor/token` | Pede à QI Tech um novo token (reinicia os 5 minutos) |
| `GET` | `/health_check` | Diz se está de pé (`204`) |

<<<<<<< HEAD
A suíte automatizada conta com **123 testes (100% de aprovação e 0 warnings)**, cobrindo **100% do domínio de regras antifraude (`src/domain/`)**, validações de contrato JSON Schema, fluxos de segundo fator (2FA Biométrico e Social), *Transactional Outbox* e cenários de concorrência massiva multi-thread no banco de dados.

### Executar a suíte de testes via Docker (Recomendado):
Não é necessário instalar Python na máquina hospedeira:

```bash
docker compose --profile test run --rm test
```

> **Resultado esperado:** `123 passed in ~9.9s` (100% de sucesso).

### Executar localmente com Python e Relatório de Cobertura / Benchmark:
```powershell
# Criação e ativação do ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Instalação das dependências de teste
pip install -r requirements-dev.txt

# Execução dos 123 testes + cobertura de 100% do domínio antifraude
pytest --cov=src/domain --cov-report=term-missing

# Execução do benchmark de latência etapa por etapa da API do motor
python scripts/benchmark_telemetry.py

# Inspeção das tabelas e linhas atuais do PostgreSQL
python scripts/inspect_db.py
```

---

## 7. Catálogo de Endpoints da API

Todas as rotas (exceto `/` e `/health_check`) exigem o cabeçalho de autenticação interna comparado em tempo constante (`hmac.compare_digest`):
```http
INTERNAL-TOKEN: default_token
```

| Método | Rota | Cabeçalhos Obrigatórios | Descrição | Status Sucesso |
| :--- | :--- | :--- | :--- | :---: |
| `GET` | `/` | — | Identificação da API | `200` |
| `GET` | `/health_check` | — | Checagem de saúde da aplicação | `204` |
| `POST` | `/customer` | `INTERNAL-TOKEN` | Cadastra cliente PF ou PJ | `201` |
| `GET` | `/customer/{customer_key}` | `INTERNAL-TOKEN` | Consulta cliente por chave UUID | `200` |
| `POST` | `/account` | `INTERNAL-TOKEN` | Cria conta (saldo 0 e MCC 7995 bloqueado) | `201` |
| `GET` | `/account/{account_key}` | `INTERNAL-TOKEN` | Consulta saldo, limites e MCCs bloqueados | `200` |
| `PUT` | `/account/{account_key}/blocked_mcc` | `INTERNAL-TOKEN` | Atualiza lista de MCCs bloqueados do Cofre | `200` |
| `POST` | `/account/{account_key}/trusted_contact` | `INTERNAL-TOKEN` | Cadastra contato de confiança (máx. 2) | `201` |
| `POST` | `/account/{account_key}/deposit` | `INTERNAL-TOKEN`, `Idempotency-Key` | Realiza depósito (em centavos) | `201` / `200` |
| `POST` | `/account/{account_key}/purchase` | `INTERNAL-TOKEN`, `Idempotency-Key` | Realiza compra com cartão (valida Cofre) | `201` / `200` |
| `POST` | `/transfer` | `INTERNAL-TOKEN`, `Idempotency-Key` | Transfere valores com tarifa de R$ 1,00 | `201` / `200` |
| `GET` | `/account/{account_key}/statement` | `INTERNAL-TOKEN` | Extrato paginado (`limit`, `page`) | `200` |
| `POST` | `/pix/transaction` | `INTERNAL-TOKEN` | Avalia Pix no Motor Antifraude 60+ (e processa 2FA em replay) | `201` / `200` |
| `GET` | `/pix/transaction/{id}` | `INTERNAL-TOKEN` | Consulta resultado e metadados de uma análise Pix | `200` |
| `POST` | `/pix/feedback` | `INTERNAL-TOKEN` | Registra feedback de fraude/legítimo sobre um Pix avaliado | `201` |

---

## 8. Exemplos Práticos de Uso

### 1. Cadastrar um Cliente (com CPF ou CNPJ formatado)
```bash
curl -X POST http://localhost:3000/customer \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sebastião da Silva",
    "email": "sebastiao@exemplo.com",
    "document_number": "529.982.247-25"
  }'
```

### 2. Abrir uma Conta
```bash
curl -X POST http://localhost:3000/account \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_key": "<UUID_DO_CLIENTE>",
    "transfer_limit_cents": 100000
  }'
```

### 3. Cadastrar Contato de Confiança (Máximo 2)
```bash
curl -X POST http://localhost:3000/account/<UUID_DA_CONTA>/trusted_contact \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Mariana da Silva (Filha)",
    "channel": "EMAIL",
    "address": "mariana.filha@exemplo.com"
  }'
```

### 4. Realizar Depósito Idempotente (R$ 500,00)
```bash
curl -X POST http://localhost:3000/account/<UUID_DA_CONTA>/deposit \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Idempotency-Key: dep-001-abc" \
  -H "Content-Type: application/json" \
  -d '{
    "amount_cents": 50000
  }'
```

### 5. Realizar Transferência com Tarifa (R$ 100,00 + R$ 1,00 de tarifa)
```bash
curl -X POST http://localhost:3000/transfer \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Idempotency-Key: trf-001-xyz" \
  -H "Content-Type: application/json" \
  -d '{
    "from_account_key": "<UUID_CONTA_ORIGEM>",
    "to_account_key": "<UUID_CONTA_DESTINO>",
    "amount_cents": 10000
  }'
```

### 6. Consultar Extrato Paginado
```bash
curl -X GET "http://localhost:3000/account/<UUID_DA_CONTA>/statement?limit=10&page=0" \
  -H "INTERNAL-TOKEN: default_token"
```

### 7. Avaliar Transação Pix no Motor Antifraude (`POST /pix/transaction`)
```bash
curl -X POST http://localhost:3000/pix/transaction \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "pix-demo-001",
    "amount": 30000,
    "transaction_date": "2026-10-18T14:00:00-03:00",
    "type": "payment",
    "source": {
      "channel": "app",
      "device_id": "device-maria-01",
      "geolocation": {"latitude": -23.5505, "longitude": -46.6333, "accuracy_m": 12.0},
      "remote_access_detected": false,
      "call_in_progress": true
    },
    "source_account": {
      "document_number": "529.982.247-25",
      "has_trusted_contact": true,
      "owner": {"name": "Sebastião da Silva"}
    },
    "destination_account": {
      "document_number": "111.444.777-35",
      "participant": "60701190",
      "branch": "0001",
      "number": "12345678",
      "owner": {"name": "Destinatário"}
    }
  }'
```

---

## 9. Matriz de Códigos de Erro (`BNK` e `AFP`)

Todas as respostas de erro retornam um envelope padronizado contendo `title`, `description`, `translation` (em português), `code`, `request_id` e lista de `errors`:
=======
Todas as rotas, menos `/health_check`, exigem o cabeçalho `INTERNAL-TOKEN`. Ausente ou errado, a resposta é `403 AFP000002`, e a comparação é feita em tempo constante. **Reprovar um Pix não é erro**: a resposta é `201` com `status: rejected`.

**Entrada.** Valores em centavos (inteiro ≥ 1) e `transaction_date` com fuso. Campos opcionais ausentes desligam a regra correspondente e entram em `metadata.inputs_missing`; a requisição não falha. `source.channel` aceita `internet`, `celular`, `computador`, `tablet` e `relogio`. O alias `app` é gravado como `celular`.
>>>>>>> dd3a26cccfde9cdbed8f9d44aa646efbc8b42bca

```json
{
  "id": "6f1c2b0e-0d7a-4f1e-9a51-2c1f8f0b9a10",
  "amount": 18900,
  "transaction_date": "2026-10-15T14:35:00-03:00",
  "type": "payment",
  "source_account": { "document_number": "529.982.247-25", "has_trusted_contact": true },
  "destination_account": {
    "document_number": "111.444.777-35",
    "participant": "60701190", "branch": "0001", "number": "4455667"
  },
  "source": {
    "channel": "app",
    "device_id": "cel-maria",
    "remote_access_detected": false,
    "call_in_progress": false
  }
}
```

<<<<<<< HEAD
### 9.1 Códigos do Core Bancário (`BNK`)

| HTTP Status | Código BNK | Cenário de Ocorrência |
| :---: | :---: | :--- |
| `400` | `BNK000001` | Corpo, cabeçalho ou parâmetro de consulta fora do formato esperado |
| `403` | `BNK000002` | `INTERNAL-TOKEN` ausente ou incorreto |
| `400` | `BNK000011` | Cabeçalho `Idempotency-Key` ausente em operação de dinheiro |
| `409` | `BNK000012` | Mesma chave de idempotência reenviada com corpo diferente |
| `404` | `BNK000404` | Rota ou recurso HTTP inexistente |
| `409` | `BNK001001` | Documento (CPF/CNPJ) ou e-mail já cadastrado |
| `422` | `BNK001002` | CPF ou CNPJ com dígitos verificadores inválidos |
| `404` | `BNK001003` | Cliente não encontrado |
| `404` | `BNK002001` | Conta não encontrada |
| `409` | `BNK002002` | Cliente já possui conta cadastrada |
| `400` | `BNK002003` | Limite por transferência menor que 1 centavo |
| `400` | `BNK002004` | Lista de MCCs fora do formato (deve conter 4 dígitos por MCC) |
| `409` | `BNK003001` | Limite de contatos de confiança atingido (máximo de 2 por conta) |
| `409` | `BNK003002` | Contato de confiança com mesmo endereço já cadastrado na conta |
| `409` | `BNK004001` | Saldo insuficiente (considera valor + tarifa na transferência) |
| `422` | `BNK004002` | Transferência para a mesma conta (origem igual ao destino) |
| `422` | `BNK004003` | Valor da transferência excede o limite configurado na conta |
| `422` | `BNK004004` | Operação bloqueada pelo Cofre Antivícios (MCC 7995 / apostas) |
| `422` | `BNK004005` | CNPJ do lojista com dígitos verificadores inválidos |
| `400` | `BNK004006` | Valor monetário menor que 1 centavo |
| `503` | `BNK004007` | Timeout ao aguardar trava de linha no banco de dados |

### 9.2 Códigos do Motor Antifraude Pix (`AFP`)

| HTTP Status | Código AFP | Cenário de Ocorrência |
| :---: | :---: | :--- |
| `400` | `AFP000001` | Corpo, cabeçalho ou parâmetro da requisição Pix fora do schema esperado |
| `403` | `AFP000002` | Cabeçalho `INTERNAL-TOKEN` ausente ou inválido nas rotas `/pix/*` |
| `404` | `AFP000003` | Nenhuma análise Pix encontrada para o `id` consultado |
| `409` | `AFP000004` | Conflito de idempotência: mesmo `id` de Pix reenviado com payload diferente |
| `422` | `AFP000005` | Dígitos verificadores inválidos em `source_account.document_number` ou `destination_account.document_number` |
| `400` | `AFP000006` | `transaction_date` sem fuso horário (timezone) ou no futuro (`> 5 min`) |
| `422` | `AFP000007` | `source.channel` fora dos canais aceitos (`internet`, `celular`, `computador`, `tablet`, `relogio`, `app`) |
| `400` | `AFP000008` | `amount` inválido (não inteiro, booleano ou menor que 1 centavo) |
| `503` | `AFP000009` | Timeout (`> 2s`) ao aguardar `pg_advisory_xact_lock` do pagador concorrente |

---

## 10. Motor Antifraude Pix Seguro 60+ (Regras, Banco de Dados e Telemetria)

O **Motor Antifraude Pix Seguro 60+** foi projetado com **Arquitetura Hexagonal / Domínio Puro**: a função [`evaluate(context, config)`](./src/domain/engine.py) opera 100% em memória sobre *snapshots* imutáveis (`@dataclass(frozen=True)`), enquanto todos os pesos, janelas temporais, tetos de família e *feature flags* são parametrizados no banco na tabela `fraude.engine_config`.

### 10.1 Catálogo das 26 Regras, Tetos por Família e Pisos de 2FA

| Família / Teto | Código | Regra | Efeito / Pontuação (`engine_config v1`) |
| :--- | :---: | :--- | :--- |
| **Eliminatórias** *(Rejeição Imediata)* | `E1` | Cofre Antivícios por MCC | `REJECTED` se o `merchant_mcc` do destinatário estiver bloqueado na conta |
| | `E2` | Destino Marcado (`MARCADA`) | `REJECTED` em pagamentos (exceto `refund`) sob flag BCB 587 |
| | `E3` | Quarentena Policial (`QUARENTENA`) | `REJECTED` se o destinatário não for beneficiário de confiança (`H2`) |
| | `E4` | Limite Noturno PF e MEI (`20h–06h`) | `REJECTED` acima de R$ 1.000,00 para destinatário não cadastrado há $\ge 24\text{h}$ |
| | `E5` | Aparelho Desconhecido / Maturando | `REJECTED` se soma diária no aparelho $> \text{R\$ } 1.000$; **Piso de 2FA** se Pix $> \text{R\$ } 200$ |
| | `E6` | Banimento Regulatório de *Bets* | `REJECTED` se CNPJ destino constar ativo em `fraude.bet_destination` (exceto `refund`) |
| **Aparelho** *(Teto: 45 pts)* | `D1` | Estágio de Maturação do Aparelho | `+40` (desconhecido) ou `+20` (maturando $< 24\text{h}$) |
| | `D2` | Aparelho Compartilhado | `+35` se $\ge 3$ documentos distintos usaram o aparelho em 7 dias |
| | `D3` | *Cold Start* (Primeiro Pix) | `+5` quando pagador não possui histórico anterior (suprime `D1` e `E5`) |
| **Geografia** *(Teto: 40 pts)* | `G1` | Distância da Mediana Habitual (90d) | `+25` ($> 500\text{ km}$) ou `+15` ($> 100\text{ km}$) |
| | `G2` | Deslocamento Impossível (Teletransporte) | `+35` e **Piso de 2FA** ($\ge 100\text{ km}$ a $\ge 800\text{ km/h}$ ou $\ge 20\text{ km}$ a $\ge 300\text{ km/h}$) |
| | `G4` | Geolocalização Ausente em Mobile | `+5` em `celular` ou `tablet` sem coordenadas GPS |
| **Destino** *(Teto: 55 pts)* | `C1` | Novo Beneficiário | `+15` se nunca houve Pix aprovado e liquidado para a `destination_key` |
| | `C2` | Idade da Conta Destino | `+30` ($< 7\text{d}$), `+20` ($< 30\text{d}$) ou `+5` ($< 90\text{d}$) |
| | `C5` | Muitos Pagadores em 24h (Conta Mula) | `+25` ($\ge 5$ pagadores) ou `+15` ($\ge 3$ pagadores) + script `MULE_DESTINATION_CHECK` |
| | `C6` | Repasse Rápido em 1h (*Fast-Forward*) | `+25` se o destino repassou $\ge 50\%$ do que recebeu na última hora |
| | `C7` | Reputação Endógena Suspeita | `+30` ($\ge 50\%$ suspeitas) ou `+15` ($\ge 30\%$ suspeitas) com $\ge 4$ análises |
| | `C8` | Pix Teste Seguido de Drenagem (72h) | `+30` e **Piso de 2FA** (teste $\le \text{R\$ } 10$ seguido de Pix $\ge \max(\text{R\$ } 500, 20\times \text{teste})$) |
| **Comportamento** *(Teto: 60 pts)* | `K1` | Canal Incomum (Segmento 90d) | `+10` se o segmento (`mobile`/`desktop`/`relogio`) representa $< 10\%$ do histórico |
| | `P1` | Valor Atípico Acima do Percentil 95 | `+30` ($> 3\times \text{P95}$), `+20` ($> \text{P95}$) ou `+10` ($> \text{R\$ } 500$ sem histórico) |
| | `P2` | Horário Incomum no Histograma | `+10` se a janela de $\pm 1\text{h}$ tem $< 5\%$ das observações históricas |
| | `M1` | Acumulado em 24 Horas | `+20` se a soma em 24h ultrapassar $3\times$ o limiar P95 |
| | `M2` | Fracionamento (*Smurfing* perto do Teto) | `+30` se houver $\ge 3$ Pix em 24h entre $80\%$ e $100\%$ dos tetos (R$ 200 ou R$ 1.000) |
| | `V1` | Rajada de Pix em 10 Minutos (*Burst*) | `+40` ($\ge 5$ Pix em 10 min) ou `+25` ($\ge 3$ Pix em 10 min) |
| | `V2` | Pulverização para Novos Destinos (1h) | `+30` se enviar para $\ge 3$ destinos inéditos na última hora |
| **Fora do Teto** *(Risco Direto & Bônus)* | `K2` | Relógio Inteligente (*Smartwatch*) | `0 pts` e **Piso de 2FA** para Pix $> \text{R\$ } 200,00$ no canal `relogio` |
| | `O1` | Conta Origem Recente | `+10` se a conta pagadora tiver menos de 30 dias |
| | `R1` | Acesso Remoto ou Ligação em Curso | `+30` (acesso remoto) + `+30` (ligação ativa) + **Piso de 2FA** (`CALL_COACHING_CHECK`) |
| | `R2` | Automação / Bot em Canal Desktop | `+40` e **Piso de 2FA**; **escala para `REJECTED`** quando combinada com `C1` ou `V1` |
| | `F1` | Valor vs. Renda Mensal (Local + OF) | `+25` ($> 2\times$ renda 30d) ou `+15` ($> 1\times$ renda 30d) |
| | `F2` | Drenagem de Saldo ($\ge 80\%$) | `+15` se o Pix consumir $\ge 80\%$ do saldo somado (Conta Local + Open Finance) |
| | `F3` | Conta de Passagem (*Pass-Through* 30m) | `+30` (`+15` reforço de queda no Open Finance) + **Piso de 2FA** (`PASSTHROUGH_CHECK`) |
| | `H2` | Beneficiário de Confiança (Recorrente) | **`-25`** ($\ge 3$ Pix em $\ge 3$ meses distintos dentro de $\pm 20\%$ da mediana, sem `C8`/marcação) |
| **Pisos Globais** | `X1` | Convergência de Sinais Fracos | **Piso de 2FA** se $\ge 3$ regras pontuarem entre `10` e `19` pontos brutos |
| | `X2` | Alto Valor para Novo Destinatário | **Piso de 2FA** para qualquer Pix na **Faixa D** ($> \text{R\$ } 5.000,00$) com `C1` |

---

### 10.2 O que o Motor Puxa do Banco de Dados e Valores Reais das Tabelas

Em cada chamada `POST /pix/transaction`, o [`FraudRepository`](./src/repositories/fraud_repository.py) consulta e atualiza as seguintes tabelas nos schemas `public` e `fraude`:

1. **`fraude.engine_config` (Leitura):** Carrega a versão ativa onde `active_from <= transaction_date` (`version = 1`, `active_from = '2026-01-01T00:00:00Z'`), contendo todas as faixas (`A` até R$ 200, `B` até R$ 1.000, `C` até R$ 5.000, `D` acima de R$ 5.000), pesos e flags.
2. **`fraude.bet_destination` (Leitura — Regra `E6`):** Verifica se o CNPJ do destinatário consta ativo na lista regulatória de apostas:
   | `cnpj` | `razao_social` | `source` | `active` |
   | :--- | :--- | :--- | :---: |
   | `99000001000101` | `APOSTA FICTICIA UM LTDA` | `seed_demo` | `true` |
   | `99000002000148` | `BET FICTICIA DOIS LTDA` | `seed_demo` | `true` |
   | `99000003000192` | `CASSINO FICTICIO TRES LTDA` | `seed_demo` | `true` |
3. **Histórico e Perfil do Pagador (Leitura — janela de 125 dias):**
   * `fraude.pix_analysis` + `public.bank_transaction`: histórico de Pix anteriores do `source_hash` (valores, horários, coordenadas GPS, canal, `device_id` e liquidação);
   * `public.account`, `public.blocked_mcc`, `public.trusted_contact`, `public.ledger_entry` e `fraude.of_payer_profile`: saldo atual, data de abertura da conta, MCCs bloqueados no Cofre, consentimento do Contato de Confiança (`approval_consent_at`), lançamentos contábeis (`DEPOSIT`/`TRANSFER`) e saldos/rendas externos via Open Finance.
4. **Tabelas de Estado Pré-Calculadas (Leitura e Escrita Atômica via `ON CONFLICT DO UPDATE`):**
   * **`fraude.destination_reputation`** (acumula análises, reprovações, 2FA, pagadores em 24h e taxa de repasse em 1h):
     | `destination_key` (SHA-256) | `analyses_count` | `rejected_count` | `two_factor_count` | `payers_24h` | `forwarded_ratio_1h` |
     | :--- | :---: | :---: | :---: | :---: | :---: |
     | `f4f2c9f1b50cd3a5...f3a6a` | `60` | `56` | `2` | `1` | `0.0000` |
     | `596639d67d941368...06f4d` | `1` | `1` | `0` | `1` | `0.0000` |
   * **`fraude.device_seen`** (controla a primeira/última aparição de cada aparelho por pagador e compartilhamento `D2`):
     | `device_id` | `source_hash` (SHA-256) | `first_seen` | `last_seen` | `tx_count` |
     | :--- | :--- | :---: | :---: | :---: |
     | `device-bench-01` | `ec8fcc450d86eb39...6528` | `2026-10-18 08:42:00Z` | `2026-10-18 08:42:03Z` | `60` |
     | `device-headless-chrome-01` | `b217f82798b7bbd4...398d` | `2026-10-18 08:40:55Z` | `2026-10-18 08:40:55Z` | `1` |
5. **Auditoria de Análises e Regras (`fraude.pix_analysis` e `fraude.pix_rule_result`):**
   * Amostra de linhas reais gravadas em `fraude.pix_analysis`:
     | `id` | `pix_id` | `status` | `score` | `value_band` | `amount_cents` | `channel` | `customer_message_key` |
     | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
     | `106` | `PIX-HTTP-d56fb67352a84b19...` | `rejected` | `120` | `A` | `17900` (R$ 179,00) | `celular` | `BLOCKED_FOR_SAFETY` |
     | `102` | `PIX-HTTP-052d9c3439a74ce3...` | `rejected` | `90` | `A` | `17800` (R$ 178,00) | `celular` | `BLOCKED_FOR_SAFETY` |
   * Amostra de linhas reais gravadas em `fraude.pix_rule_result` (para `analysis_id = 106`):
     | `id` | `analysis_id` | `rule_code` | `points` | `evidence` (JSONB) |
     | :---: | :---: | :---: | :---: | :--- |
     | `207` | `106` | `D1` | `20` | `{"device_stage": "maturing"}` |
     | `208` | `106` | `C7` | `30` | `{"analyses": 59, "ratio": 0.9661}` |
     | `209` | `106` | `V1` | `40` | `{"pix_10min": 60}` |
     | `210` | `106` | `R1` | `30` | `{"channel": "celular", "call_in_progress": true}` |

---

### 10.3 Tempo Gasto em Todo o Processo da API do Motor (Benchmark Real)

Medição obtida com [`scripts/benchmark_telemetry.py`](./scripts/benchmark_telemetry.py) sobre 30 transações sequenciais contra o PostgreSQL:

| Etapa do Processo (`AvaliarPixController`) | Mínimo (ms) | Mediana / P50 (ms) | Média (ms) | P95 (ms) | Máximo (ms) | % do Tempo (P50) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Normalização, Validação e Hash SHA-256** (`_normalize`, `_validate`, `_request_hash`) | `0.094` | **`0.123`** | `0.134` | `0.183` | `0.315` | **0.4%** |
| **2. Busca de Contas Origem/Destino** (`_find_account`) | `3.400` | **`3.971`** | `5.887` | `5.855` | `55.411` | **13.1%** |
| **3. Reserva de Idempotência** (`reserve_analysis` — `INSERT ON CONFLICT`) | `2.118` | **`2.639`** | `2.948` | `3.855` | `10.176` | **8.7%** |
| **4. Trava por Pagador** (`_lock_payer` — `pg_advisory_xact_lock` com timeout `2s`) | `0.776` | **`1.042`** | `1.219` | `1.883` | `2.021` | **3.4%** |
| **5. Carregamento de Snapshots** (`load_payer_snapshot`, `load_destination_snapshot`, `load_device_snapshot`) | `7.826` | **`10.809`** | `11.077` | `13.601` | `23.491` | **35.6%** |
| **6. Avaliação Pura do Motor de Regras** (`evaluate(context, config)` — 26 regras em memória) | `0.193` | **`0.271`** | `0.478` | `0.364` | `6.721` | **0.9%** |
| **7. Persistência, Reputação, Outbox e Commit** (`persist_analysis` + `commit`) | `9.166` | **`11.297`** | `11.251` | `12.368` | `18.951` | **37.2%** |
| **Total Interno do Controller** (`AvaliarPixController.avaliar`) | `26.093` | **`30.354`** | `33.001` | `33.217` | `116.758` | **100%** |
| **HTTP End-to-End (`POST /pix/transaction` — Nova Análise)** | `35.179` | **`38.369`** | `40.017` | `42.967` | `85.709` | **SLA < 300 ms (Folga de 87%)** |
| **Replay Idempotente (`200 OK` — Mesma chave e corpo)** | `6.174` | **`7.486`** | `7.749` | `10.115` | `10.660` | **SLA < 300 ms** |
| **Replay de Confirmação 2FA (`second_factor_passed=True`)** | `6.094` | **`8.225`** | `8.769` | `12.363` | `16.125` | **SLA < 300 ms** |

---

### 10.4 Mapa da Suíte de Testes e Cobertura de 100% do Domínio

| Suíte / Arquivo | Qtd. Testes | Base Acionada | O que é verificado |
| :--- | :---: | :---: | :--- |
| [`tests/unit/test_rules_catalog.py`](./tests/unit/test_rules_catalog.py) | `35` | Memória (`conftest.py` lê seed de `database.sql`) | Cobertura unitária exaustiva de todas as regras `E1..E5`, `D1..D3`, `G1..G2`, `C2..C8`, `P1..P2`, `M1..M2`, `V2`, `O1`, `K1..K2`, `R1`, `X2`, `F1..F3`, transições de reputação e funções de identidade/estatística |
| [`tests/unit/test_engine_improvements.py`](./tests/unit/test_engine_improvements.py) | `24` | Memória | Fronteiras inclusivas das faixas `A..D`, função `decide`, banimento de bets (`E6`), níveis de teletransporte (`G2`), teto por família (`capped_score`) e piso `X1` |
| [`tests/unit/test_pix_validation.py`](./tests/unit/test_pix_validation.py) | `14` | Memória | JSON Schema `post_pix_transaction.json`, mapeamento de erros `AFP`, normalização do alias `app` $\to$ `celular` e invariância do `request_hash` no 2FA |
| [`tests/unit/test_fraud_engine.py`](./tests/unit/test_fraud_engine.py) | `12` | Memória | P95 resistente a outlier, limite noturno (`E4`), aluguel recorrente (`H2`), teste+drenagem (`C8`), rajada (`V1`), 2FA Social (`TRUSTED_CONTACT_APPROVAL`) e reconhecimento de MEI |
| [`tests/unit/test_channel_rules.py`](./tests/unit/test_channel_rules.py) | `8` | Memória | Geolocalização ausente (`G4`), chamada ativa (`R1`), automação robótica desktop (`R2`) com escalada para `rejected` e mudança de segmento (`K1`) |
| [`tests/integration/fraud/test_fraud_outbox.py`](./tests/integration/fraud/test_fraud_outbox.py) | `11` | PostgreSQL Real (`DbUtils.rollback()`) | Gravação de Pix retido na `notification_outbox`, idempotência (`201` vs `200` vs `409`), escalada de `friction_answer=YES`, aprovação com `second_factor_passed=True` e endpoint `/pix/feedback` |
| [`tests/integration/fraud/test_fraud_scenarios.py`](./tests/integration/fraud/test_fraud_scenarios.py) | `5` | PostgreSQL Real (`DbUtils.rollback()`) | Cenários ponta a ponta: cliente rotineiro aprovado, quarentena policial (`E3`), desafio e aprovação 2FA, proteção noturna de MEI (`E4`) e bot desktop (`R2`) |
| [`tests/integration/banking/test_bank_api.py`](./tests/integration/banking/test_bank_api.py) + [`test_healthcheck.py`](./tests/integration/test_healthcheck.py) | `14` | PostgreSQL Real (`DbUtils.rollback()`) | Operações bancárias, Cofre Antivícios em compras, concorrência multi-thread de saldo/contatos e preservação de acentuação nos erros |
| **Total** | **123** | **100% Passando** | **100% de cobertura em todos os módulos de regras e entidades de `src/domain/`** |

---

## 11. Estrutura do Projeto

A arquitetura adota separação estrita de responsabilidades entre transporte HTTP, controle transacional, domínio puro de regras e persistência SQL:

```text
bootcamp-entrega-final/
├── database/
│   ├── database.sql               # Esquema DDL completo (schemas public e fraude + seed engine_config v1)
│   └── seed_test_scenarios.sql    # Carga opcional de cenários de demonstração
├── docs/
│   ├── backtest-massa-sintetica.md
│   ├── banco60_banner.jpg
│   ├── como-o-projeto-e-organizado.md
│   ├── motor-antifraude-ajustes.md
│   └── politica-resiliencia-sla-antifraude.md
├── scripts/
│   ├── backtest.py                # Avaliação estatística sobre massa sintética rotulada
│   ├── benchmark_telemetry.py     # Benchmark etapa por etapa da API do motor antifraude
│   ├── inspect_db.py              # Inspeção formatada das tabelas e linhas do PostgreSQL
│   ├── massa_sintetica.py         # Geração de massa sintética de Pix legítimos e golpes
│   └── simulate_fraud_attacks.py  # Simulação de vetores de ataque contra a API
├── src/
│   ├── app.py                     # Entrypoint FastAPI e registro de rotas/middlewares
│   ├── constants.py               # Variáveis de ambiente e configuração
│   ├── database.py                # Engine SQLAlchemy e gerenciamento de contexto por requisição
│   ├── connectors/                # Conectores REST externos com timeout estrito (300 ms)
│   ├── controllers/               # Orquestração transacional (AvaliarPixController, TransactionController...)
│   ├── domain/                    # Núcleo puro do Motor Antifraude Pix (100% em memória, 100% coberto)
│   │   ├── config.py              # Leitura tipada de faixas, janelas, fuso horário e flags
│   │   ├── engine.py              # Orquestrador evaluate(), decide(), capped_score() e 2FA
│   │   ├── entities.py            # Entidades imutáveis (PixRequest, EvaluationContext, Decision...)
│   │   ├── facts.py               # Extração de fatos derivados do histórico (P95, H2, estágio de device)
│   │   ├── identity.py            # Hashing SHA-256 e mascaramento de documentos
│   │   ├── payer_class.py         # Classificação PF / MEI / PJ por documento e razão social
│   │   ├── reputation.py          # Máquina de estados do destinatário (NORMAL -> OBSERVACAO -> QUARENTENA)
│   │   ├── statistics.py          # Percentil linear, mediana e distância geodésica de Haversine
│   │   └── rules/                 # Regras divididas em eliminatory.py, scoring.py e channel.py
│   ├── dtos/                      # Envelopes de saída HTTP (BankDTO, PixAnalysisDTO)
│   ├── errors/                    # Hierarquia de exceções e catálogos BNK e AFP
│   ├── middlewares/               # Token interno (compare_digest), log seguro, request_id e sessão DB
│   ├── models/                    # Modelos SQLAlchemy dos schemas public (banking.py) e fraude (fraud.py)
│   ├── repositories/              # Consultas SQL, travas FOR UPDATE / advisory lock e outbox
│   ├── resources/                 # Adaptadores HTTP FastAPI e validação JSON Schema
│   ├── schemas/                   # Contratos JSON de entrada (post_pix_transaction.json, etc.)
│   └── utils/                     # Validação de dígitos de CPF/CNPJ, UUID e mapeadores de erro
├── tests/
│   ├── unit/                      # 93 testes unitários do motor antifraude e validações (em memória)
│   └── integration/               # 30 testes de integração (banking, fraud, outbox e concorrência)
├── docker-compose.yml             # Orquestração da API, PostgreSQL 16 e perfil de testes
├── Dockerfile                     # Imagem Docker da aplicação
└── requirements.txt               # Dependências de produção
=======
**Saída.** Abaixo, uma resposta real do motor na massa sintética: o terceiro Pix de um fracionamento (três Pix logo abaixo de R$ 200 para destinos novos em pouco tempo). O score 80 passa o corte de 2FA da faixa A (45), mas fica abaixo do de reprovar (85).

```json
{
  "key": "75a4e5f9-d686-4a25-ba60-1955ec92a4c1",
  "status": "two_factor_required",
  "metadata": {
    "engine_version": 1,
    "score": 80,
    "value_band": "A",
    "thresholds": { "two_factor": 45, "reject": 85 },
    "rules_fired": [
      { "code": "G4", "points": 5, "evidence": { "channel": "celular", "segment": "mobile" } },
      { "code": "C1", "points": 15, "evidence": { "previous_pix_to_destination": 0 } },
      { "code": "M2", "points": 30, "evidence": { "ceiling_cents": 20000, "pix_near_ceiling": 3 } },
      { "code": "V2", "points": 30, "evidence": { "new_destinations_1h": 3 } }
    ],
    "floor_applied": [],
    "payer_class": "PF",
    "destination_status": "NORMAL",
    "destination_reputation": { "analyses_count": 0, "suspicious_ratio": 0.0 },
    "notify_trusted_contact": true,
    "customer_message_key": "CONFIRM_IDENTITY",
    "inputs_missing": ["geolocation", "destination_account.created_at"],
    "challenge_type": "CUSTOMER_TOKEN_2FA",
    "friction_script_key": "CONFIRM_IDENTITY",
    "friction_params": {}
  }
}
>>>>>>> dd3a26cccfde9cdbed8f9d44aa646efbc8b42bca
```

## Regras

**Nenhum limiar fica fixo no código.** Todos os parâmetros abaixo são lidos de `fraude.engine_config` (versionado, com `active_from`), e cada análise grava a versão usada. A equipe de dados recalibra inserindo uma versão nova, sem refatorar. Os códigos seguem a pesquisa do time (E, D, G, K, C, P, M, V, O, R, H, X), mais F para os sinais do Open Finance.

### Eliminatórias (rodam antes do score; qualquer uma reprova)

| Regra | Lógica | Parâmetros | Por quê |
| --- | --- | --- | --- |
| **E1 Cofre Antivícios** | O MCC do CNPJ de destino (tabela `merchant`) está nos `blocked_mcc` da conta | padrão `7995` (apostas) | Garantia herdada do Banco 60+: o dinheiro não vai para a aposta que o cliente bloqueou. Quem recebe Pix não informa MCC, então lemos o cadastro do CNPJ |
| **E2 Destino marcado** | Destino com marcação `MARCADA` ativa e `type` diferente de `refund` | validade de 5 anos; flag `ENABLE_BCB_587_RULES` | Res. BCB 587 (publicada em 18/09/2026). Adotamos antes da vigência, com data de expiração na tabela |
| **E3 Quarentena** | Destino em `QUARENTENA` e pagador sem beneficiário de confiança (H2) | até 72 h | Espelho interno do bloqueio cautelar de até 72 h do BC (hipótese: o do BC é do lado recebedor) |
| **E4 Limite noturno** | PF (11 dígitos) ou MEI, das 20h às 6h (fuso `America/Sao_Paulo`), acima do teto, para destino sem pré-cadastro | teto R$ 1.000; pré-cadastro = Pix aprovado ao mesmo destino há 24 h ou mais; PJ só com `APPLY_NIGHT_LIMIT_PJ` | Res. BCB 142/2021. Sequestro-relâmpago acontece à noite, e o 60+ raramente opera nesse horário |
| **E5 Aparelho não conhecido** | Aparelho desconhecido ou em maturação: soma do dia acima do limite reprova; Pix acima do limite vira piso de 2FA | R$ 1.000/dia reprova; R$ 200/Pix piso de 2FA | Res. BCB 403/2024. Reprovamos só o acumulado, porque o neto pode ter dado um celular novo ao avô |
| **E6 Bets** | CNPJ de destino ativo em `fraude.bet_destination`, exceto `refund` | flag `ENABLE_BETS_BAN` | Proibição de Pix para bets. O CNPJ nunca entra na `evidence`; devoluções passam |

**Reconhecimento do MEI (E4).** É feito em memória, sem consulta externa, sobre o nome do titular de um documento de 14 dígitos:

1. normaliza o nome (maiúsculas, sem acento);
2. com sufixo de empresa (`LTDA`, `EIRELI`, `SLU`, `EPP`, `S/A`, `S.A.`), é PJ;
3. se termina com um CPF válido ou com a raiz de 8 dígitos do próprio CNPJ, é MEI;
4. senão, é PJ.

`SA` e `ME` soltos ficam fora da lista para não vetar sobrenomes como "Sá". É uma heurística, por isso fica atrás de uma flag (`ENABLE_MEI_AS_PF`).

### Pontuação

| Regra | Lógica | Parâmetros e pontos | Por quê |
| --- | --- | --- | --- |
| **D1 Estágio do aparelho** | Desconhecido (nunca visto para o pagador), maturando (visto há menos de 24 h) ou conhecido | +40 / +20 / 0 | Aparelho novo é um estágio, não um sim/não. Singapura segura ações de risco por 12 h; o OCBC, por 24 h |
| **D2 Aparelho compartilhado** | Mesmo `device_id` com 3 ou mais documentos em 7 dias | +35 | Contas laranja operadas do mesmo aparelho. Casal no mesmo tablet (2 CPFs) é normal no 60+ |
| **D3 Partida a frio** | Primeira transação do cliente (substitui a D1) | +5 | Sem histórico não dá para dizer que o aparelho é novo |
| **G1 Distância do usual** | Distância até a mediana dos locais dos últimos 90 dias (mín. 5 pontos) | > 100 km +15; > 500 km +25 | Conta tomada opera de outro lugar. A mediana resiste a uma viagem pontual |
| **G2 Deslocamento impossível** | Velocidade desde o último Pix geolocalizado | ≥ 100 km e ≥ 800 km/h, ou ≥ 20 km e ≥ 300 km/h: +35 e piso de 2FA; ignora pontos com precisão pior que 5 km ou com mais de 6 h | 800 km/h é o limite generoso de voo comercial; o nível de 300 km/h pega deslocamentos curtos que nenhum carro faz |
| **G4 Sem geolocalização** | Canal `celular` ou `tablet` sem `geolocation` | +5 | Muitos 60+ negam a permissão, por isso o peso é baixo |
| **K1 Canal incomum** | Segmento do canal (mobile, desktop, relógio) usado em menos de 10% das transações em 90 dias (mín. 5) | +10 | Troca de canal acompanha tomada de conta |
| **K2 Relógio** | Canal `relogio` acima de R$ 200 | piso de 2FA | A tela pequena não mostra o destinatário completo (hipótese) |
| **C1 Beneficiário novo** | Primeiro Pix concluído do par pagador–destino | +15 | Golpe de engenharia social sempre leva a um destino novo |
| **C2 Idade do destino** | Idade da conta de destino | < 7 d +30; < 30 d +20; < 90 d +5 | Conta jovem sugere laranja, mas cerca de 60% das mulas têm mais de 1 ano: nunca decide sozinha |
| **C5 Muitos pagadores** | Pagadores distintos para o destino em 24 h | ≥ 3 +15; ≥ 5 +25 | Mula recebe de várias vítimas |
| **C6 Repasse rápido** | O destino repassa 50% ou mais do que recebe em até 1 h | +25 | Na pesquisa, cerca de 53% do dinheiro de mula sai em 1 h |
| **C7 Reputação endógena** | Proporção de `rejected` + `two_factor_required` nas análises do destino (mín. 4) | ≥ 30% +15; ≥ 50% +30 | "Consórcio de um participante só": cada análise ensina a próxima |
| **C8 Teste e drenagem** | Pix de até R$ 10 a destino novo e, em até 72 h, Pix alto ao mesmo destino | alto = maior entre R$ 500 e 20× o teste; +30 e piso de 2FA | Pix de centavos valida a conta antes da drenagem |
| **P1 Valor fora do padrão** | Valor acima do maior entre o P95 de 90 dias e R$ 500 | acima +20; acima de 3× +30; com menos de 10 observações, acima de R$ 500: +10 | O percentil resiste a outlier; média e desvio-padrão não (ver abaixo) |
| **P2 Horário fora do padrão** | Hora (±1 h, circular) usada em menos de 5% das transações (mín. 10) | +10 | Cada cliente tem seu ritmo; complementa o corte fixo do BC |
| **M1 Acumulado** | Soma de 24 h acima de 3× o limiar da P1 | +20 | Pega a drenagem em várias parcelas |
| **M2 Fracionamento** | 3 ou mais Pix entre 80% e 100% de R$ 200 ou de R$ 1.000 em 24 h | +30 | Quebrar o valor para ficar abaixo do teto é fácil de contornar |
| **V1 Rajada** | Pix do pagador em 10 min (contando o atual) | ≥ 3 +25; ≥ 5 +40 | O 60+ raramente faz 3 Pix seguidos; automação ou controle remoto, sim |
| **V2 Destinos novos** | Destinos novos em 1 h | ≥ 3 +30 | Vítima conduzida a vários destinos |
| **O1 Origem recém-aberta** | Conta de origem com menos de 30 dias | +10 | Conta aberta para a fraude |
| **R1 Acesso remoto / ligação** | `remote_access_detected` ou `call_in_progress` verdadeiros | +30 cada; piso de 2FA | "Mão fantasma" e falso atendente |
| **R2 Automação no desktop** | Canal `internet` ou `computador` com sinal de robô em `source.interaction`: `is_robotic_movement`, cadência de digitação com desvio ≤ 15 ms ou `session_idle_then_burst` | +40 e piso de 2FA; com C1 ou V1, escala para `rejected` | Bots e acesso remoto drenam a sessão aberta. A telemetria inteira vai para a `evidence` |
| **F1 Valor frente à renda** (hipótese) | Valor acima da renda mensal (créditos `DEPOSIT` em 30 dias + Open Finance) | > 1× +15; > 2× +25 | Pix muito grande para uma renda estável é desvio |
| **F2 Saldo esvaziado** (hipótese) | Pix que consome 80% ou mais do saldo (conta + Open Finance) | +15 | Golpes de engenharia social esvaziam a reserva |
| **F3 Conta de passagem** (hipótese) | Depósito há menos de 30 min e Pix ≥ 90% dele para destino novo | +30 e piso de 2FA; +15 se o Open Finance mostra queda parecida em outro banco | O golpista faz o idoso trazer a economia de outro banco e a pulveriza |
| **H2 Beneficiário de confiança** | 3 ou mais Pix concluídos ao destino em 3 meses-calendário diferentes, valor dentro de ±20% da mediana do par | −25 (score nunca abaixo de 0); não vale para destino marcado ou em quarentena, nem com C8 | Reduz atrito de quem paga o aluguel todo mês. Exigir meses distintos dificulta o golpista construir confiança rápido |

### Racional das escolhas

- **Por que P95 e não média ± desvio-padrão.** Um valor atípico puxa as duas medidas, e no 60+ ele é comum (reforma, remédio, funeral). Com 17 Pix de R$ 200 e um de R$ 8.000, a média + 3 desvios chega a cerca de R$ 5.994, e uma fraude de R$ 5.900 passaria. O P95 fica em cerca de R$ 1.370, como comprova um teste unitário. Com poucos pontos o P95 também oscila, por isso o mínimo de 10 observações e o piso de R$ 500.
- **Teto por família.** Regras da mesma família tendem a contar o mesmo fato duas vezes, então a soma de cada uma é limitada antes de entrar no score. Os tetos são: aparelho (D1, D2, D3) 45, geografia (G1, G2, G4) 40, destino (C1, C2, C5–C8) 55, comportamento (K1, P1, P2, M1, M2, V1, V2) 60. Pontos negativos, R1, R2, O1 e F ficam fora do teto. Quando um teto age, a `metadata` traz `family_caps_applied`.
- **Reputação do destino.** Nenhum destino é rejeitado só por ser novo, porque o neto que abriu conta ontem é legítimo. Só a convergência com C5, C6 ou C7 leva à quarentena.

![Estados da reputação do destino](docs/diagramas/04-reputacao-do-destino.svg)

<details>
<summary>Código Mermaid deste diagrama</summary>

```mermaid
stateDiagram-v2
    [*] --> NORMAL
    NORMAL --> OBSERVACAO: conta com menos de 7 dias, PJ com menos de 30 ou Pix exorbitante
    OBSERVACAO --> NORMAL: 7 dias sem gatilho
    OBSERVACAO --> QUARENTENA: C5 com 5 ou mais pagadores, C6 ou C7 de 50% ou mais
    QUARENTENA --> OBSERVACAO: expira em 72 h
    [*] --> MARCADA: carga do BC ou feedback
    MARCADA --> NORMAL: expira em 5 anos
    note right of OBSERVACAO
        Só pontua (C2, C5)
    end note
    note right of QUARENTENA
        E3 rejeita pagador sem H2
    end note
    note right of MARCADA
        E2 rejeita, exceto devolução
    end note
```

</details>

## Como as regras viram decisão

**Ordem:** (1) validação e idempotência → (2) eliminatórias E1 a E6 → (3) soma dos pontos com teto por família → (4) faixa de valor → (5) pisos → (6) gravação.

A decisão fica numa função única (`domain.engine.decide`):

1. alguma eliminatória dispara → `rejected`;
2. score ≥ corte de reprovar da faixa → `rejected`;
3. score ≥ corte de 2FA **ou** algum piso ativo → `two_factor_required`;
4. senão → `approved`.

| Faixa | Valor (limites inclusivos) | 2FA a partir de | Reprova a partir de |
| --- | --- | --- | --- |
| A | até R$ 200 | 45 | 85 |
| B | R$ 200,01 a R$ 1.000 | 35 | 75 |
| C | R$ 1.000,01 a R$ 5.000 | 30 | 65 |
| D | acima de R$ 5.000 | 25 | 55 |

A fronteira desce quando o valor sobe: o custo da fraude cresce com o valor, e o da fricção é quase constante. Os cortes de R$ 200 e R$ 1.000 seguem limites do BC. O de R$ 5.000 e os pontos são hipóteses.

**Quando pede 2FA mesmo com pouca pontuação (pisos):**
- E5, K2, C8, R1, R2, F3 e G2;
- **X1 Convergência:** 3 ou mais sinais fracos, entre 10 e 19 pontos cada (sinais de 5 pontos não contam);
- **X2 Valor alto a destino novo:** faixa D com C1.

**Exemplos** (cobertos por testes unitários):
- Pix de R$ 1.500 às 22:15 para destino sem pré-cadastro: a E4 dispara e o Pix é `rejected`, com `rules_fired: [E4]`.
- O mesmo Pix às 14:00, cliente em padrão, para conta aberta há 5 dias: C1 (+15) e C2 (+30) somam 45, acima do corte de 30 da faixa C. Resultado: `two_factor_required`.
- O aluguel de R$ 1.200 pago ao mesmo destino pela 4ª vez: C1 não dispara, a H2 tira 25 e o score fica em 0. Resultado: `approved`.
- Ligação em andamento num Pix pequeno para destino conhecido: score baixo, mas o piso da R1 leva a `two_factor_required`.

**Tipo de desafio e fricção** (na `metadata` quando há 2FA):
- `challenge_type` diz **para quem vai o token** da QI Tech: `CUSTOMER_TOKEN_2FA` (padrão, o próprio cliente) ou `TRUSTED_CONTACT_APPROVAL` (o Contato de Confiança). O segundo vale quando R1 (ligação), C1 e F2 convergem e o Contato deu aceite (`approval_consent_at`).
- `friction_script_key` diz ao app qual pergunta fazer antes do 2FA, pela ordem R1, F3, C6, C5: `CALL_COACHING_CHECK`, `PASSTHROUGH_CHECK`, `MULE_DESTINATION_CHECK`; nos demais casos, `CONFIRM_IDENTITY`.
- O motor devolve só a chave e uma faixa qualitativa, nunca o limiar ou o número.

**Segundo fator pela QI Tech (2FA v2).** O motor só decide; quem fala com a QI é o `PixSecondFactorController`, no papel da `transaction-api`:

1. `POST /pix/transaction/{id}/second_factor` cria a transferência na QI (`POST /account/{account_key}/pix_transfer`) com `tfa_info` (CPF do aprovador e `sms` ou `email`). A QI responde `pending_2fa_approval` e envia o token. O motor grava `qi_pix_transfer_key`, `qi_account_key`, o status da QI e o prazo de 5 minutos na análise.
2. O aprovador precisa combinar com o desafio. Em `CUSTOMER_TOKEN_2FA` tem de ser o próprio pagador; em `TRUSTED_CONTACT_APPROVAL`, nunca o pagador. Na QI, ele também precisa estar cadastrado como aprovador da conta.
3. `PUT .../second_factor/token` primeiro aplica a resposta de fricção. "Sim, há alguém no telefone" escala o desafio sem chamar a QI: vira `TRUSTED_CONTACT_APPROVAL` se há Contato consentido, ou `rejected` se não há.
4. Se não houve escalada, o token é validado na QI (`validate_token`):
   - `sent` ou `pending` aprovam o Pix e gravam `second_factor_at`;
   - token errado ou expirado mantém o Pix retido;
   - a 5ª tentativa errada faz a QI rejeitar a transferência, e o Pix vira `rejected` (regra `QI2FA` na auditoria).
5. `PATCH .../second_factor/token` pede um novo token (`resend_token`). O prazo de 5 minutos reinicia, mas a contagem de tentativas, não.

A escalada nunca relaxa: um `rejected` não vira `approved`. Para quem integra o motor por fora, o reenvio do mesmo `id` com `second_factor_passed: true` continua valendo. Esse campo e o `friction_answer` não entram no `request_hash`.

**Aviso ao Contato de Confiança.** Com `rejected` ou `two_factor_required` e Contato cadastrado, o motor grava o aviso na `notification_outbox` com `transaction_id = NULL` e `analysis_id` preenchido, na mesma transação da análise. O `outbox-worker` do banco faz a entrega.

## Como rodar e testar

Sobe o banco e a API:

```bash
docker compose up -d --build
```

Roda os 102 testes: 69 unitários (motor e conector da QI Tech contra um mock), 19 da API Pix (8 do 2FA com o mock da QI) e 14 da API bancária:

```bash
pytest
```

Gera a massa sintética (600 Pix pela API) e o relatório do backtest, em [docs/backtest-massa-sintetica.md](docs/backtest-massa-sintetica.md):

```bash
python scripts/massa_sintetica.py
```

```bash
python scripts/backtest.py
```

## Resultado do backtest

A massa tem 480 Pix legítimos de clientes 60+:
- aluguel recorrente, contas e família;
- uso de `tablet`, alias `app`, relógio e uso ocasional do computador.

E 120 golpes ou bloqueios:
- falsa central, mão fantasma, sequestro-relâmpago e mula;
- teste e drenagem, fracionamento e destino marcado;
- robô no desktop, bot no `internet` e bets.

| Métrica (RFC) | Meta | Resultado |
| --- | --- | --- |
| Pix em `two_factor_required` (todos) | entre 2% e 5% | **17,0% — fora da meta** |
| Legítimos reprovados | o menor possível | **0 de 480** |
| Legítimos com 2FA | o menor possível | 18,8% |
| `rejected` por eliminatória | só regras previstas | E2, E3, E4, E5 e E6, todas em golpes ou bets |
| Valor fraudulento contido | — | **97,3%** (R$ 132,8 mil de R$ 136,5 mil) |

| Tipologia | Interceptados | Principal regra |
| --- | --- | --- |
| Falsa central, sequestro-relâmpago, mão fantasma, mula, destino marcado, bets | 100% | R1, E4, E5, E3, E2, E6 |
| Robô no desktop (aparelho conhecido) e bot no `internet` | 100% | R2 com escalada (20 de 20), sem falso positivo nos 10 legítimos no desktop |
| Teste e drenagem | 50% dos Pix, 99,9% do valor | C8 pega a drenagem; o Pix de teste passa, por desenho |
| Fracionamento | 33% | M2 só dispara no terceiro Pix, por desenho |

**O que ainda precisa de calibração** (hipóteses a validar antes de produção):

- **P1 com histórico curto.** O idoso faz poucos Pix. Com menos de 10 observações, todo aluguel acima de R$ 500 ganha +10, e isso gera a maior parte do 2FA em legítimos.
- **C7 se retroalimenta.** Um 2FA que o cliente passou conta como "suspeito" para o destino. Locadores que recebem de vários inquilinos acabam pontuando.
- **Partida a frio.** No começo do histórico, D3 e C1 pesam em todo primeiro Pix para cada destino.
- **R2.** A massa não tem quem cola a chave Pix (cadência de digitação perto de zero sem ser robô). Esse é o principal risco de falso positivo no desktop.
- **K1.** Disparou só em legítimos. As vítimas fazem poucos Pix e não atingem o mínimo de 5 transações.
- **Limites da massa.** A massa sintética mede a coerência interna das regras, não a taxa real de fraude. As tipologias têm 5 a 30 casos, então um Pix muda o percentual em vários pontos.

## Códigos de erro

Todo erro tem `code`, `title`, `description`, `translation`, `request_id` e `errors` (`field`, `rule`, `message`), e nunca expõe a stack nem o documento completo.

| Código | Status | Quando |
| --- | --- | --- |
| `AFP000001` | 400 | Corpo, cabeçalho ou parâmetro fora do formato |
| `AFP000002` | 403 | `INTERNAL-TOKEN` ausente ou errado |
| `AFP000003` | 404 | Análise inexistente (`GET` ou feedback) |
| `AFP000004` | 409 | Mesmo `id` com corpo diferente |
| `AFP000005` | 422 | CPF ou CNPJ com dígitos verificadores inválidos |
| `AFP000006` | 400 | `transaction_date` sem fuso, inválida ou mais de 5 min no futuro |
| `AFP000007` | 422 | `channel` fora do enum |
| `AFP000008` | 400 | `amount` menor que 1 ou não inteiro |
| `AFP000009` | 503 | Espera pela trava do pagador passou do máximo; repita com o mesmo `id` |
| `AFP000010` | 409 | O Pix não está aguardando segundo fator (ou o desafio não foi aberto) |
| `AFP000011` | 422 | Token incorreto (QI `PXT000173`) |
| `AFP000012` | 422 | Token expirado; peça um novo (QI `PXT000172`) |
| `AFP000013` | 422 | 5 tentativas erradas: a QI rejeitou e o Pix virou `rejected` (QI `PXT000171`) |
| `AFP000014` | 503 | QI Tech indisponível ou falha no envio do token; repita |
| `AFP000015` | 422 | Transferência recusada pela QI Tech (o código da QI vai em `errors`) |
| `AFP000016` | 422 | Aprovador incompatível com o desafio ou sem permissão na QI (`PXT000168`) |

## Modelo de dados

O motor não tem banco próprio: usa o PostgreSQL do Banco 60+. Ele **só lê** as tabelas do banco (`customer`, `account`, `blocked_mcc`, `merchant`, `trusted_contact`, `bank_transaction`, `ledger_entry`) e **escreve** no schema `fraude` e, para avisos, na `notification_outbox`. Nunca mexe em saldo nem em extrato.

| Tabela (`fraude.`) | Conteúdo |
| --- | --- |
| `pix_analysis` | Uma linha por Pix: `pix_id` único, `request_hash`, status, score, faixa, versão do motor, documentos em hash e máscara, canal, aparelho, geolocalização, `metadata`, campos da fricção e do desafio na QI Tech (`qi_account_key`, `qi_pix_transfer_key`, `qi_end_to_end_id`, status da QI e prazo do token) |
| `pix_rule_result` | Regra, pontos e `evidence` (JSON) de cada regra disparada, para auditoria e backtest |
| `device_seen` | Aparelho × pagador com primeira e última vez visto (D1, D2, E5) |
| `destination_flag` | `OBSERVACAO`, `QUARENTENA` e `MARCADA`, com validade |
| `destination_reputation` | Contadores por destino (análises, reprovações, 2FA, pagadores em 24 h, repasse em 1 h), atualizados com `n = n + 1` |
| `bet_destination` | CNPJs de bets (E6) |
| `of_payer_profile` | Agregados do Open Finance (renda, saldo, consentimento), carregados fora da decisão |
| `engine_config` | Parâmetros versionados com `active_from` |
| `pix_feedback` | Rótulos de fraude (evolução) |
| `pix_shadow_result` | Score do modo sombra, que não altera a resposta (evolução) |

**Alterações no Banco 60+:**
- `notification_outbox` aceita `transaction_id` nulo e ganha `analysis_id`, com `CHECK` de que exatamente um dos dois está preenchido. Também ganha `UNIQUE (analysis_id, contact_id)` e um índice parcial `WHERE transaction_id IS NULL`, que é o filtro dos Pix barrados ou retidos.
- `trusted_contact` ganha `approval_consent_at`.
- `bank_transaction` ganha índices para o histórico do par pagador–destino.

## Premissas e fora do escopo

**Premissas:**
- **RFC Banco 60+.** É a especificação de produto do desafio. O motor é parametrizado para recalibrar sem refatorar quando houver dados de produção.
- **Res. BCB 587.** Ligada por padrão (`ENABLE_BCB_587_RULES`). Desligada, a E2 não rejeita.
- **MED 2.0.** Adotamos a obrigatoriedade em 02/02/2026, para ancorar a rastreabilidade (`id`, `destination_key` e evidência gravados).
- **MEI.** Reconhecido por heurística no nome, sem consulta à Receita. Pode errar nos dois sentidos.
- **Renda.** Assumimos que o benefício chega como crédito `DEPOSIT` no ledger.

**Fora do escopo:**
- tela do 2FA no app; autenticação e assinatura das chamadas à QI Tech (usamos o cabeçalho `API-CLIENT-KEY`, configurável) e o webhook de conclusão assíncrona (`pending`);
- conexão com o Open Finance;
- entrega real do aviso (`outbox-worker`);
- liquidação externa, MED e estorno;
- modelo supervisionado (entra em modo sombra);
- regra de "nome parecido", porque o payload não traz o nome do recebedor;
- geolocalização de compras e IP, porque não passam pelo motor.

**Melhorias conhecidas:**
- Trocar o hash SHA-256 simples do CPF por HMAC com chave secreta. O espaço de CPFs é pequeno e o hash simples pode ser revertido por força bruta.
- Calibrar P1 e C7, conforme o backtest acima.
