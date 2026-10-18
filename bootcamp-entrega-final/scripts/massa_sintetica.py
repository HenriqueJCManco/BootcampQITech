"""Massa sintética do Pix Seguro 60+.

Recria o banco, grava os cadastros do Banco 60+ e as tabelas de apoio do
schema fraude direto no PostgreSQL e manda 600 Pix pela API, em ordem de
data, para que análise, regras, aparelhos, reputação, marcações e outbox
sejam produzidos pelo próprio motor. Cada Pix recebe um rótulo em
pix_feedback (legítimo ou tipologia de golpe), que o backtest usa.

Uso (com o banco e a API de pé):
    python scripts/massa_sintetica.py
"""

import hashlib
import math
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from domain.identity import destination_key, document_hash  # noqa: E402


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2://bootcamp:bootcamp@localhost:5432/bootcamp")
API_URL = os.environ.get("API_URL", "http://127.0.0.1:3000")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "default_token")

ROWS = 600
PAYERS = 100
LANDLORDS = 60
RELATIVES = 120
MULES = 2
BRT = timezone(timedelta(hours=-3))
END = (datetime.now(BRT) - timedelta(hours=2)).replace(second=0, microsecond=0)
START = END - timedelta(days=160)
FEE_CENTS = 100
REGULAR_PAYERS = 90
DEVICE_PREFIX = {"celular": "cel", "app": "cel", "tablet": "cel", "computador": "pc", "internet": "pc"}

FIRST_NAMES = [
    "Maria", "José", "Antônio", "Francisca", "Ana", "João", "Raimunda", "Sebastião", "Terezinha", "Benedito",
    "Luzia", "Geraldo", "Aparecida", "Joaquim", "Conceição", "Manoel", "Irene", "Pedro", "Lourdes", "Osvaldo",
]
LAST_NAMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Pereira", "Costa", "Rodrigues", "Almeida", "Nascimento", "Lima",
    "Araújo", "Fernandes", "Carvalho", "Gomes", "Martins", "Rocha", "Ribeiro", "Barbosa", "Ferreira", "Moura",
]
CITIES = [
    (-23.5505, -46.6333), (-22.9056, -47.0608), (-23.9608, -46.3336), (-21.1775, -47.8103),
    (-23.5015, -47.4526), (-22.9068, -43.1729), (-19.9167, -43.9345),
]
MERCHANT_MCCS = [("5411", "Supermercado"), ("5912", "Farmácia"), ("4900", "Companhia de Energia"),
                 ("5812", "Restaurante"), ("4814", "Telefonia"), ("8011", "Clínica")]


def check_digits(base: list[int], weights: list[int]) -> int:
    remainder = sum(digit * weight for digit, weight in zip(base, weights)) % 11
    return 0 if remainder < 2 else 11 - remainder


def new_cpf(rng: random.Random) -> str:
    digits = [rng.randint(0, 9) for _ in range(9)]
    digits.append(check_digits(digits, list(range(10, 1, -1))))
    digits.append(check_digits(digits, list(range(11, 1, -1))))
    raw = "".join(map(str, digits))
    return f"{raw[:3]}.{raw[3:6]}.{raw[6:9]}-{raw[9:]}"


