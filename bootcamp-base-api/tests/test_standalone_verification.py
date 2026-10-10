import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Setup environment variables before imports
os.environ["APP_ENV"] = "local"
os.environ["SERVICE_NAME"] = "transaction-api"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["INTERNAL_TOKEN"] = "default_token"

sys.path.insert(0, os.path.abspath("src"))
sys.path.insert(0, os.path.abspath("."))

from app import app
from controllers import CustomerController, AccountController, TransactionController
from errors.base_error import error_verification, ForbiddenNotInternal, NotFoundResource
from errors.custom_errors import (
    BlockedByVault,
    CustomerAlreadyHasAccount,
    DuplicateCustomer,
    IdempotencyConflict,
    InsufficientFunds,
    InvalidAmount,
    InvalidCustomerDocument,
    InvalidMerchantDocument,
    InvalidTransferLimit,
    SameAccountTransfer,
    TransferLimitExceeded,
    TrustedContactLimitReached,
)
from models.base import Base
from models import (
    Customer,
    Account,
    Merchant,
    BlockedMCC,
    TrustedContact,
    BankTransaction,
    LedgerEntry,
    NotificationOutbox,
)
from tests.utils.random_generator import RandomGenerator
from utils.document_number import is_valid_cpf, is_valid_cnpj, is_valid_document_number
from utils.identifiers import parse_uuid
from utils.schema_handler import SchemaCache
from jsonschema import validate, ValidationError


# ─────────────────────────────────────────────────────────────
# Fixtures e Setup em memória para SQLite
# ─────────────────────────────────────────────────────────────

_id_counter = 0

def _next_id():
    global _id_counter
    _id_counter += 1
    return _id_counter

@event.listens_for(Customer, "init")
def _init_customer(target, args, kwargs):
    target.id = _next_id()
    if "customer_key" not in kwargs:
        target.customer_key = uuid.uuid4()

@event.listens_for(Account, "init")
def _init_account(target, args, kwargs):
    target.id = _next_id()
    if "account_key" not in kwargs:
        target.account_key = uuid.uuid4()

@event.listens_for(TrustedContact, "init")
def _init_contact(target, args, kwargs):
    target.id = _next_id()
    if "contact_key" not in kwargs:
        target.contact_key = uuid.uuid4()

@event.listens_for(BankTransaction, "init")
def _init_tx(target, args, kwargs):
    target.id = _next_id()
    if "transaction_key" not in kwargs:
        target.transaction_key = uuid.uuid4()

@event.listens_for(LedgerEntry, "init")
def _init_ledger(target, args, kwargs):
    target.id = _next_id()
    if "entry_key" not in kwargs:
        target.entry_key = uuid.uuid4()

@event.listens_for(BlockedMCC, "init")
def _init_blocked_mcc(target, args, kwargs):
    target.id = _next_id()

@event.listens_for(Merchant, "init")
def _init_merchant(target, args, kwargs):
    target.id = _next_id()

@event.listens_for(NotificationOutbox, "init")
def _init_outbox(target, args, kwargs):
    target.id = _next_id()


class MockContext:
    def __init__(self, session):
        self.db_session = session

    def get_or_create_session(self):
        return self.db_session


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def test_client():
    return TestClient(app)


# ─────────────────────────────────────────────────────────────
# 1. Testes de Rotas e Healthcheck (HTTP direto com TestClient)
# ─────────────────────────────────────────────────────────────

class TestHealthCheckRoutes:
    def test_home(self, test_client):
        response = test_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "transaction-api"
        assert "id" in data

    def test_health_check(self, test_client):
        response = test_client.get("/health_check")
        assert response.status_code == 204
        assert response.content == b""

    def test_no_token(self, test_client):
        response = test_client.put("/sample")
        assert response.status_code == 403
        data = response.json()
        assert data["code"] == "BNK000002"
        assert data["translation"] == "Requisição não autorizada."

    def test_sink(self, test_client):
        response = test_client.put("/sample", headers={"INTERNAL-TOKEN": "default_token"})
        assert response.status_code == 404
        data = response.json()
        assert data["code"] == "BNK000404"
        assert data["translation"] == "O recurso solicitado não foi encontrado."

    def test_method_not_allowed(self, test_client):
        response = test_client.put("/health_check")
        assert response.status_code == 405
        assert response.json()["code"] == "BNK000405"

    def test_error_translation_keeps_accents(self, test_client):
        # 403 no middleware de token
        r1 = test_client.put("/sample")
        assert r1.status_code == 403
        assert r1.json()["translation"] == "Requisição não autorizada."

        # 404 no exception handler interno
        r2 = test_client.put("/sample", headers={"INTERNAL-TOKEN": "default_token"})
        assert r2.status_code == 404
        assert r2.json()["translation"] == "O recurso solicitado não foi encontrado."


