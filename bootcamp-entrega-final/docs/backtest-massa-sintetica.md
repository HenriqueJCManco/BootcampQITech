# Backtest com massa sintética

Gerado em 18/10/2026 09:03 por `scripts/backtest.py`, sobre os rótulos de `fraude.pix_feedback`. A massa mede a coerência interna das regras, não a taxa real de fraude.

## Volume por tabela

| Tabela | Linhas |
| --- | --- |
| `customer` | 600 |
| `account` | 600 |
| `merchant` | 600 |
| `blocked_mcc` | 650 |
| `trusted_contact` | 600 |
| `bank_transaction` | 1130 |
| `ledger_entry` | 2042 |
| `notification_outbox` | 271 |
| `fraude.engine_config` | 1 |
| `fraude.pix_analysis` | 600 |
| `fraude.pix_second_factor` | 113 |
| `fraude.pix_rule_result` | 1257 |
| `fraude.device_seen` | 710 |
| `fraude.destination_flag` | 608 |
| `fraude.destination_reputation` | 282 |
| `fraude.of_payer_profile` | 600 |
| `fraude.pix_feedback` | 600 |
| `fraude.pix_shadow_result` | 600 |
| `fraude.bet_destination` | 600 |

## Decisões (decisão original do motor)

| | Todos | Legítimos | Golpes | Bets |
| --- | --- | --- | --- | --- |
| `approved` | 408 (68.0%) | 378 (78.8%) | 30 | 0 |
| `two_factor_required` | 113 (18.8%) | 102 (21.2%) | 11 | 0 |
| `rejected` | 79 (13.2%) | 0 (0.0%) | 74 | 5 |
| **Total** | 600 | 480 | 115 | 5 |

## Metas da RFC

| Métrica | Meta | Resultado | Situação |
| --- | --- | --- | --- |
| Pix em `two_factor_required` (todos) | entre 2% e 5% | 18.8% | FORA |
| `rejected` por eliminatória | marcação, cofre, quarentena, limite noturno, aparelho novo (E5) e bets (E6) | {'E4': 14, 'E5': 10, 'E6': 5, 'E2': 5, 'E3': 8} | OK |
| `rejected` por pontuação | raro (adotado: até 1% do total) | 40 (6.7%) | FORA |
| Fricção em legítimos (2FA ou reprovação) | o menor possível | 21.2% | — |

## Golpes por tipologia

| Tipologia | Pix | Interceptados (2FA ou rejected) | Rejeitados | Valor contido | Regras mais frequentes |
| --- | --- | --- | --- | --- | --- |
| bet_regulatoria | 5 | 5 (100.0%) | 5 | R$ 1.110,22 de R$ 1.110,22 (100.0%) | E6 |
| golpe_bot_internet | 10 | 10 (100.0%) | 10 | R$ 5.082,58 de R$ 5.082,58 (100.0%) | C1, R2, P1 |
| golpe_desktop_robotico_conhecido | 10 | 10 (100.0%) | 10 | R$ 6.083,40 de R$ 6.083,40 (100.0%) | C1, R1, R2, P1 |
| golpe_destino_marcado | 5 | 5 (100.0%) | 5 | R$ 2.937,16 de R$ 2.937,16 (100.0%) | E2 |
| golpe_falsa_central | 10 | 10 (100.0%) | 10 | R$ 31.347,45 de R$ 31.347,45 (100.0%) | C1, P1, M1, R1 |
| golpe_fracionamento | 30 | 10 (33.3%) | 0 | R$ 1.824,16 de R$ 5.420,03 (33.7%) | G4, C1, M2, V2 |
| golpe_mao_fantasma | 10 | 10 (100.0%) | 10 | R$ 21.952,02 de R$ 21.952,02 (100.0%) | E5 |
| golpe_mula | 10 | 10 (100.0%) | 9 | R$ 11.507,78 de R$ 11.507,78 (100.0%) | E3, E4, G4, C1 |
| golpe_sequestro_relampago | 10 | 10 (100.0%) | 10 | R$ 22.717,59 de R$ 22.717,59 (100.0%) | E4 |
| golpe_teste_e_drenagem | 20 | 10 (50.0%) | 10 | R$ 35.911,45 de R$ 35.980,58 (99.8%) | G4, C1, C8, P1 |

**Valor fraudulento contido no total:** R$ 139.363,59 de R$ 143.028,59 (97.4%).

## O que gera fricção nos legítimos

| Regra | Vezes em Pix legítimo com 2FA ou rejected |
| --- | --- |
| P1 | 102 |
| C1 | 72 |
| D3 | 68 |
| C7 | 30 |
| G4 | 28 |
| K1 | 4 |

## Por segmento de canal

| Segmento | Pix | Legítimos | Fricção em legítimos | Golpes | Golpes interceptados | Valor contido |
| --- | --- | --- | --- | --- | --- | --- |
| mobile | 560 | 470 | 98 (20.9%) | 85 | 55 (64.7%) | 96.7% |
| desktop | 40 | 10 | 4 (40.0%) | 30 | 30 (100.0%) | 100.0% |

## Regras de canal

| Regra | Disparos em legítimos | Disparos em golpes | Observação |
| --- | --- | --- | --- |
| G4 | 127 | 51 |  |
| K1 | 10 | 0 | por segmento: {'desktop': 10} |
| R1 | 0 | 20 |  |
| R2 | 0 | 20 | 20 escaladas para rejected; avaliada em 20 de 30 golpes desktop (os demais pararam numa eliminatória) |

**Alias `app`:** 56 Pix enviados com `channel: app`, 56 gravados como `celular`.

**Aviso ao Contato de Confiança:** 192 de 192 Pix retidos ou barrados com `notify_trusted_contact` geraram linha na `notification_outbox` (100.0%).

## Fricção por tipo de Pix legítimo

| Tipo | Pix | Com 2FA ou rejected |
| --- | --- | --- |
| legitimo_aluguel | 360 | 98 (27.2%) |
| legitimo_conta | 78 | 0 (0.0%) |
| legitimo_desktop_ocasional | 10 | 4 (40.0%) |
| legitimo_familia | 32 | 0 (0.0%) |
