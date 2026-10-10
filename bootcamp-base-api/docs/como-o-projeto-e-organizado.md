# Como a transaction-api é organizada

Este projeto separa HTTP, regras de negócio e acesso ao banco para que
cada arquivo tenha um motivo claro para mudar.

## 1. Mapa do projeto

```text
src/
  app.py                     registra rotas e middlewares
  resources/                 adaptadores HTTP
  schemas/                   contratos JSON de entrada
  controllers/               regras de negócio e commit
  repositories/              consultas SQLAlchemy
  models/                    mapeamento das tabelas
  dtos/                      formato de saída da API
  errors/                    códigos e respostas de erro
  middlewares/               token, sessão, log e request_id
  utils/                     validação e funções compartilhadas
database/
  database.sql               schema e índices do PostgreSQL
tests/integration/banking/   cenários observados pela API
```

O sentido das dependências é:

```text
resource → controller → repository → model → PostgreSQL
```

O model não conhece a rota. O repository não decide regra de negócio.
O controller não monta resposta HTTP. O resource não escreve SQL.

## 2. O caminho de uma requisição

Uma chamada `POST /account/{key}/deposit` percorre estas etapas:

1. `request_context` cria ou valida o `X-Request-ID`.
2. `request_logger` registra entrada e saída.
3. `internal_token` recusa chamadas sem `INTERNAL-TOKEN`.
4. `session_manager` prepara o contexto da sessão; fecha a sessão ao
   final e desfaz qualquer transação não confirmada.
5. O resource valida o JSON contra `src/schemas/post_deposit.json` e
   confere o `Idempotency-Key`.
6. `TransactionController` valida o valor e verifica se a conta existe.
7. `BankRepository` reserva a chave única, bloqueia a linha da conta e
   lê o saldo já protegido contra uma atualização concorrente.
8. O controller atualiza saldo, grava lançamento no ledger, registra
   contatos na outbox e confirma tudo com um único `commit`.
9. O resource transforma o resultado em JSON e escolhe `201` (operação
   nova) ou `200` (repetição idempotente).

Se uma regra recusar a operação, a exceção vira uma resposta BNK e a
sessão desfaz a reserva da chave, sem saldo, ledger ou aviso parcial.

## 3. Por que a transferência tem uma ordem fixa

Uma transferência movimenta duas contas. Se uma chamada A→B bloquear
primeiro A e outra B→A bloquear primeiro B, cada uma pode ficar esperando
pela linha que a outra segura. Para evitar esse deadlock, o repository
sempre executa o bloqueio em ordem crescente do ID:

```sql
SELECT ...
FROM account
WHERE id IN (...)
ORDER BY id
FOR UPDATE
```

Depois que as linhas estão bloqueadas, o controller confere se o saldo
cobre `amount_cents + 100`. Se não cobrir, não grava nada. Se cobrir,
grava três linhas distintas: débito da transferência, débito da tarifa e
crédito da conta de destino. Saldo, lançamentos e avisos da outbox ficam
na mesma transação.

O `CHECK (balance_cents >= 0)` é a última barreira no próprio PostgreSQL,
caso uma regra de aplicação tenha algum defeito.

## 4. Idempotência em dois pedidos iguais

Antes de mover dinheiro, o repository insere `Idempotency-Key` em
`bank_transaction`. A coluna tem `UNIQUE`; o `INSERT ... ON CONFLICT DO
NOTHING` faz duas requisições concorrentes com a mesma chave aguardarem
o resultado da primeira.

- Chave nova: reserva e segue para o movimento.
- Mesma chave e mesmo hash de rota/corpo: devolve o resultado original
  com `200`, sem novo lançamento.
- Mesma chave com outro hash: responde `409 BNK000012`.
- Erro antes do commit: rollback remove a reserva; uma nova tentativa
  pode ser avaliada novamente.

O hash não armazena o corpo; é calculado sobre JSON canônico e a rota.
Não se usa o saldo atual para uma resposta repetida: ela é reconstruída
a partir do `balance_after_cents` do ledger original.

## 5. Onde alterar cada comportamento

| Alteração | Arquivo/camada |
|---|---|
| Adicionar ou alterar campo de entrada | `src/schemas/` |
| Adicionar rota ou definir status HTTP | `src/resources/` e `src/app.py` |
| Alterar regra de limite, saldo ou Cofre | `src/controllers/` |
| Alterar uma consulta ou gravação | `src/repositories/bank_repository.py` |
| Alterar tabela, constraint ou índice | `database/database.sql` e `src/models/banking.py` |
| Alterar JSON de resposta | `src/dtos/bank_dto.py` |
| Adicionar regra de erro | `src/errors/` e teste da resposta |
| Adicionar uma operação financeira | seguir o fluxo de idempotência, trava, ledger, outbox e commit |

O banco de desenvolvimento executa `database/database.sql` apenas quando
o volume é criado. Para reconstruir o schema local após uma mudança,
`docker compose down -v` seguido de `docker compose up --build -d`
recria o banco, mas apaga todos os dados daquele volume. Em sistemas
reais, alterações de schema devem ser aplicadas com migrações, não com
remoção do banco.

## 6. Limites deliberados

- O gateway externo é responsável por rate limiting e prazo global da
  requisição; a API exige o token interno e faz a validação final.
- A outbox registra notificações `PENDING`; não existe integração de
  envio de SMS/e-mail nesta etapa.
- O catálogo de estabelecimentos é uma carga inicial, sem endpoint de
  cadastro. O arquivo enviado com a RFC não contém registros para essa
  carga.
- Liquidação externa, estorno, encerramento de conta e alteração do
  limite não fazem parte do escopo.
