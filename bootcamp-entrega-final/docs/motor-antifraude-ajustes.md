# Pix Seguro 60+: ajustes do motor (v0.1 → engine_config versão 1)

Complementa o README do motor. Todos os números abaixo são hipóteses lidas de
`fraude.engine_config` e vão para o backtest; nada fica fixo no código.

## Regras novas ou alteradas

| Regra | O que mudou | Parâmetros (`engine_config`) |
| --- | --- | --- |
| **E6 Bets** (eliminatória, nova) | Destino com CNPJ ativo em `fraude.bet_destination` é rejeitado, exceto `type: refund`. A E1 (Cofre por MCC) continua igual. O CNPJ nunca vai para a `evidence`. | `flags.ENABLE_BETS_BAN` (padrão `true`) |
| **G2 Deslocamento impossível** | Dois níveis, ambos com piso de 2FA e +35: ≥ 100 km e ≥ 800 km/h; ≥ 20 km e ≥ 300 km/h. Ignora pontos com precisão pior que 5 km ou com mais de 6 h. Intervalo mínimo de 60 s para não dividir por zero. | `regras.G2.niveis`, `precisao_max_m`, `idade_max_horas`, `intervalo_min_s` |
| **X1 Convergência** | Conta só sinais entre 10 e 19 pontos, para que sinais de 5 não virem 2FA. Olha os pontos brutos, antes do teto por família. | `pisos.X1.pontos_min_sinal_fraco`, `pontos_max_sinal_fraco` |
| **Teto por família** | Soma os pontos positivos por família e limita cada uma ao teto antes de somar. Pontos negativos (H2), R1, R2, O1 e F ficam fora do teto. Quando um teto age, a `metadata` traz `family_caps_applied`. | `familias` (aparelho 45, geografia 40, destino 55, comportamento 60); `flags.ENABLE_FAMILY_CAPS` |

A decisão está numa função única, `domain.engine.decide`: eliminatória → `rejected`;
score ≥ corte de reprovar → `rejected`; score ≥ corte de 2FA ou piso → `two_factor_required`;
senão `approved`. As faixas são inclusivas ("até R$ 200").

## Banco

* `fraude.bet_destination (cnpj CHAR(14) PK, razao_social, source, active, created_at)`, com seed de três CNPJs fictícios (`99000001000101`, `99000002000148`, `99000003000192`).
* `fraude.pix_analysis.geo_accuracy_m` (opcional) guarda a precisão do GPS usada pela G2.
* O payload aceita `source.geolocation.accuracy_m` (metros).

## API

* O `INTERNAL-TOKEN` é comparado em tempo constante (`hmac.compare_digest`).
* O schema `post_pix_transaction.json` não usa `$ref`: o `SchemaHandler` do Base Service não resolve referências internas.

## Fora desta versão (decidido)

* Geolocalização na compra e nível "só IP": a compra não passa pelo motor e o payload não traz IP.
* GET sem token com visão pública: a RFC exige token em todas as rotas, exceto `/health_check`.
* Multiplicador de combinação, D-conhecido negativo e exclusividade de aparelho declarada pelo app: o golpe típico do 60+ usa o aparelho do próprio cliente, e a exclusividade já é inferida por `device_seen` (D2).
