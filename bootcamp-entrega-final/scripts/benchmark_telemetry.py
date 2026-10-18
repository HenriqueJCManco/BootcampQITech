import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from contextlib import contextmanager
from controllers.avaliar_pix_controller import AvaliarPixController
from database import clear_context, open_context
from domain import EvaluationContext, evaluate
from domain.identity import document_hash, mask_document
from domain.statistics import percentile
from dtos import PixAnalysisDTO
from tests.utils import INTERNAL_TOKEN, RandomGenerator
from tests.utils.requisition import ClientRequisition


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
                source_masked=mask_document(pix.source_document),
                destination_account_id=destination_account.id if destination_account is not None else None,
                destination_key=pix.destination_key,
                destination_masked=mask_document(pix.destination_document),
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


def run_benchmark() -> None:
    stages = measure_stage_breakdown(iterations=30)
    print(f"{'ETAPA DO PROCESSO':<34} | {'MIN (ms)':>9} | {'P50 (ms)':>9} | {'MEDIA (ms)':>10} | {'P95 (ms)':>9} | {'MAX (ms)':>9}")
    print("-" * 92)
    for name, values in stages.items():
        avg = sum(values) / len(values)
        print(
            f"{name:<34} | {min(values):9.3f} | {percentile(values, 50):9.3f} | "
            f"{avg:10.3f} | {percentile(values, 95):9.3f} | {max(values):9.3f}"
        )


if __name__ == "__main__":
    run_benchmark()
