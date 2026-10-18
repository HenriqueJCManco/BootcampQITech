"""Backtest do Pix Seguro 60+ contra os rótulos de fraude.pix_feedback.

Mede as metas da seção "Parametrização, calibração e backtest" da RFC sobre
a decisão original do motor (antes de o 2FA ser concluído) e grava o
relatório em docs/backtest-massa-sintetica.md.

Uso:
    python scripts/backtest.py
"""

import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2://bootcamp:bootcamp@localhost:5432/bootcamp")
REPORT = ROOT / "docs" / "backtest-massa-sintetica.md"

TWO_FACTOR_TARGET = (0.02, 0.05)
SCORE_REJECTION_LIMIT = 0.01
ELIMINATORY_EXPECTED = {"E1", "E2", "E3", "E4", "E5", "E6"}
SEGMENTS = {"celular": "mobile", "tablet": "mobile", "computador": "desktop", "internet": "desktop",
            "relogio": "relogio"}
CHANNEL_RULES = ("G4", "K1", "K2", "R1", "R2")

RULE_EVIDENCE_QUERY = text(
    """
    SELECT a.pix_id, r.rule_code, r.evidence
    FROM fraude.pix_rule_result r JOIN fraude.pix_analysis a ON a.id = r.analysis_id
    WHERE r.rule_code IN ('G4', 'K1', 'K2', 'R1', 'R2')
    """
)

QUERY = text(
    """
    SELECT a.pix_id, a.amount_cents, a.score, a.value_band, a.metadata, a.channel,
           EXISTS (SELECT 1 FROM notification_outbox o WHERE o.analysis_id = a.id) AS has_outbox,
           CASE WHEN sf.second_factor_at IS NOT NULL THEN 'two_factor_required' ELSE a.status END AS decision,
           f.is_fraud, f.reason,
           coalesce(array_agg(r.rule_code ORDER BY r.id) FILTER (WHERE r.rule_code IS NOT NULL), '{}') AS rules
    FROM fraude.pix_analysis a
    LEFT JOIN fraude.pix_second_factor sf ON sf.analysis_id = a.id
    JOIN fraude.pix_feedback f ON f.transaction_id = a.pix_id
    LEFT JOIN fraude.pix_rule_result r ON r.analysis_id = a.id
    GROUP BY a.id, sf.second_factor_at, f.is_fraud, f.reason
    """
)


def pct(part: int, total: int) -> str:
    return f"{100 * part / total:.1f}%" if total else "—"


