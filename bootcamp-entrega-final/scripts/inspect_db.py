"""
Script Utilitario de Inspecao do Banco de Dados PostgreSQL (Bootcamp Bank).

Mostra o estado atual, volumetria e registros do banco de dados de forma formatada.
Pode ser executado diretamente no terminal pelo comando:
    python scripts/inspect_db.py
"""

import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://bootcamp:bootcamp@localhost:5432/bootcamp"
)

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_title(title: str):
    print(f"\n{BOLD}{CYAN}{'='*80}{RESET}")
    print(f"{BOLD}{CYAN} {title}{RESET}")
    print(f"{BOLD}{CYAN}{'='*80}{RESET}")


def main():
    try:
        engine = create_engine(DATABASE_URL)
        conn = engine.connect()
    except Exception as e:
        print(f"Erro ao conectar ao PostgreSQL ({DATABASE_URL}): {e}")
        return

    print_title("RESUMO DE VOLUMETRIA DO BANCO DE DADOS (POSTGRESQL)")

    counts = conn.execute(text("""
        SELECT 
            (SELECT count(*) FROM customer) AS clientes,
            (SELECT count(*) FROM account) AS contas,
            (SELECT count(*) FROM merchant) AS lojistas,
            (SELECT count(*) FROM trusted_location) AS locais_seguros,
            (SELECT count(*) FROM fraude.pix_analysis) AS analises_pix,
            (SELECT count(*) FROM fraude.pix_rule_result) AS regras_disparadas,
            (SELECT count(*) FROM notification_outbox) AS outbox_notificacoes;
    """)).fetchone()

    print(f" * Total de Clientes Cadastrados  : {BOLD}{GREEN}{counts.clientes:,}{RESET}")
    print(f" * Total de Contas Bancarias      : {BOLD}{GREEN}{counts.contas:,}{RESET}")
    print(f" * Total de Lojistas (Merchants)  : {BOLD}{GREEN}{counts.lojistas:,}{RESET}")
    print(f" * Locais Seguros (Geofencing)    : {BOLD}{counts.locais_seguros}{RESET}")
    print(f" * Analises Antifraude Pix        : {BOLD}{counts.analises_pix}{RESET}")
    print(f" * Regras Antifraude Registradas  : {BOLD}{counts.regras_disparadas}{RESET}")
    print(f" * Eventos Outbox (Notificacoes)  : {BOLD}{counts.outbox_notificacoes}{RESET}")

    # =========================================================================
    # AMOSTRA DE CLIENTES
    # =========================================================================
    print_title("AMOSTRA DE CLIENTES (TABELA 'customer')")
    customers = conn.execute(text("""
        SELECT id, document_number, name, email, created_at 
        FROM customer 
        ORDER BY id ASC 
        LIMIT 5;
    """)).fetchall()

    if customers:
        print(f"{'ID':<6} | {'DOCUMENTO':<18} | {'NOME':<30} | {'EMAIL'}")
        print("-" * 80)
        for c in customers:
            print(f"{c.id:<6} | {c.document_number:<18} | {c.name[:30]:<30} | {c.email}")
    else:
        print("Nenhum cliente cadastrado no momento.")

    # =========================================================================
    # AMOSTRA DE CONTAS
    # =========================================================================
    print_title("AMOSTRA DE CONTAS (TABELA 'account')")
    accounts = conn.execute(text("""
        SELECT a.id, a.customer_id, c.name, a.balance_cents, a.transfer_limit_cents 
        FROM account a
        JOIN customer c ON a.customer_id = c.id
        ORDER BY a.id ASC 
        LIMIT 5;
    """)).fetchall()

    if accounts:
        print(f"{'ID':<6} | {'TITULAR':<30} | {'SALDO':<15} | {'LIMITE DIARIO'}")
        print("-" * 80)
        for a in accounts:
            saldo = f"R$ {a.balance_cents / 100:,.2f}"
            limite = f"R$ {a.transfer_limit_cents / 100:,.2f}"
            print(f"{a.id:<6} | {a.name[:30]:<30} | {saldo:<15} | {limite}")
    else:
        print("Nenhuma conta cadastrada no momento.")

    # =========================================================================
    # ANALISES PIX
    # =========================================================================
    print_title("ULTIMAS AVALIACOES ANTIFRAUDE (TABELA 'fraude.pix_analysis')")
    pix_analyses = conn.execute(text("""
        SELECT 
            p.id, 
            p.pix_id, 
            p.status, 
            p.score, 
            p.amount_cents, 
            p.channel,
            p.metadata->>'customer_message_key' AS msg_key,
            p.created_at
        FROM fraude.pix_analysis p
        ORDER BY p.id DESC 
        LIMIT 5;
    """)).fetchall()

    if pix_analyses:
        print(f"{'ID':<4} | {'PIX ID':<25} | {'STATUS':<12} | {'SCORE':<5} | {'VALOR':<12} | {'MENSAGEM AO CLIENTE'}")
        print("-" * 80)
        for p in pix_analyses:
            valor = f"R$ {p.amount_cents / 100:.2f}"
            status_color = GREEN if p.status == "approved" else (YELLOW if p.status == "two_factor_required" else RED)
            status_fmt = f"{status_color}{p.status}{RESET}"
            msg = p.msg_key or "-"
            print(f"{p.id:<4} | {p.pix_id[:25]:<25} | {status_fmt:<20} | {str(p.score or 0):<5} | {valor:<12} | {msg}")
    else:
        print("Nenhuma analise Pix registrada ainda.")

    # =========================================================================
    # LOCAIS SEGUROS
    # =========================================================================
    print_title("LOCAIS SEGUROS CADASTRADOS (TABELA 'trusted_location')")
    locations = conn.execute(text("""
        SELECT id, account_id, name, latitude, longitude, radius_meters 
        FROM trusted_location 
        ORDER BY id ASC;
    """)).fetchall()

    if locations:
        print(f"{'ID':<4} | {'CONTA':<6} | {'NOME':<32} | {'LATITUDE':<12} | {'LONGITUDE':<12} | {'RAIO'}")
        print("-" * 80)
        for loc in locations:
            print(f"{loc.id:<4} | {loc.account_id:<6} | {loc.name[:32]:<32} | {float(loc.latitude):<12.6f} | {float(loc.longitude):<12.6f} | {loc.radius_meters}m")
    else:
        print("Nenhum local seguro cadastrado no momento.")

    print(f"\n{BOLD}Conexao finalizada com sucesso.{RESET}\n")
    conn.close()
    engine.dispose()


if __name__ == "__main__":
    main()
