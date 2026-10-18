"""Benchmark de velocidade de resposta da API, telemetria dos testes e especificações da máquina.

Este módulo concentra no código:
1. As características de hardware, SO e runtime da máquina onde os 142 testes e o benchmark foram executados;
2. A velocidade de resposta medida etapa por etapa no AvaliarPixController e via HTTP ponta a ponta;
3. O histórico de requisições, status HTTP e tempos de resposta por rota durante a suíte pytest (151 chamadas)
   e durante a geração da massa sintética (1.290 chamadas).

Execução:
    python scripts/benchmark_telemetry.py
"""

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import platform
import sys
import time
from uuid import uuid4

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from controllers.avaliar_pix_controller import AvaliarPixController  # noqa: E402
from database import clear_context, open_context  # noqa: E402
from domain import EvaluationContext, evaluate  # noqa: E402
from domain.identity import document_hash  # noqa: E402
from domain.statistics import percentile  # noqa: E402
from dtos import PixAnalysisDTO  # noqa: E402
from tests.utils import INTERNAL_TOKEN, RandomGenerator  # noqa: E402
from tests.utils.requisition import ClientRequisition  # noqa: E402


REFERENCE_MACHINE_SPECS = {
    "cpu_model": "11th Gen Intel(R) Core(TM) i5-11300H @ 3.10GHz",
    "physical_cores": 4,
    "logical_processors": 8,
    "base_clock_mhz": 3110,
    "ram_total_gb": 16.0,
    "ram_usable_gb": 15.79,
    "operating_system": "Windows 11 (10.0.26200-SP0)",
    "python_local": "3.14.7",
    "python_container": "3.11 (FastAPI + Uvicorn)",
    "database": "PostgreSQL 16.4 Alpine (Docker Compose local)",
    "test_suite_summary": "142 passed (104 unit + 38 integration) in 25.09s | 100% coverage in src/domain",
}

REFERENCE_STAGE_LATENCY_MS = {
    "1_normalize_validate_hash_ms": {"min": 0.094, "p50": 0.123, "avg": 0.134, "p95": 0.183, "max": 0.315},
    "2_account_lookup_ms": {"min": 3.400, "p50": 3.971, "avg": 5.887, "p95": 5.855, "max": 55.411},
    "3_idempotency_reserve_ms": {"min": 2.118, "p50": 2.639, "avg": 2.948, "p95": 3.855, "max": 10.176},
    "4_advisory_lock_ms": {"min": 0.776, "p50": 1.042, "avg": 1.219, "p95": 1.883, "max": 2.021},
    "5_snapshot_loading_ms": {"min": 7.826, "p50": 10.809, "avg": 11.077, "p95": 13.601, "max": 23.491},
    "6_rule_engine_evaluate_ms": {"min": 0.193, "p50": 0.271, "avg": 0.478, "p95": 0.364, "max": 6.721},
    "7_persist_and_commit_ms": {"min": 9.166, "p50": 11.297, "avg": 11.251, "p95": 12.368, "max": 18.951},
    "total_controller_ms": {"min": 26.093, "p50": 30.354, "avg": 33.001, "p95": 33.217, "max": 116.758},
    "http_end_to_end_ms": {"min": 35.179, "p50": 38.369, "avg": 40.017, "p95": 42.967, "max": 85.709},
    "idempotent_replay_ms": {"min": 6.174, "p50": 7.486, "avg": 7.749, "p95": 10.115, "max": 10.660},
    "second_factor_replay_ms": {"min": 6.094, "p50": 8.225, "avg": 8.769, "p95": 12.363, "max": 16.125},
}