def new_cnpj(rng: random.Random, root: str | None = None) -> str:
    digits = [int(char) for char in (root or "".join(str(rng.randint(0, 9)) for _ in range(8)))] + [0, 0, 0, 1]
    digits.append(check_digits(digits, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    digits.append(check_digits(digits, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    raw = "".join(map(str, digits))
    return f"{raw[:2]}.{raw[2:5]}.{raw[5:8]}/{raw[8:12]}-{raw[12:]}"


def digits(document: str) -> str:
    return "".join(char for char in document if char.isdigit())


def person_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)} {rng.choice(LAST_NAMES)}"


def external_account(rng: random.Random, document: str | None = None) -> dict:
    return {
        "document_number": document or new_cpf(rng),
        "participant": f"{rng.randint(10000000, 99999999)}",
        "branch": f"{rng.randint(1, 9999):04d}",
        "number": f"{rng.randint(100000, 99999999)}",
    }


def external_key(account: dict) -> str:
    return destination_key(account["participant"], account["branch"], account["number"], account["document_number"])


class Seeder:
    def __init__(self) -> None:
        self.rng = random.Random(60)
        self.engine = create_engine(DATABASE_URL)
        self.session = requests.Session()
        self.session.headers["INTERNAL-TOKEN"] = INTERNAL_TOKEN
        self.customers: list[dict] = []
        self.events: list[tuple[datetime, int, str, dict]] = []
        self.labels: dict[str, tuple[bool, str]] = {}
        self.sequence = 0

    def run(self) -> None:
        self.reset_database()
        with self.engine.begin() as connection:
            self.seed_customers(connection)
            self.seed_registry_tables(connection)
        self.plan_legit_pix()
        self.plan_fraud_pix()
        self.replay_events()
        self.send_feedback()
        self.seed_shadow_results()
        print(f"Massa gerada: {len(self.labels)} Pix analisados entre {START:%d/%m/%Y} e {END:%d/%m/%Y}.")

    def reset_database(self) -> None:
        schema = (ROOT / "database" / "database.sql").read_text(encoding="utf-8")
        with create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT").connect() as connection:
            connection.exec_driver_sql("DROP SCHEMA IF EXISTS fraude CASCADE;")
            connection.exec_driver_sql("DROP SCHEMA public CASCADE;")
            connection.exec_driver_sql("CREATE SCHEMA public;")
            connection.exec_driver_sql(schema)

    def add_customer(self, connection, role: str, created_at: datetime, document: str | None = None,
                     name: str | None = None) -> dict:
        rng = self.rng
        document = document or new_cpf(rng)
        name = name or person_name(rng)
        customer_id = connection.execute(
            text("INSERT INTO customer (document_number, email, name, created_at) "
                 "VALUES (:document, :email, :name, :created_at) RETURNING id"),
            {"document": document, "email": f"{uuid.uuid4().hex[:12]}@massa.test", "name": name, "created_at": created_at},
        ).scalar_one()
        account_id, account_key = connection.execute(
            text("INSERT INTO account (customer_id, transfer_limit_cents, created_at) "
                 "VALUES (:customer_id, 500000, :created_at) RETURNING id, account_key"),
            {"customer_id": customer_id, "created_at": created_at + timedelta(days=1)},
        ).one()
        customer = {
            "index": len(self.customers), "role": role, "document": document, "name": name,
            "account_id": account_id, "account_key": str(account_key), "created_at": created_at,
            "home": rng.choice(CITIES), "contacts": 0,
        }
        self.customers.append(customer)
        return customer

    def seed_customers(self, connection) -> None:
        rng = self.rng
        for index in range(PAYERS):
            created_at = END - timedelta(days=rng.randint(730, 3650))
            if index >= PAYERS - 5:
                cpf = digits(new_cpf(rng))
                name = f"{person_name(rng).upper()} {cpf}"
                self.add_customer(connection, "payer", created_at, new_cnpj(rng), name)
            else:
                self.add_customer(connection, "payer", created_at)
        for _ in range(LANDLORDS):
            self.add_customer(connection, "landlord", END - timedelta(days=rng.randint(1000, 5000)))
        for _ in range(RELATIVES):
            self.add_customer(connection, "relative", END - timedelta(days=rng.randint(200, 3000)))
        for _ in range(MULES):
            self.add_customer(connection, "mule", END - timedelta(days=5))
        while len(self.customers) < ROWS:
            document = new_cnpj(rng) if rng.random() < 0.1 else None
            self.add_customer(connection, "other", END - timedelta(days=rng.randint(30, 4000)), document)

    def seed_registry_tables(self, connection) -> None:
        rng = self.rng
        payers = [customer for customer in self.customers if customer["role"] == "payer"]

        blocked = [{"account_id": customer["account_id"], "mcc": "7995"} for customer in self.customers]
        blocked += [{"account_id": customer["account_id"], "mcc": "7801"} for customer in rng.sample(payers, 50)]
        connection.execute(text("INSERT INTO blocked_mcc (account_id, mcc) VALUES (:account_id, :mcc)"), blocked)

        self.merchants = []
        for index in range(ROWS):
            mcc, kind = ("7995", "Apostas") if index < 30 else rng.choice(MERCHANT_MCCS)
            merchant = {"document_number": new_cnpj(rng), "name": f"{kind} {rng.choice(LAST_NAMES)} {index}", "mcc": mcc}
            self.merchants.append(merchant)
        connection.execute(
            text("INSERT INTO merchant (document_number, name, mcc) VALUES (:document_number, :name, :mcc)"),
            self.merchants,
        )

        contacts = []
        for customer in payers:
            for _ in range(1 if rng.random() < 0.6 else 2):
                contacts.append(customer)
        others = [customer for customer in self.customers if customer["role"] in ("other", "relative")]
        while len(contacts) < ROWS:
            contacts.append(rng.choice(others))
        rows = []
        for customer in contacts:
            if customer["contacts"] >= 2:
                continue
            customer["contacts"] += 1
            rows.append({
                "account_id": customer["account_id"], "name": person_name(rng),
                "channel": rng.choice(["SMS", "EMAIL"]), "address": f"contato{len(rows)}@massa.test",
                "created_at": customer["created_at"] + timedelta(days=30),
                "consent": customer["created_at"] + timedelta(days=60) if rng.random() < 0.4 else None,
            })
        while len(rows) < ROWS:
            customer = rng.choice([item for item in others if item["contacts"] < 2])
            customer["contacts"] += 1
            rows.append({
                "account_id": customer["account_id"], "name": person_name(rng), "channel": "EMAIL",
                "address": f"contato{len(rows)}@massa.test", "created_at": customer["created_at"] + timedelta(days=30),
                "consent": None,
            })
        connection.execute(
            text("INSERT INTO trusted_contact (account_id, name, channel, address, created_at, approval_consent_at) "
                 "VALUES (:account_id, :name, :channel, :address, :created_at, :consent)"),
            rows,
        )

        existing = {cnpj for (cnpj,) in connection.execute(text("SELECT cnpj FROM fraude.bet_destination"))}
        target = ROWS - len(existing)
        bets = []
        while len(bets) < target:
            cnpj = digits(new_cnpj(rng))
            if cnpj not in existing:
                existing.add(cnpj)
                bets.append({"cnpj": cnpj, "razao_social": f"Bet Fictícia {len(bets)} Ltda", "source": "massa_sintetica"})
        connection.execute(
            text("INSERT INTO fraude.bet_destination (cnpj, razao_social, source) VALUES (:cnpj, :razao_social, :source)"),
            bets,
        )
        self.bet_cnpjs = [bet["cnpj"] for bet in bets]

        self.marked_accounts = [external_account(rng) for _ in range(10)]
        marks = []
        for index in range(ROWS):
            account = self.marked_accounts[index] if index < len(self.marked_accounts) else external_account(rng)
            starts_at = END - timedelta(days=rng.randint(10, 1400))
            marks.append({
                "key": external_key(account), "status": "MARCADA",
                "reason": rng.choice(["bcb_587_marcacao", "feedback_fraude_confirmada"]),
                "starts_at": starts_at, "expires_at": starts_at + timedelta(days=5 * 365),
            })
        connection.execute(
            text("INSERT INTO fraude.destination_flag (destination_key, status, reason, starts_at, expires_at) "
                 "VALUES (:key, :status, :reason, :starts_at, :expires_at)"),
            marks,
        )

        devices, profiles = [], []
        for customer in self.customers:
            source_hash = document_hash(customer["document"])
            prefixes = ("cel", "pc") if customer["role"] == "payer" else ("cel",)
            for prefix in prefixes:
                devices.append({
                    "device_id": f"{prefix}-{customer['index']}", "source_hash": source_hash,
                    "first_seen": START - timedelta(days=rng.randint(60, 400)), "last_seen": START - timedelta(days=1),
                    "tx_count": rng.randint(5, 60),
                })
            loaded_at = END - timedelta(days=rng.randint(0, 20))
            balance = rng.randint(0, 6_000_000)
            profiles.append({
                "account_id": customer["account_id"], "income": rng.choice([0, 0, rng.randint(50_000, 400_000)]),
                "balance": balance, "previous": balance + rng.randint(-200_000, 200_000) if rng.random() < 0.7 else None,
                "previous_at": loaded_at - timedelta(days=7), "loaded_at": loaded_at,
                "consent": END + timedelta(days=180) if rng.random() < 0.8 else END - timedelta(days=10),
            })
        for profile in profiles:
            if profile["previous"] is not None:
                profile["previous"] = max(profile["previous"], 0)
            else:
                profile["previous_at"] = None
        connection.execute(
            text("INSERT INTO fraude.device_seen (device_id, source_hash, first_seen, last_seen, tx_count) "
                 "VALUES (:device_id, :source_hash, :first_seen, :last_seen, :tx_count)"),
            devices,
        )
        connection.execute(
            text("INSERT INTO fraude.of_payer_profile (account_id, other_income_cents, other_balance_cents, "
                 "other_balance_prev_cents, prev_loaded_at, loaded_at, consent_expires_at) "
                 "VALUES (:account_id, :income, :balance, :previous, :previous_at, :loaded_at, :consent)"),
            profiles,
        )

        for customer in payers:
            benefit = rng.randint(141_200, 600_000)
            day = START.replace(hour=9, minute=0)
            while day <= END:
                self.schedule(day + timedelta(days=rng.randint(0, 2), minutes=rng.randint(0, 120)), "deposit",
                              {"account_id": customer["account_id"], "amount": benefit})
                day += timedelta(days=30)

    def schedule(self, moment: datetime, kind: str, data: dict) -> None:
        self.sequence += 1
        self.events.append((moment, self.sequence, kind, data))

    def pix_body(self, payer: dict, moment: datetime, amount: int, destination: dict, **source) -> dict:
        source_account = {"document_number": payer["document"], "has_trusted_contact": payer["contacts"] > 0}
        if len(digits(payer["document"])) == 14:
            source_account["owner"] = {"name": payer["name"]}
        prefix = "pix-app" if source.get("channel") == "app" else "pix"
        body = {
            "id": f"{prefix}-{uuid.UUID(int=self.rng.getrandbits(128))}",
            "amount": amount,
            "transaction_date": moment.isoformat(),
            "source_account": source_account,
            "destination_account": destination,
            "source": {"device_id": f"cel-{payer['index']}", "channel": "celular",
                       "remote_access_detected": False, "call_in_progress": False, **source},
        }
        return {key: value for key, value in body.items() if value is not None}

    def location(self, payer: dict) -> dict:
        latitude, longitude = payer["home"]
        return {"latitude": round(latitude + self.rng.uniform(-0.02, 0.02), 5),
                "longitude": round(longitude + self.rng.uniform(-0.02, 0.02), 5),
                "accuracy_m": self.rng.choice([15, 30, 65, 120])}

    def human_interaction(self) -> dict:
        return {"is_robotic_movement": False, "typing_cadence_std_ms": round(self.rng.uniform(90, 220), 1),
                "session_idle_then_burst": False}

    def legit(self, payer: dict, moment: datetime, amount: int, destination: dict, reason: str, channel: str = "celular") -> None:
        source = {"channel": channel, "device_id": f"{DEVICE_PREFIX[channel]}-{payer['index']}"}
        if channel in ("computador", "internet"):
            source["interaction"] = self.human_interaction()
        elif self.rng.random() < 0.7:
            source["geolocation"] = self.location(payer)
        body = self.pix_body(payer, moment, amount, destination, **source)
        self.schedule(moment, "pix", {"body": body, "fraud": False, "reason": reason, "payer": payer})

    def internal(self, customer: dict) -> dict:
        return {"document_number": customer["document"], "account_key": customer["account_key"]}

    def plan_legit_pix(self) -> None:
        rng = self.rng
        payers = [customer for customer in self.customers if customer["role"] == "payer"]
        landlords = [customer for customer in self.customers if customer["role"] == "landlord"]
        relatives = [customer for customer in self.customers if customer["role"] == "relative"]
        bills = [merchant for merchant in self.merchants if merchant["mcc"] != "7995"]

        def bill_destination() -> dict:
            return external_account(rng, rng.choice(bills)["document_number"])

        for index, payer in enumerate(payers[:REGULAR_PAYERS]):
            landlord = landlords[index % len(landlords)]
            relative = relatives[index % len(relatives)]
            rent = rng.randint(70_000, 150_000)
            for month in range(4, 0, -1):
                moment = (END - timedelta(days=30 * month + 12)).replace(
                    hour=rng.randint(9, 16), minute=rng.randint(0, 59))
                draw = rng.random()
                channel = "tablet" if draw < 0.15 else "app" if draw < 0.25 else "celular"
                self.legit(payer, moment, rent, self.internal(landlord), "legitimo_aluguel", channel)
            if index >= 60:
                continue
            moment = (END - timedelta(days=rng.randint(15, 100))).replace(hour=rng.randint(8, 18), minute=rng.randint(0, 59))
            if rng.random() < 0.5:
                self.legit(payer, moment, rng.randint(10_000, 50_000), self.internal(relative), "legitimo_familia")
            else:
                self.legit(payer, moment, rng.randint(4_000, 25_000), bill_destination(), "legitimo_conta")

        for index, payer in enumerate(payers[REGULAR_PAYERS:]):
            for step in range(5):
                moment = (END - timedelta(days=80 - 14 * step)).replace(hour=rng.randint(9, 17), minute=rng.randint(0, 59))
                self.legit(payer, moment, rng.randint(5_000, 30_000), bill_destination(), "legitimo_conta",
                           "app" if step % 2 else "celular")
            moment = (END - timedelta(days=rng.uniform(3, 6))).replace(hour=rng.randint(9, 17), minute=rng.randint(0, 59))
            relative = relatives[(REGULAR_PAYERS + index) % len(relatives)]
            self.legit(payer, moment, rng.randint(15_000, 60_000), self.internal(relative),
                       "legitimo_desktop_ocasional", "computador" if index < 5 else "internet")

    def fraud(self, payer: dict, moment: datetime, amount: int, destination: dict, reason: str,
              is_fraud: bool = True, **source) -> None:
        body = self.pix_body(payer, moment, amount, destination, **source)
        self.schedule(moment, "pix", {"body": body, "fraud": is_fraud, "reason": reason, "payer": payer})

    def plan_fraud_pix(self) -> None:
        rng = self.rng
        victims = iter([customer for customer in self.customers if customer["role"] == "payer"])

        def day_moment(days_back: float, hour: int) -> datetime:
            return (END - timedelta(days=days_back)).replace(hour=hour, minute=rng.randint(0, 59))

        for _ in range(10):
            payer = next(victims)
            self.fraud(payer, day_moment(rng.uniform(1, 8), rng.randint(9, 17)), rng.randint(200_000, 400_000),
                       external_account(rng), "golpe_falsa_central", call_in_progress=True,
                       geolocation=self.location(payer))
        for _ in range(10):
            payer = next(victims)
            interaction = {"is_robotic_movement": True, "typing_cadence_std_ms": round(rng.uniform(0, 8), 1),
                           "session_idle_then_burst": rng.random() < 0.7}
            self.fraud(payer, day_moment(rng.uniform(1, 8), rng.randint(9, 17)), rng.randint(150_000, 300_000),
                       external_account(rng), "golpe_mao_fantasma", channel="computador",
                       device_id=f"pc-remoto-{payer['index']}", remote_access_detected=True, interaction=interaction)
        for _ in range(10):
            payer = next(victims)
            moment = (END - timedelta(days=rng.uniform(1, 8))).replace(hour=rng.choice([21, 22, 23, 0, 1]),
                                                                       minute=rng.randint(0, 59))
            self.fraud(payer, moment, rng.randint(150_000, 300_000), external_account(rng),
                       "golpe_sequestro_relampago")
        for _ in range(10):
            payer = next(victims)
            test_moment = day_moment(rng.uniform(1, 8), rng.randint(9, 16))
            destination = external_account(rng)
            self.fraud(payer, test_moment, rng.randint(1, 1_000), destination, "golpe_teste_e_drenagem")
            self.fraud(payer, test_moment + timedelta(minutes=rng.randint(20, 60)), rng.randint(200_000, 500_000),
                       destination, "golpe_teste_e_drenagem")
        for _ in range(10):
            payer = next(victims)
            moment = day_moment(rng.uniform(1, 8), rng.randint(9, 15))
            for step in range(3):
                self.fraud(payer, moment + timedelta(minutes=25 * step), rng.randint(16_500, 19_900),
                           external_account(rng), "golpe_fracionamento")
        for _ in range(10):
            payer = next(victims)
            interaction = {"is_robotic_movement": True, "typing_cadence_std_ms": round(rng.uniform(0, 6), 1),
                           "session_idle_then_burst": rng.random() < 0.5}
            self.fraud(payer, day_moment(rng.uniform(1, 8), rng.randint(9, 17)), rng.randint(30_000, 90_000),
                       external_account(rng), "golpe_desktop_robotico_conhecido", channel="computador",
                       device_id=f"pc-{payer['index']}", remote_access_detected=True, interaction=interaction)
        for _ in range(10):
            payer = next(victims)
            interaction = {"typing_cadence_std_ms": round(rng.uniform(0.5, 4), 1), "session_idle_then_burst": True}
            self.fraud(payer, day_moment(rng.uniform(1, 8), rng.randint(9, 17)), rng.randint(20_000, 80_000),
                       external_account(rng), "golpe_bot_internet", channel="internet",
                       device_id=f"pc-{payer['index']}", interaction=interaction)
        mules = [customer for customer in self.customers if customer["role"] == "mule"]
        for mule in mules:
            window = END - timedelta(days=rng.uniform(1, 3))
            for step in range(5):
                credit_at = window - timedelta(hours=6 - step)
                amount = rng.randint(80_000, 150_000)
                self.schedule(credit_at, "deposit", {"account_id": mule["account_id"], "amount": amount})
                self.schedule(credit_at + timedelta(minutes=rng.randint(8, 25)), "forward",
                              {"account_id": mule["account_id"], "amount": int(amount * 0.9)})
            for step in range(5):
                payer = next(victims)
                self.fraud(payer, window + timedelta(minutes=40 * step), rng.randint(50_000, 150_000),
                           self.internal(mule), "golpe_mula")
        for account in self.marked_accounts[:5]:
            payer = next(victims)
            self.fraud(payer, day_moment(rng.uniform(1, 8), rng.randint(9, 17)), rng.randint(30_000, 80_000),
                       account, "golpe_destino_marcado")
        for cnpj in self.bet_cnpjs[:5]:
            payer = next(victims)
            document = f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
            self.fraud(payer, day_moment(rng.uniform(1, 8), rng.randint(10, 20)), rng.randint(5_000, 30_000),
                       external_account(rng, document), "bet_regulatoria", is_fraud=False)

    def replay_events(self) -> None:
        for moment, _, kind, data in sorted(self.events, key=lambda event: (event[0], event[1])):
            if kind == "deposit":
                self.deposit(data["account_id"], data["amount"], moment)
            elif kind == "forward":
                self.transfer(data["account_id"], None, data["amount"], moment, f"fwd-{uuid.uuid4()}", fee=0)
            else:
                self.send_pix(data, moment)

    def send_pix(self, data: dict, moment: datetime) -> None:
        body = data["body"]
        response = self.session.post(f"{API_URL}/pix/transaction", json=body, timeout=30)
        if response.status_code not in (200, 201):
            raise RuntimeError(f"POST /pix/transaction {response.status_code}: {response.text}")
        status = response.json()["status"]
        self.labels[body["id"]] = (data["fraud"], data["reason"])

        if status == "two_factor_required" and not data["fraud"] and data["reason"].startswith("legitimo"):
            retry = {**body, "second_factor_passed": True, "friction_answer": "NO"}
            status = self.session.post(f"{API_URL}/pix/transaction", json=retry, timeout=30).json()["status"]

        if status == "approved":
            destination = data["body"]["destination_account"]
            target = next((c for c in self.customers if c["account_key"] == destination.get("account_key")), None)
            self.transfer(data["payer"]["account_id"], target["account_id"] if target else None,
                          body["amount"], moment + timedelta(seconds=5), body["id"])

    def deposit(self, account_id: int, amount: int, moment: datetime) -> None:
        with self.engine.begin() as connection:
            transaction_id = self.bank_transaction(connection, f"dep-{uuid.uuid4()}", "DEPOSIT", None, account_id,
                                                   amount, 0, moment)
            self.ledger(connection, account_id, transaction_id, "CREDIT", "DEPOSIT", amount, moment)

    def transfer(self, source_id: int, target_id: int | None, amount: int, moment: datetime, key: str,
                 fee: int = FEE_CENTS) -> bool:
        with self.engine.begin() as connection:
            balance = connection.execute(text("SELECT balance_cents FROM account WHERE id = :id FOR UPDATE"),
                                         {"id": source_id}).scalar_one()
            if balance < amount + fee:
                return False
            transaction_id = self.bank_transaction(connection, key, "TRANSFER", source_id, target_id, amount, fee, moment)
            self.ledger(connection, source_id, transaction_id, "DEBIT", "TRANSFER", -amount, moment)
            if fee:
                self.ledger(connection, source_id, transaction_id, "DEBIT", "FEE", -fee, moment)
            if target_id is not None:
                self.ledger(connection, target_id, transaction_id, "CREDIT", "TRANSFER", amount, moment)
            return True

    @staticmethod
    def bank_transaction(connection, key, kind, source_id, target_id, amount, fee, moment) -> int:
        return connection.execute(
            text("INSERT INTO bank_transaction (idempotency_key, request_hash, type, from_account_id, to_account_id, "
                 "amount_cents, fee_cents, created_at) VALUES (:key, :hash, :type, :source, :target, :amount, :fee, :at) "
                 "RETURNING id"),
            {"key": key, "hash": hashlib.sha256(key.encode()).hexdigest(), "type": kind, "source": source_id,
             "target": target_id, "amount": amount, "fee": fee, "at": moment},
        ).scalar_one()

    @staticmethod
    def ledger(connection, account_id, transaction_id, direction, kind, signed_amount, moment) -> None:
        balance = connection.execute(
            text("UPDATE account SET balance_cents = balance_cents + :amount WHERE id = :id RETURNING balance_cents"),
            {"amount": signed_amount, "id": account_id},
        ).scalar_one()
        connection.execute(
            text("INSERT INTO ledger_entry (account_id, transaction_id, direction, kind, amount_cents, "
                 "balance_after_cents, entry_datetime) VALUES (:account, :transaction, :direction, :kind, :amount, "
                 ":balance, :at)"),
            {"account": account_id, "transaction": transaction_id, "direction": direction, "kind": kind,
             "amount": abs(signed_amount), "balance": balance, "at": moment},
        )

    def send_feedback(self) -> None:
        for pix_id, (is_fraud, reason) in self.labels.items():
            response = self.session.post(f"{API_URL}/pix/feedback",
                                         json={"transaction_id": pix_id, "is_fraud": is_fraud, "reason": reason},
                                         timeout=30)
            if response.status_code != 201:
                raise RuntimeError(f"POST /pix/feedback {response.status_code}: {response.text}")

    def seed_shadow_results(self) -> None:
        with self.engine.begin() as connection:
            rows = connection.execute(text("SELECT id, score FROM fraude.pix_analysis")).all()
            connection.execute(
                text("INSERT INTO fraude.pix_shadow_result (analysis_id, shadow_score, model_version) "
                     "VALUES (:id, :score, 'shadow-baseline-sintetico-v0')"),
                [{"id": analysis_id,
                  "score": round(min(max(1 / (1 + math.exp(-(score - 45) / 8)) + self.rng.gauss(0, 0.05), 0), 1), 4)}
                 for analysis_id, score in rows],
            )


if __name__ == "__main__":
    Seeder().run()