# ─────────────────────────────────────────────────────────────
# 2. Validação de Documentos e Identificadores
# ─────────────────────────────────────────────────────────────

class TestDocumentAndUUIDValidation:
    def test_cpf_validation(self):
        # CPF gerado com dígitos verificadores corretos
        for _ in range(10):
            cpf = RandomGenerator.generate_cpf()
            assert is_valid_cpf(cpf)
            assert is_valid_document_number(cpf)

        # CPF com dígitos todos iguais (inválido por regra da Receita)
        assert not is_valid_cpf("111.111.111-11")
        # CPF com dígito verificador adulterado
        assert not is_valid_cpf("529.982.247-00")

    def test_cnpj_validation(self):
        for _ in range(10):
            cnpj = RandomGenerator.generate_cnpj()
            assert is_valid_cnpj(cnpj)
            assert is_valid_document_number(cnpj)

        assert not is_valid_cnpj("11.111.111/1111-11")
        assert not is_valid_cnpj("12.345.678/0001-00")

    def test_uuid_validation(self):
        valid = "c0a80101-0000-0000-0000-000000000001"
        assert str(parse_uuid(valid, "account_key")) == valid

        with pytest.raises(Exception) as exc_info:
            parse_uuid("not-a-uuid", "account_key")
        assert exc_info.value.code == "BNK000001"
        assert exc_info.value.http_status == 400


# ─────────────────────────────────────────────────────────────
# 3. Schemas JSON e Proteção contra Vazamento de Dados Privados
# ─────────────────────────────────────────────────────────────

class TestSchemasAndSafety:
    def test_post_customer_schema_rejects_malformed_email(self):
        schema = SchemaCache.get_schema("post_customer.json")
        # Válido
        validate({"name": "Ana", "email": "ana@test.com", "document_number": "123.456.789-01"}, schema)

        # Inválido
        with pytest.raises(ValidationError):
            validate({"name": "Ana", "email": "private-address-without-at", "document_number": "123.456.789-01"}, schema)

    def test_error_verification_no_duplicate_codes(self):
        # Garante que nenhum código BNK está duplicado entre as classes de erro
        error_verification()


# ─────────────────────────────────────────────────────────────
# 4. Ciclo de Vida do Cliente e da Conta
# ─────────────────────────────────────────────────────────────

class TestCustomerAndAccountFlow:
    def test_create_customer_and_account(self, db_session):
        mock_ctx = MockContext(db_session)
        with patch("controllers.base_controller.get_context", return_value=mock_ctx):
            cust_ctrl = CustomerController()
            payload = {
                "name": "Cliente de Teste",
                "email": f"{uuid.uuid4()}@example.test",
                "document_number": RandomGenerator.generate_cpf(),
            }
            customer = cust_ctrl.create(payload)
            assert customer["name"] == payload["name"]
            assert customer["email"] == payload["email"]
            assert "customer_key" in customer

            # Consulta por chave
            found = cust_ctrl.get_by_key(customer["customer_key"])
            assert found["customer_key"] == customer["customer_key"]

            # Duplicidade de documento deve falhar
            with pytest.raises(DuplicateCustomer):
                cust_ctrl.create({
                    "name": "Outro",
                    "email": f"{uuid.uuid4()}@example.test",
                    "document_number": payload["document_number"],
                })

            # Abertura de conta
            acc_ctrl = AccountController()
            account = acc_ctrl.create({"customer_key": customer["customer_key"]})
            assert account["balance_cents"] == 0
            assert account["transfer_limit_cents"] == 100000
            assert account["blocked_mcc_list"] == ["7995"]

            # Tentativa de abrir 2ª conta para mesmo cliente deve falhar
            with pytest.raises(CustomerAlreadyHasAccount):
                acc_ctrl.create({"customer_key": customer["customer_key"]})

    def test_trusted_contacts_limit(self, db_session):
        mock_ctx = MockContext(db_session)
        with patch("controllers.base_controller.get_context", return_value=mock_ctx):
            cust_ctrl = CustomerController()
            acc_ctrl = AccountController()

            customer = cust_ctrl.create({
                "name": "Pessoa",
                "email": f"{uuid.uuid4()}@test.com",
                "document_number": RandomGenerator.generate_cpf(),
            })
            account = acc_ctrl.create({"customer_key": customer["customer_key"]})
            acc_key = account["account_key"]

            # Adiciona contato 1 e 2
            c1 = acc_ctrl.add_trusted_contact(acc_key, {"name": "C1", "channel": "EMAIL", "address": "c1@test.com"})
            c2 = acc_ctrl.add_trusted_contact(acc_key, {"name": "C2", "channel": "EMAIL", "address": "c2@test.com"})
            assert c1["contact_key"]
            assert c2["contact_key"]

            # 3º contato deve falhar com TrustedContactLimitReached
            with pytest.raises(TrustedContactLimitReached):
                acc_ctrl.add_trusted_contact(acc_key, {"name": "C3", "channel": "EMAIL", "address": "c3@test.com"})