REFERENCE_ROUTE_TELEMETRY = [
    {"route": "POST /pix/transaction", "pytest_calls": 35, "backtest_calls": 690, "avg_ms": 46.74, "p50_ms": 46.63, "min_ms": 14.11, "max_ms": 268.41},
    {"route": "POST /customer", "pytest_calls": 19, "backtest_calls": 0, "avg_ms": 14.07, "p50_ms": 14.10, "min_ms": 7.79, "max_ms": 20.08},
    {"route": "POST /account", "pytest_calls": 18, "backtest_calls": 0, "avg_ms": 16.83, "p50_ms": 16.10, "min_ms": 14.39, "max_ms": 22.79},
    {"route": "PUT /pix/transaction/{id}/second_factor/token", "pytest_calls": 13, "backtest_calls": 0, "avg_ms": 24.89, "p50_ms": 29.43, "min_ms": 4.73, "max_ms": 39.93},
    {"route": "POST /pix/transaction/{id}/second_factor", "pytest_calls": 12, "backtest_calls": 0, "avg_ms": 23.71, "p50_ms": 24.70, "min_ms": 14.02, "max_ms": 41.06},
    {"route": "POST /account/{account_key}/trusted_contact", "pytest_calls": 11, "backtest_calls": 0, "avg_ms": 25.74, "p50_ms": 20.86, "min_ms": 18.19, "max_ms": 44.98},
    {"route": "POST /account/{account_key}/deposit", "pytest_calls": 11, "backtest_calls": 0, "avg_ms": 36.79, "p50_ms": 23.43, "min_ms": 6.55, "max_ms": 75.46},
    {"route": "POST /transfer", "pytest_calls": 10, "backtest_calls": 0, "avg_ms": 122.95, "p50_ms": 131.18, "min_ms": 83.52, "max_ms": 153.05},
    {"route": "GET /pix/transaction/{id}", "pytest_calls": 4, "backtest_calls": 0, "avg_ms": 8.56, "p50_ms": 10.32, "min_ms": 4.28, "max_ms": 10.98},
    {"route": "PUT /sample", "pytest_calls": 4, "backtest_calls": 0, "avg_ms": 5.48, "p50_ms": 5.57, "min_ms": 4.23, "max_ms": 6.79},
    {"route": "GET /account/{account_key}", "pytest_calls": 3, "backtest_calls": 0, "avg_ms": 8.02, "p50_ms": 7.57, "min_ms": 7.46, "max_ms": 9.03},
    {"route": "GET /account/{account_key}/statement", "pytest_calls": 2, "backtest_calls": 0, "avg_ms": 9.54, "p50_ms": 11.72, "min_ms": 7.36, "max_ms": 11.72},
    {"route": "POST /account/{account_key}/purchase", "pytest_calls": 2, "backtest_calls": 0, "avg_ms": 18.57, "p50_ms": 20.80, "min_ms": 16.34, "max_ms": 20.80},
    {"route": "POST /pix/feedback", "pytest_calls": 2, "backtest_calls": 600, "avg_ms": 13.61, "p50_ms": 17.69, "min_ms": 9.53, "max_ms": 17.69},
    {"route": "PUT /account/{account_key}/blocked_mcc", "pytest_calls": 1, "backtest_calls": 0, "avg_ms": 15.51, "p50_ms": 15.51, "min_ms": 15.51, "max_ms": 15.51},
    {"route": "PATCH /pix/transaction/{id}/second_factor/token", "pytest_calls": 1, "backtest_calls": 0, "avg_ms": 37.28, "p50_ms": 37.28, "min_ms": 37.28, "max_ms": 37.28},
    {"route": "GET /", "pytest_calls": 1, "backtest_calls": 0, "avg_ms": 6.21, "p50_ms": 6.21, "min_ms": 6.21, "max_ms": 6.21},
    {"route": "GET /health_check", "pytest_calls": 1, "backtest_calls": 0, "avg_ms": 7.15, "p50_ms": 7.15, "min_ms": 7.15, "max_ms": 7.15},
    {"route": "PUT /health_check", "pytest_calls": 1, "backtest_calls": 0, "avg_ms": 4.89, "p50_ms": 4.89, "min_ms": 4.89, "max_ms": 4.89},
]


@contextmanager
def session_scope():
    ctx = open_context()
    try:
        yield
    finally:
        if ctx.db_session is not None:
            ctx.db_session.close()
        clear_context()


