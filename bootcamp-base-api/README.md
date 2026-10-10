# transaction-api

API bancária de estudo baseada na RFC do projeto. O serviço usa FastAPI,
PostgreSQL e Docker Compose; valores monetários são sempre inteiros em
centavos.

## 1. Pré-requisitos

- Docker Desktop com `docker compose`
- Python 3.11 para executar os testes localmente, a mesma versão da imagem da API

No PowerShell, confira as instalações:

```powershell
docker compose version
python --version
```

## 2. Subir a API e o banco

```powershell
docker compose up --build -d
```

O Compose cria o banco PostgreSQL e inicializa as oito tabelas definidas
em [database/database.sql](./database/database.sql). A API fica em
`http://localhost:3000`; a rota `/health_check` retorna `204` quando
está pronta.

As configurações locais podem ser alteradas copiando
`.env.example` para `.env`. O token `default_token` é apenas para
desenvolvimento. Em produção, use um segredo próprio e coloque a API
atrás do gateway interno descrito na RFC.

## 3. Contrato HTTP

As rotas `/` e `/health_check` são públicas. Todas as demais exigem:

```text
INTERNAL-TOKEN: default_token
```

| Método e rota | Uso |
|---|---|
| `POST /customer` | Cadastra cliente PF ou PJ |
| `GET /customer/{customer_key}` | Consulta cliente |
| `POST /account` | Abre conta; inicia saldo em zero e bloqueia MCC `7995` |
| `GET /account/{account_key}` | Consulta saldo, limite e MCCs bloqueados |
| `PUT /account/{account_key}/blocked_mcc` | Substitui a lista de MCCs bloqueados |
| `POST /account/{account_key}/trusted_contact` | Cadastra contato de confiança (máximo 2) |
| `POST /account/{account_key}/deposit` | Deposita centavos; requer `Idempotency-Key` |
| `POST /account/{account_key}/purchase` | Compra; requer `Idempotency-Key` |
| `POST /transfer` | Transfere e cobra tarifa fixa de 100 centavos; requer `Idempotency-Key` |
| `GET /account/{account_key}/statement` | Extrato paginado (`limit` de 1 a 100; `page` começa em 0) |

Exemplo no PowerShell:

```powershell
$headers = @{ "INTERNAL-TOKEN" = "default_token" }
$customer = Invoke-RestMethod -Method Post `
  -Uri http://localhost:3000/customer `
  -Headers $headers -ContentType "application/json" `
  -Body '{"name":"Maria da Silva","email":"maria@example.test","document_number":"529.982.247-25"}'

$account = Invoke-RestMethod -Method Post `
  -Uri http://localhost:3000/account `
  -Headers $headers -ContentType "application/json" `
  -Body (@{ customer_key = $customer.customer_key } | ConvertTo-Json)

$depositHeaders = $headers.Clone()
$depositHeaders["Idempotency-Key"] = "deposito-exemplo-001"
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:3000/account/$($account.account_key)/deposit" `
  -Headers $depositHeaders -ContentType "application/json" `
  -Body '{"amount_cents":50000}'
```

Um primeiro movimento responde `201`; a repetição da mesma operação com
a mesma chave e o mesmo conteúdo responde `200` com o resultado
original. Reutilizar a chave com outro conteúdo responde `409`.

## 4. Organização do código

O fluxo segue `resource → controller → repository → model`:

- `src/resources/`: rotas HTTP, validação do schema e status de resposta.
- `src/controllers/`: regras de negócio e ponto explícito de `commit`.
- `src/repositories/`: consultas e gravações SQLAlchemy.
- `src/models/`: representação das oito tabelas.
- `src/schemas/`: contratos JSON de entrada, rejeitando campos extras.
- `src/dtos/`: conversão dos modelos para respostas HTTP.
- `src/errors/`: códigos BNK e formato único de erro, com `request_id`.
- `database/database.sql`: schema, constraints e índices do PostgreSQL.

O fluxo de concorrência, idempotência e a responsabilidade de cada
camada estão detalhados em
[docs/como-o-projeto-e-organizado.md](./docs/como-o-projeto-e-organizado.md).

## 5. Garantias financeiras implementadas

- Dinheiro em centavos (`BIGINT`), sem `float`.
- Cada movimento atualiza saldo, ledger e outbox na mesma transação.
- `CHECK (balance_cents >= 0)` protege o saldo no banco.
- Operações financeiras bloqueiam as linhas das contas com
  `SELECT ... FOR UPDATE`, sempre na ordem crescente de ID.
- `Idempotency-Key` tem índice único e o hash cobre rota e corpo.
- Transferências registram débito, crédito e tarifa como lançamentos
  distintos; cada lançamento guarda o saldo após aquele lançamento.
- Extrato é ordenado por data e ID, pede uma linha extra para detectar
  próxima página e lê saldo/extrato em transação somente leitura
  `REPEATABLE READ`.
- Avisos são gravados como `PENDING` na `notification_outbox` junto com
  o movimento; envio por SMS/e-mail não está incluído.

O catálogo `merchant` é criado vazio porque a RFC não fornece a carga
inicial. A proteção compara o MCC informado com MCCs bloqueados e, quando
há um estabelecimento cadastrado, também compara o MCC confiável do
catálogo. Antes de usar compras em produção, carregue o catálogo oficial.
Não há rota para cadastrar estabelecimentos.

Rate limiting, prazo global das requisições e repasse do
`Idempotency-Key` pertencem ao gateway externo da RFC; esta aplicação
valida o token interno e garante idempotência no PostgreSQL.

## 6. Executar os testes

Com os containers no ar, em outro terminal:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
pytest
```

Os testes de integração usam o banco do Compose e recriam o schema antes
de cada cenário. Para apagar os dados persistidos intencionalmente:

```powershell
docker compose down -v
```

Esse último comando remove o volume do PostgreSQL e todos os dados locais.
