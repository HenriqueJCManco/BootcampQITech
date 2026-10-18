# Política de Resiliência, SLA e Salvaguardas Contratuais do Antifraude

Este documento estabelece os padrões operacionais, contratos de tempo (SLA), comportamento sob indisponibilidade/ataques e salvaguardas jurídicas do **Motor Pix Seguro 60+**.

---

## 1. Métricas de Tempo e SLA da API

Para garantir que o fluxo de transferência do Banco 60+ (passo 4b) não sofra lentidão perceptível para o cliente, a API opera sob o teto estrito de **300 ms**.

### Decomposição dos Tempos de Execução (Medição em Produção)

| Etapa | Componente | Tempo Típico | Limite Máximo (SLA) | Estratégia de Mitigação |
| :--- | :--- | :--- | :--- | :--- |
| **Validação Rápida** | `_validate` e `_normalize` | **< 1 ms** | 5 ms | Interrupção imediata (400/422) sem abrir transação no banco |
| **Leitura Consolidada** | `load_payer_snapshot` e `load_destination_snapshot` | **5 a 15 ms** | 50 ms | Tabelas pré-calculadas (`destination_reputation`, `device_seen`) com índices primários $O(1)$ |
| **Verificação de Regras** | `evaluate(context, config)` | **0.05 a 0.20 ms** | 5 ms | 100% em memória, sem I/O ou consultas externas |
| **Persistência e Commit** | `persist_analysis` e `commit` | **10 a 25 ms** | 100 ms | Transação isolada, escrita de outbox e `INSERT ... ON CONFLICT DO UPDATE` |
| **Tempo Total de Consumo** | Endpoint `POST /pix/transaction` | **20 a 45 ms** | **300 ms** | Aborta com `503` se a espera pela trava passar de 2s |

Cada análise grava no campo `metadata.telemetry` o detalhamento exato em microssegundos:
```json
{
  "telemetry": {
    "total_elapsed_ms": 32.4,
    "validation_ms": 0.8,
    "db_fetch_ms": 11.2,
    "rule_evaluation_ms": 0.15,
    "db_persist_ms": 20.25
  }
}
```

---

## 2. Mitigação de Falhas e Ataques a Requisitos Externos

### A. Travamento de Dependências Externas (QI Tech e Open Finance)
* **Princípio da Não-Dependência Síncrona:** O motor antifraude **nunca faz chamadas externas síncronas** dentro da rota de autorização do Pix.
  - A QI Tech (2FA e Biometria) é acionada pela `transaction-api` **fora do motor e fora da trava**.
  - O Open Finance é alimentado previamente por jobs em background (`of_payer_profile`). Se o serviço cair, as regras `F` são desligadas automaticamente (`inputs_missing`), sem impactar o Pix.
* **Conectores com Timeout Rígido:** Qualquer chamada a parceiros via `QITechConnector` ou `OpenFinanceConnector` possui timeout máximo de **300 ms**:
  - `httpx.Timeout(0.3)` estrito.

### B. Política de Indisponibilidade (Fail-Closed vs Fail-Open)
Configurada dinamicamente no `engine_config.antifraude`:
1. **Padrão de Segurança (Fail-Closed):**
   - Se o motor antifraude falhar ou o banco de dados atingir timeout: responde **`503 AFP000009`** / `503 BNK004010`.
   - O dinheiro **não sai**. A idempotência (`Idempotency-Key`) assegura que o app repita o pedido com segurança.
2. **Exceção para Valores Triviais (Fail-Open Faixa A):**
   - Através do parâmetro `abrir_ate_centavos: 20000` (R$ 200,00), a diretoria de produto pode autorizar que transações de valor irrelevante passem caso o motor esteja degradado, mantendo a experiência do aposentado em pequenos pagamentos.

### C. Ataques de Negação de Serviço por Travas Concorrentes (DoS)
* Golpistas poderiam disparar centenas de requisições paralelas para travar a conta do idoso.
* **Salvaguarda:** A trava de aconselhamento (`pg_advisory_xact_lock`) possui limite máximo de espera:
  ```sql
  SET LOCAL lock_timeout = '2s';
  ```
* Se a fila de concorrência exceder 2 segundos, o PostgreSQL lança o erro `55P03`, que a API converte em `503 PixLockTimeout`, liberando conexões do pool imediatamente.

---

## 3. Cláusulas e Salvaguardas Contratuais para se Resguardar

Para resguardar juridicamente o Banco 60+ frente a clientes, parceiros tecnológicos e órgãos reguladores (BACEN / LGPD):

### 1. Termo de Responsabilidade do 2FA Social (`approval_consent_at`)
* **Cláusula de Autorização do Titular:** O titular declara ciência de que, sob fortes indícios de coação ou falso atendente telefônico, a operação será submetida ao crivo de seu Contato de Confiança cadastrado.
* **Cláusula de Aceite do Contato de Confiança:** O familiar cadastrado assina eletronicamente termo de responsabilidade no app. Se o termo não estiver assinado (`approval_consent_at IS NULL`), o motor **recusa o envolvimento do terceiro** e barra preventivamente o Pix (`BLOCKED_FOR_SAFETY`), eximindo a instituição de responsabilidade por autorizações indevidas.

### 2. SLA Contratual com Provedores Terceirizados (ex.: QI Tech)
* **Cláusula de Desempenho e Latência:** O provedor deve garantir latência média $\le 150\text{ ms}$ (p99 $\le 300\text{ ms}$) e disponibilidade de $99.9\%$.
* **Cláusula de Não-Responsabilização por Indisponibilidade de Terceiro:** Em caso de queda da infraestrutura biométrica da contratada, o banco resguarda o direito de acionar contingência ou recusar a operação sem incorrer em perdas e danos.

### 3. Sigilo de Regras e Proibição de Exposição (Anti-Probing)
* O contrato de termos de uso do aplicativo estipula que recusas de transação por motivos de segurança não vinculam a instituição à revelação dos parâmetros exatos de scoring, prevenindo que fraudadores utilizem engenharia reversa judicial ou técnica para mapear as defesas do banco.