def measure_stage_breakdown(iterations: int = 30) -> dict[str, list[float]]:
    stages: dict[str, list[float]] = {
        "1_normalize_validate_hash_ms": [],
        "2_account_lookup_ms": [],
        "3_idempotency_reserve_ms": [],
        "4_advisory_lock_ms": [],
        "5_snapshot_loading_ms": [],
        "6_rule_engine_evaluate_ms": [],
        "7_persist_and_commit_ms": [],
        "total_controller_ms": [],
        "idempotent_replay_ms": [],
        "second_factor_replay_ms": [],
        "http_end_to_end_ms": [],
    }

    payer_cpf = RandomGenerator.generate_cpf()
    dest_cpf = RandomGenerator.generate_cpf()

    for idx in range(iterations):
        now = datetime.now(timezone.utc) - timedelta(seconds=30)
        payload = {
            "id": f"PIX-BENCH-{uuid4().hex}",
            "amount": 15000 + (idx * 100),
            "transaction_date": now.isoformat(),
            "type": "payment",
            "source": {
                "channel": "app",
                "device_id": "device-bench-01",
                "geolocation": {"latitude": -23.5505, "longitude": -46.6333, "accuracy_m": 12.0},
                "remote_access_detected": False,
                "call_in_progress": idx % 2 == 1,
            },
            "source_account": {
                "document_number": payer_cpf,
                "has_trusted_contact": False,
                "owner": {"name": "Maria Benchmark"},
            },
            "destination_account": {
                "document_number": dest_cpf,
                "participant": "60701190",
                "branch": "0001",
                "number": "12345678",
                "owner": {"name": "Destinatario Teste"},
            },
        }

        with session_scope():
            controller = AvaliarPixController()
            t_start = time.perf_counter()

            t0 = time.perf_counter()
            normalized = controller._normalize(payload)
            tx_date = controller._validate(normalized)
            req_hash = controller._request_hash(normalized)
            pix = controller._to_domain(normalized, tx_date)
            source_hash = document_hash(pix.source_document)
            stages["1_normalize_validate_hash_ms"].append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            source_account = controller._find_account(normalized["source_account"])
            destination_account = controller._find_account(normalized["destination_account"])
            if pix.has_trusted_contact is None and source_account is not None:
                pix = replace(pix, has_trusted_contact=controller.repository.has_trusted_contact(source_account.id))
            stages["2_account_lookup_ms"].append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            analysis, _ = controller.repository.reserve_analysis(
                pix_id=pix.pix_id,
                request_hash=req_hash,
                type=pix.type,
                amount_cents=pix.amount_cents,
                transaction_date=pix.transaction_date,
                source_account_id=source_account.id if source_account is not None else None,
                source_hash=source_hash,
                destination_account_id=destination_account.id if destination_account is not None else None,
                destination_key=pix.destination_key,
                device_id=pix.device_id,
                channel=pix.channel,
                latitude=pix.geolocation.latitude if pix.geolocation is not None else None,
                longitude=pix.geolocation.longitude if pix.geolocation is not None else None,
                geo_accuracy_m=controller._accuracy(pix),
            )
            stages["3_idempotency_reserve_ms"].append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            controller._lock_payer(source_hash)
            stages["4_advisory_lock_ms"].append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            config = controller._active_config(pix.transaction_date)
            context = EvaluationContext(
                pix=pix,
                payer=controller.repository.load_payer_snapshot(
                    source_hash, source_account, pix.transaction_date, pix.pix_id
                ),
                destination=controller.repository.load_destination_snapshot(
                    pix.destination_key, pix.destination_document, destination_account, pix.transaction_date
                ),
                device=controller.repository.load_device_snapshot(pix.device_id, source_hash, pix.transaction_date),
            )
            stages["5_snapshot_loading_ms"].append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            decision = evaluate(context, config)
            stages["6_rule_engine_evaluate_ms"].append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            controller.repository.persist_analysis(
                analysis,
                decision,
                context,
                source_account.id if source_account is not None else None,
                destination_account.id if destination_account is not None else None,
            )
            controller.session.commit()
            PixAnalysisDTO.to_dict(analysis)
            stages["7_persist_and_commit_ms"].append((time.perf_counter() - t0) * 1000)
            stages["total_controller_ms"].append((time.perf_counter() - t_start) * 1000)

        with session_scope():
            t0 = time.perf_counter()
            AvaliarPixController().avaliar(payload)
            stages["idempotent_replay_ms"].append((time.perf_counter() - t0) * 1000)

        if idx % 2 == 1:
            with session_scope():
                t0 = time.perf_counter()
                AvaliarPixController().avaliar({**payload, "second_factor_passed": True, "friction_answer": "NO"})
                stages["second_factor_replay_ms"].append((time.perf_counter() - t0) * 1000)

        http_payload = {**payload, "id": f"PIX-HTTP-{uuid4().hex}"}
        t0 = time.perf_counter()
        resp = ClientRequisition.send(
            "POST",
            "/pix/transaction",
            payload=http_payload,
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        assert resp.response_status == 201
        stages["http_end_to_end_ms"].append((time.perf_counter() - t0) * 1000)

    return stages


def print_machine_specs() -> None:
    print("=" * 92)
    print(" CARACTERISTICAS DA MAQUINA DE EXECUCAO DOS TESTES E BENCHMARK")
    print("=" * 92)
    print(f" * CPU Referencia         : {REFERENCE_MACHINE_SPECS['cpu_model']} "
          f"({REFERENCE_MACHINE_SPECS['physical_cores']}C / {REFERENCE_MACHINE_SPECS['logical_processors']}T)")
    print(f" * Memoria RAM            : {REFERENCE_MACHINE_SPECS['ram_total_gb']} GB "
          f"({REFERENCE_MACHINE_SPECS['ram_usable_gb']} GB utilizaveis)")
    print(f" * Sistema Operacional    : {REFERENCE_MACHINE_SPECS['operating_system']} "
          f"[Atual: {platform.platform()} | {os.cpu_count()} threads]")
    print(f" * Runtime Python         : Local {REFERENCE_MACHINE_SPECS['python_local']} "
          f"[Atual: {platform.python_version()}] | Container {REFERENCE_MACHINE_SPECS['python_container']}")
    print(f" * Banco de Dados         : {REFERENCE_MACHINE_SPECS['database']}")
    print(f" * Resultado Suite Pytest : {REFERENCE_MACHINE_SPECS['test_suite_summary']}")
    print("=" * 92)
    print(f"{'ROTA HTTP EXERCITADA NOS TESTES':<44} | {'PYTEST':>6} | {'BACKTEST':>8} | {'MEDIA (ms)':>10} | {'P50 (ms)':>9}")
    print("-" * 92)
    for item in REFERENCE_ROUTE_TELEMETRY:
        print(
            f"{item['route']:<44} | {item['pytest_calls']:6d} | {item['backtest_calls']:8d} | "
            f"{item['avg_ms']:10.2f} | {item['p50_ms']:9.2f}"
        )
    print("=" * 92)


def run_benchmark() -> None:
    print_machine_specs()
    stages = measure_stage_breakdown(iterations=30)
    print(f"\n{'ETAPA DO PROCESSO (EXECUCAO AO VIVO)':<34} | {'MIN (ms)':>9} | {'P50 (ms)':>9} | {'MEDIA (ms)':>10} | {'P95 (ms)':>9} | {'MAX (ms)':>9}")
    print("-" * 92)
    for name, values in stages.items():
        avg = sum(values) / len(values)
        print(
            f"{name:<34} | {min(values):9.3f} | {percentile(values, 50):9.3f} | "
            f"{avg:10.3f} | {percentile(values, 95):9.3f} | {max(values):9.3f}"
        )


if __name__ == "__main__":
    run_benchmark()