# ─────────────────────────────────────────────────────────────
# 5. Operações Financeiras, Idempotência e Cofre MCC
# ─────────────────────────────────────────────────────────────

class TestFinancialOperations:
    def _mock_reserve(self, session, idempotency_key, request_hash, transaction_type, amount_cents, fee_cents=0, from_account_id=None, to_account_id=None):
        existing = session.query(BankTransaction).filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return existing, False
        tx = BankTransaction(
            transaction_key=uuid.uuid4(),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            type=transaction_type,
            amount_cents=amount_cents,
            fee_cents=fee_cents,
            from_account_id=from_account_id,
            to_account_id=to_account_id,
        )
        session.add(tx)
        session.flush()
        return tx, True

    def test_deposit_and_idempotency_replay(self, db_session):
        mock_ctx = MockContext(db_session)
        with patch("controllers.base_controller.get_context", return_value=mock_ctx):
            cust_ctrl = CustomerController()
            acc_ctrl = AccountController()
            tx_ctrl = TransactionController()

            customer = cust_ctrl.create({
                "name": "Cliente Deposito",
                "email": f"{uuid.uuid4()}@test.com",
                "document_number": RandomGenerator.generate_cpf(),
            })
            account = acc_ctrl.create({"customer_key": customer["customer_key"]})
            acc_key = account["account_key"]

            dep_key = str(uuid.uuid4())
            payload = {"amount_cents": 2500}

            with patch.object(tx_ctrl.repository, "reserve_transaction", side_effect=lambda **kw: self._mock_reserve(db_session, **kw)), \
                 patch.object(tx_ctrl, "_lock_accounts", side_effect=lambda ids: db_session.query(Account).filter(Account.id.in_(ids)).all()):

                # 1ª chamada: 201 Created
                res1, replayed1 = tx_ctrl.deposit(acc_key, dep_key, payload)
                assert not replayed1
                assert res1["balance_cents"] == 2500

                # 2ª chamada (replay com mesma chave e payload): 200 OK com mesmo corpo
                res_replay, replayed2 = tx_ctrl.deposit(acc_key, dep_key, payload)
                assert replayed2
                assert res_replay == res1

                # 3ª chamada (mesma chave com valor modificado): 409 Conflito de Idempotência
                with pytest.raises(IdempotencyConflict):
                    tx_ctrl.deposit(acc_key, dep_key, {"amount_cents": 3000})

                # Extrato reflete o saldo e o lançamento
                orig_execute = db_session.execute
                def safe_execute(stmt, *args, **kwargs):
                    if "SET TRANSACTION" in str(stmt):
                        return MagicMock()
                    return orig_execute(stmt, *args, **kwargs)

                with patch.object(db_session, "execute", side_effect=safe_execute):
                    stmt = tx_ctrl.statement(acc_key, 10, 0)
                assert stmt["balance_cents"] == 2500
                assert len(stmt["data"]) == 1
                assert stmt["data"][0]["kind"] == "DEPOSIT"
                assert stmt["data"][0]["amount_cents"] == 2500

    def test_purchase_mcc_protection_and_key_release(self, db_session):
        mock_ctx = MockContext(db_session)
        with patch("controllers.base_controller.get_context", return_value=mock_ctx):
            cust_ctrl = CustomerController()
            acc_ctrl = AccountController()
            tx_ctrl = TransactionController()

            customer = cust_ctrl.create({
                "name": "Cliente Compra",
                "email": f"{uuid.uuid4()}@test.com",
                "document_number": RandomGenerator.generate_cpf(),
            })
            account = acc_ctrl.create({"customer_key": customer["customer_key"]})
            acc_key = account["account_key"]

            # Cadastra merchant com MCC 7995 (bloqueado por padrão)
            cnpj = RandomGenerator.generate_cnpj()
            merchant = Merchant(document_number=cnpj, name="Cassino Teste", mcc="7995")
            db_session.add(merchant)
            db_session.commit()

            with patch.object(tx_ctrl.repository, "reserve_transaction", side_effect=lambda **kw: self._mock_reserve(db_session, **kw)), \
                 patch.object(tx_ctrl, "_lock_accounts", side_effect=lambda ids: db_session.query(Account).filter(Account.id.in_(ids)).all()):

                # Deposita 1000
                tx_ctrl.deposit(acc_key, str(uuid.uuid4()), {"amount_cents": 1000})

                # Compra com MCC 7995 deve ser bloqueada
                purch_key = str(uuid.uuid4())
                purch_payload = {"amount_cents": 500, "mcc": "5411", "merchant_document_number": cnpj}

                with pytest.raises(BlockedByVault):
                    tx_ctrl.purchase(acc_key, purch_key, purch_payload)
                db_session.rollback()

                # Desbloqueia MCCs da conta
                acc_ctrl.replace_blocked_mccs(acc_key, [])

                # Re-executa compra com a MESMA chave de idempotência (que foi liberada pelo rollback)
                res, replayed = tx_ctrl.purchase(acc_key, purch_key, purch_payload)
                assert not replayed
                assert res["balance_cents"] == 500

    def test_transfer_atomicity_and_tariffs(self, db_session):
        mock_ctx = MockContext(db_session)
        with patch("controllers.base_controller.get_context", return_value=mock_ctx):
            cust_ctrl = CustomerController()
            acc_ctrl = AccountController()
            tx_ctrl = TransactionController()

            c1 = cust_ctrl.create({"name": "Origem", "email": "o@test.com", "document_number": RandomGenerator.generate_cpf()})
            c2 = cust_ctrl.create({"name": "Destino", "email": "d@test.com", "document_number": RandomGenerator.generate_cpf()})
            a1 = acc_ctrl.create({"customer_key": c1["customer_key"]})
            a2 = acc_ctrl.create({"customer_key": c2["customer_key"]})

            with patch.object(tx_ctrl.repository, "reserve_transaction", side_effect=lambda **kw: self._mock_reserve(db_session, **kw)), \
                 patch.object(tx_ctrl, "_lock_accounts", side_effect=lambda ids: db_session.query(Account).filter(Account.id.in_(ids)).all()):

                # Deposita 1000 centavos na conta 1
                tx_ctrl.deposit(a1["account_key"], str(uuid.uuid4()), {"amount_cents": 1000})

                # Cada transferência de 100 centavos cobra 100 centavos de tarifa fixa (total debitado: 200)
                # 5 transferências consomem 1000 centavos
                for _ in range(5):
                    t_res, t_rep = tx_ctrl.transfer(str(uuid.uuid4()), {
                        "from_account_key": a1["account_key"],
                        "to_account_key": a2["account_key"],
                        "amount_cents": 100,
                    })
                    assert not t_rep

                # Saldo destino: 5 x 100 = 500
                acc2_obj = db_session.query(Account).filter_by(account_key=uuid.UUID(a2["account_key"])).first()
                assert acc2_obj.balance_cents == 500

                # 6ª transferência: saldo insuficiente (0 centavos < 200 necessários)
                with pytest.raises(InsufficientFunds):
                    tx_ctrl.transfer(str(uuid.uuid4()), {
                        "from_account_key": a1["account_key"],
                        "to_account_key": a2["account_key"],
                        "amount_cents": 100,
                    })
