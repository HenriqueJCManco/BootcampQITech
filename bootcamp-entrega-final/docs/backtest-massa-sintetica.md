# Backtest com massa sintética

Gerado em 18/10/2026 04:20 por `scripts/backtest.py`, sobre os rótulos de `fraude.pix_feedback`. A massa mede a coerência interna das regras, não a taxa real de fraude.

## Volume por tabela

| Tabela | Linhas |
| --- | --- |
| `customer` | 600 |
| `account` | 600 |
| `merchant` | 600 |
| `blocked_mcc` | 650 |
| `trusted_contact` | 600 |
| `bank_transaction` | 1130 |
| `ledger_entry` | 2051 |
| `notification_outbox` | 264 |
| `fraude.engine_config` | 1 |
| `fraude.pix_analysis` | 600 |
| `fraude.pix_rule_result` | 1245 |
| `fraude.device_seen` | 810 |
| `fraude.destination_flag` | 608 |
| `fraude.destination_reputation` | 282 |
| `fraude.of_payer_profile` | 600 |
| `fraude.pix_feedback` | 600 |
| `fraude.pix_shadow_result` | 600 |
| `fraude.bet_destination` | 600 |

## Decisões (decisão original do motor)

| | Todos | Legítimos | Golpes | Bets |
| --- | --- | --- | --- | --- |
| `approved` | 420 (70.0%) | 390 (81.2%) | 30 | 0 |
| `two_factor_required` | 102 (17.0%) | 90 (18.8%) | 12 | 0 |
| `rejected` | 78 (13.0%) | 0 (0.0%) | 73 | 5 |
| **Total** | 600 | 480 | 115 | 5 |

## Metas da RFC

| Métrica | Meta | Resultado | Situação |
| --- | --- | --- | --- |
| Pix em `two_factor_required` (todos) | entre 2% e 5% | 17.0% | FORA |
| `rejected` por eliminatória | marcação, cofre, quarentena, limite noturno, aparelho novo (E5) e bets (E6) | {'E5': 10, 'E2': 5, 'E4': 11, 'E6': 5, 'E3': 8} | OK |
| `rejected` por pontuação | raro (adotado: até 1% do total) | 40 (6.7%) | FORA |
| Fricção em legítimos (2FA ou reprovação) | o menor possível | 18.8% | — |

## Golpes por tipologia

| Tipologia | Pix | Interceptados (2FA ou rejected) | Rejeitados | Valor contido | Regras mais frequentes |
| --- | --- | --- | --- | --- | --- |
| bet_regulatoria | 5 | 5 (100.0%) | 5 | R$ 1.035,63 de R$ 1.035,63 (100.0%) | E6 |
| golpe_bot_internet | 10 | 10 (100.0%) | 10 | R$ 3.683,96 de R$ 3.683,96 (100.0%) | C1, R2, P1 |
| golpe_desktop_robotico_conhecido | 10 | 10 (100.0%) | 10 | R$ 6.146,65 de R$ 6.146,65 (100.0%) | C1, R1, R2, P1 |
| golpe_destino_marcado | 5 | 5 (100.0%) | 5 | R$ 2.419,65 de R$ 2.419,65 (100.0%) | E2 |
| golpe_falsa_central | 10 | 10 (100.0%) | 10 | R$ 30.860,10 de R$ 30.860,10 (100.0%) | C1, P1, M1, R1 |
| golpe_fracionamento | 30 | 10 (33.3%) | 0 | R$ 1.863,93 de R$ 5.495,92 (33.9%) | G4, C1, M2, V2 |
| golpe_mao_fantasma | 10 | 10 (100.0%) | 10 | R$ 23.028,16 de R$ 23.028,16 (100.0%) | E5 |
| golpe_mula | 10 | 10 (100.0%) | 8 | R$ 8.912,35 de R$ 8.912,35 (100.0%) | E3, G4, C1, C2 |
| golpe_sequestro_relampago | 10 | 10 (100.0%) | 10 | R$ 23.536,60 de R$ 23.536,60 (100.0%) | E4 |
| golpe_teste_e_drenagem | 20 | 10 (50.0%) | 10 | R$ 32.334,65 de R$ 32.375,23 (99.9%) | G4, C1, C8, P1 |

**Valor fraudulento contido no total:** R$ 132.786,05 de R$ 136.458,62 (97.3%).

## O que gera fricção nos legítimos

| Regra | Vezes em Pix legítimo com 2FA ou rejected |
| --- | --- |
| P1 | 86 |
| C1 | 68 |
| D3 | 61 |
| C7 | 22 |
| G4 | 21 |
| K2 | 5 |
| K1 | 2 |

## Por segmento de canal

| Segmento | Pix | Legítimos | Fricção em legítimos | Golpes | Golpes interceptados | Valor contido |
| --- | --- | --- | --- | --- | --- | --- |
| mobile | 550 | 460 | 83 (18.0%) | 85 | 55 (64.7%) | 96.5% |
| desktop | 40 | 10 | 2 (20.0%) | 30 | 30 (100.0%) | 100.0% |
| relogio | 10 | 10 | 5 (50.0%) | 0 | 0 (—) | — |

## Regras de canal

| Regra | Disparos em legítimos | Disparos em golpes | Observação |
| --- | --- | --- | --- |
| G4 | 131 | 52 |  |
| K1 | 10 | 0 | por segmento: {'desktop': 10} |
| K2 | 5 | 0 | piso de 2FA, sem pontos |
| R1 | 0 | 20 |  |
| R2 | 0 | 20 | 20 escaladas para rejected; avaliada em 20 de 30 golpes desktop (os demais pararam numa eliminatória) |

**Alias `app`:** 66 Pix enviados com `channel: app`, 66 gravados como `celular`.

**Aviso ao Contato de Confiança:** 180 de 180 Pix retidos ou barrados com `notify_trusted_contact` geraram linha na `notification_outbox` (100.0%).

## Fricção por tipo de Pix legítimo

| Tipo | Pix | Com 2FA ou rejected |
| --- | --- | --- |
| legitimo_aluguel | 360 | 83 (23.1%) |
| legitimo_conta | 69 | 0 (0.0%) |
| legitimo_desktop_ocasional | 10 | 2 (20.0%) |
| legitimo_familia | 31 | 0 (0.0%) |
| legitimo_relogio | 10 | 5 (50.0%) |