def money(cents: int) -> str:
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main() -> None:
    with create_engine(DATABASE_URL).connect() as connection:
        rows = [dict(row._mapping) for row in connection.execute(QUERY)]
        channel_hits = [dict(row._mapping) for row in connection.execute(RULE_EVIDENCE_QUERY)]
        counts = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in TABLES
        }

    total = len(rows)
    legit = [row for row in rows if not row["is_fraud"] and row["reason"].startswith("legitimo")]
    fraud = [row for row in rows if row["is_fraud"]]
    regulatory = [row for row in rows if row["reason"] == "bet_regulatoria"]

    decisions = Counter(row["decision"] for row in rows)
    two_factor_rate = decisions["two_factor_required"] / total
    legit_decisions = Counter(row["decision"] for row in legit)

    rejected = [row for row in rows if row["decision"] == "rejected"]
    blocked = [row for row in rejected if row["rules"] and all(code.startswith("E") for code in row["rules"])]
    eliminatory_rejections = Counter(code for row in blocked for code in row["rules"])
    score_rejections = [row for row in rejected if row not in blocked]

    by_typology = defaultdict(list)
    for row in fraud + regulatory:
        by_typology[row["reason"]].append(row)

    legit_friction_rules = Counter(
        code for row in legit if row["decision"] != "approved" for code in row["rules"]
    )

    lines = [
        "# Backtest com massa sintética",
        "",
        f"Gerado em {datetime.now():%d/%m/%Y %H:%M} por `scripts/backtest.py`, sobre os rótulos de "
        "`fraude.pix_feedback`. A massa mede a coerência interna das regras, não a taxa real de fraude.",
        "",
        "## Volume por tabela",
        "",
        "| Tabela | Linhas |",
        "| --- | --- |",
        *[f"| `{table}` | {count} |" for table, count in counts.items()],
        "",
        "## Decisões (decisão original do motor)",
        "",
        "| | Todos | Legítimos | Golpes | Bets |",
        "| --- | --- | --- | --- | --- |",
    ]
    for status in ("approved", "two_factor_required", "rejected"):
        lines.append(
            f"| `{status}` | {decisions[status]} ({pct(decisions[status], total)}) "
            f"| {legit_decisions[status]} ({pct(legit_decisions[status], len(legit))}) "
            f"| {sum(1 for row in fraud if row['decision'] == status)} "
            f"| {sum(1 for row in regulatory if row['decision'] == status)} |"
        )
    lines += [f"| **Total** | {total} | {len(legit)} | {len(fraud)} | {len(regulatory)} |", ""]

    unexpected = sorted(set(eliminatory_rejections) - ELIMINATORY_EXPECTED)
    lines += [
        "## Metas da RFC",
        "",
        "| Métrica | Meta | Resultado | Situação |",
        "| --- | --- | --- | --- |",
        f"| Pix em `two_factor_required` (todos) | entre 2% e 5% | {pct(decisions['two_factor_required'], total)} "
        f"| {'OK' if TWO_FACTOR_TARGET[0] <= two_factor_rate <= TWO_FACTOR_TARGET[1] else 'FORA'} |",
        f"| `rejected` por eliminatória | marcação, cofre, quarentena, limite noturno, aparelho novo (E5) e bets (E6) "
        f"| {dict(eliminatory_rejections)} | {'OK' if not unexpected else 'ATENÇÃO: ' + ', '.join(unexpected)} |",
        f"| `rejected` por pontuação | raro (adotado: até 1% do total) | {len(score_rejections)} "
        f"({pct(len(score_rejections), total)}) "
        f"| {'OK' if len(score_rejections) / total <= SCORE_REJECTION_LIMIT else 'FORA'} |",
        f"| Fricção em legítimos (2FA ou reprovação) | o menor possível "
        f"| {pct(len(legit) - legit_decisions['approved'], len(legit))} | — |",
        "",
        "## Golpes por tipologia",
        "",
        "| Tipologia | Pix | Interceptados (2FA ou rejected) | Rejeitados | Valor contido | Regras mais frequentes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for typology, items in sorted(by_typology.items()):
        caught = [row for row in items if row["decision"] != "approved"]
        rejected_items = [row for row in items if row["decision"] == "rejected"]
        total_amount = sum(row["amount_cents"] for row in items)
        caught_amount = sum(row["amount_cents"] for row in caught)
        top_rules = ", ".join(code for code, _ in Counter(c for row in items for c in row["rules"]).most_common(4))
        lines.append(
            f"| {typology} | {len(items)} | {len(caught)} ({pct(len(caught), len(items))}) | {len(rejected_items)} "
            f"| {money(caught_amount)} de {money(total_amount)} ({pct(caught_amount, total_amount)}) | {top_rules} |"
        )

    fraud_amount = sum(row["amount_cents"] for row in fraud)
    fraud_caught = sum(row["amount_cents"] for row in fraud if row["decision"] != "approved")
    lines += [
        "",
        f"**Valor fraudulento contido no total:** {money(fraud_caught)} de {money(fraud_amount)} "
        f"({pct(fraud_caught, fraud_amount)}).",
        "",
        "## O que gera fricção nos legítimos",
        "",
        "| Regra | Vezes em Pix legítimo com 2FA ou rejected |",
        "| --- | --- |",
        *[f"| {code} | {count} |" for code, count in legit_friction_rules.most_common(10)],
        "",
    ]
    lines += channel_section(rows, channel_hits, legit, fraud)

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nRelatório gravado em {REPORT.relative_to(ROOT)}")


def channel_section(rows: list[dict], channel_hits: list[dict], legit: list[dict], fraud: list[dict]) -> list[str]:
    legit_ids = {row["pix_id"] for row in legit}
    fraud_ids = {row["pix_id"] for row in fraud}
    lines = [
        "## Por segmento de canal",
        "",
        "| Segmento | Pix | Legítimos | Fricção em legítimos | Golpes | Golpes interceptados | Valor contido |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for segment in ("mobile", "desktop", "relogio"):
        items = [row for row in rows if SEGMENTS.get(row["channel"]) == segment]
        segment_legit = [row for row in items if row["pix_id"] in legit_ids]
        segment_fraud = [row for row in items if row["pix_id"] in fraud_ids]
        friction = sum(1 for row in segment_legit if row["decision"] != "approved")
        caught = [row for row in segment_fraud if row["decision"] != "approved"]
        fraud_amount = sum(row["amount_cents"] for row in segment_fraud)
        caught_amount = sum(row["amount_cents"] for row in caught)
        lines.append(
            f"| {segment} | {len(items)} | {len(segment_legit)} | {friction} ({pct(friction, len(segment_legit))}) "
            f"| {len(segment_fraud)} | {len(caught)} ({pct(len(caught), len(segment_fraud))}) "
            f"| {pct(caught_amount, fraud_amount)} |"
        )

    lines += [
        "",
        "## Regras de canal",
        "",
        "| Regra | Disparos em legítimos | Disparos em golpes | Observação |",
        "| --- | --- | --- | --- |",
    ]
    for code in CHANNEL_RULES:
        hits = [hit for hit in channel_hits if hit["rule_code"] == code]
        on_legit = sum(1 for hit in hits if hit["pix_id"] in legit_ids)
        on_fraud = sum(1 for hit in hits if hit["pix_id"] in fraud_ids)
        note = ""
        if code == "R2":
            escalated = sum(1 for hit in hits if "escalated_with" in hit["evidence"])
            desktop_fraud = [row for row in fraud if SEGMENTS.get(row["channel"]) == "desktop"]
            reached = [row for row in desktop_fraud if not all(c.startswith("E") for c in row["rules"])]
            note = (f"{escalated} escaladas para rejected; avaliada em {len(reached)} de {len(desktop_fraud)} "
                    "golpes desktop (os demais pararam numa eliminatória)")
        elif code == "K1":
            note = f"por segmento: {dict(Counter(hit['evidence'].get('segment') for hit in hits))}"
        elif code == "K2":
            note = "piso de 2FA, sem pontos"
        lines.append(f"| {code} | {on_legit} | {on_fraud} | {note} |")

    alias = [row for row in rows if row["pix_id"].startswith("pix-app-")]
    alias_ok = sum(1 for row in alias if row["channel"] == "celular")
    held_with_contact = [row for row in rows if (row["metadata"] or {}).get("notify_trusted_contact")]
    with_outbox = sum(1 for row in held_with_contact if row["has_outbox"])
    friction_by_reason = defaultdict(lambda: [0, 0])
    for row in legit:
        friction_by_reason[row["reason"]][0] += 1
        friction_by_reason[row["reason"]][1] += row["decision"] != "approved"

    return lines + [
        "",
        f"**Alias `app`:** {len(alias)} Pix enviados com `channel: app`, {alias_ok} gravados como `celular`.",
        "",
        f"**Aviso ao Contato de Confiança:** {with_outbox} de {len(held_with_contact)} Pix retidos ou barrados com "
        f"`notify_trusted_contact` geraram linha na `notification_outbox` ({pct(with_outbox, len(held_with_contact))}).",
        "",
        "## Fricção por tipo de Pix legítimo",
        "",
        "| Tipo | Pix | Com 2FA ou rejected |",
        "| --- | --- | --- |",
        *[f"| {reason} | {total} | {held} ({pct(held, total)}) |"
          for reason, (total, held) in sorted(friction_by_reason.items())],
        "",
    ]


TABLES = [
    "customer", "account", "merchant", "blocked_mcc", "trusted_contact", "bank_transaction", "ledger_entry",
    "notification_outbox", "fraude.engine_config", "fraude.pix_analysis", "fraude.pix_second_factor",
    "fraude.pix_rule_result", "fraude.device_seen", "fraude.destination_flag", "fraude.destination_reputation",
    "fraude.of_payer_profile", "fraude.pix_feedback", "fraude.pix_shadow_result", "fraude.bet_destination",
]


if __name__ == "__main__":
    main()
