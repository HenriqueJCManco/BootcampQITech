import hashlib
import json
import re
from datetime import datetime, timezone, timedelta

from controllers.base_controller import BaseController
from dtos import PixAnalysisDTO
from errors import (
    PixAnalysisNotFound,
    PixIdempotencyConflict,
    PixInvalidAmount,
    PixInvalidChannel,
    PixInvalidDocument,
    PixInvalidTransactionDate,
)
from models.fraud import PixAnalysis
from repositories import FraudRepository
from utils.document_number import is_valid_cpf, is_valid_cnpj, is_valid_document_number, mask_document


VALID_CHANNELS = {"internet", "celular", "computador", "tablet", "relogio"}
NIGHT_LIMIT_CENTS = 100000  # R$ 1.000,00


class AvaliarPixController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = FraudRepository(self.session)

    @staticmethod
    def _request_hash(payload: dict) -> str:
        # A prova de 2FA não entra no request_hash
        sanitized = dict(payload)
        sanitized.pop("second_factor_passed", None)
        canonical = json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def avaliar(self, payload: dict) -> tuple[dict, bool]:
        pix_id = payload["id"]
        amount_cents = payload["amount"]
        if not isinstance(amount_cents, int) or amount_cents < 1:
            raise PixInvalidAmount()

        tx_date = self._parse_and_validate_date(payload["transaction_date"])

        # Valida documentos se presentes
        self._validate_documents(payload)

        # Valida canal se presente
        source = payload.get("source") or {}
        channel = source.get("channel")
        if channel is not None and channel not in VALID_CHANNELS:
            raise PixInvalidChannel()

        request_hash = self._request_hash(payload)
        source_account = payload.get("source_account") or {}
        dest_account = payload.get("destination_account") or {}

        source_doc = source_account.get("document_number") or ""
        source_hash = hashlib.sha256(source_doc.encode("utf-8")).hexdigest() if source_doc else hashlib.sha256(pix_id.encode("utf-8")).hexdigest()
        dest_doc = dest_account.get("document_number") or ""
        destination_key = hashlib.sha256(dest_doc.encode("utf-8")).hexdigest() if dest_doc else "unknown_destination"

        value_band = self._determine_value_band(amount_cents)

        # 1. Reserva de Idempotência
        analysis, is_new = self.repository.reserve_analysis(
            pix_id=pix_id,
            request_hash=request_hash,
            amount_cents=amount_cents,
            transaction_date=tx_date,
            source_hash=source_hash,
            destination_key=destination_key,
            source_masked=mask_document(source_doc),
            destination_masked=mask_document(dest_doc),
            value_band=value_band,
            device_id=source.get("device_id"),
            channel=channel,
        )

        if not is_new:
            if analysis.request_hash != request_hash:
                raise PixIdempotencyConflict()

            # Fluxo de 2FA concluído
            if payload.get("second_factor_passed") is True and analysis.status == "two_factor_required":
                analysis.status = "approved"
                analysis.second_factor_at = datetime.now(timezone.utc)
                self.session.commit()

            return PixAnalysisDTO.to_dict(analysis), True

        # 2. Trava de linha por pagador
        self.repository.lock_payer(source_hash)

        # 3. Execução das Regras e Cálculo de Score
        rules_fired = []
        score = 0
        floor_applied = None
        status = "approved"
        challenge_type = None
        friction_script_key = None
        customer_message_key = None
        payer_class = self._determine_payer_class(source_account)

        # Regras Eliminatórias (E1 a E4)
        mcc = dest_account.get("mcc")
        if mcc and mcc == "7995":
            rules_fired.append({"code": "E1", "points": 0, "evidence": {"mcc": mcc, "reason": "blocked_mcc"}})
            status = "rejected"
            customer_message_key = "BLOCKED_FOR_SAFETY"

        dest_flag = self.repository.get_destination_flag(destination_key)
        if dest_flag and dest_flag.status == "MARCADA" and payload.get("type") != "refund":
            rules_fired.append({"code": "E2", "points": 0, "evidence": {"status": "MARCADA"}})
            status = "rejected"
            customer_message_key = "BLOCKED_FOR_SAFETY"

        if dest_flag and dest_flag.status == "QUARENTENA":
            rules_fired.append({"code": "E3", "points": 0, "evidence": {"status": "QUARENTENA"}})
            status = "rejected"
            customer_message_key = "BLOCKED_FOR_SAFETY"

        # E4: Limite noturno para PF ou MEI
        if status != "rejected" and payer_class in ("PF", "MEI"):
            hour = tx_date.hour
            is_night = hour >= 20 or hour < 6
            if is_night and amount_cents > NIGHT_LIMIT_CENTS:
                rules_fired.append({
                    "code": "E4",
                    "points": 0,
                    "evidence": {"amount_cents": amount_cents, "limit_cents": NIGHT_LIMIT_CENTS, "hour": hour},
                })
                status = "rejected"
                customer_message_key = "BLOCKED_FOR_SAFETY"

        # Regras de Pontuação Comportamental (se não rejeitado por eliminatória)
        if status != "rejected":
            # R1: Acesso remoto ou ligação em andamento
            if source.get("remote_access_detected") is True:
                score += 30
                rules_fired.append({"code": "R1", "points": 30, "evidence": {"remote_access": True}})
                floor_applied = "R1"
            if source.get("call_in_progress") is True:
                score += 30
                rules_fired.append({"code": "R1", "points": 30, "evidence": {"call_in_progress": True}})
                floor_applied = "R1"

            # K2: Relógio com valor acima de R$ 200,00
            if channel == "relogio" and amount_cents > 20000:
                rules_fired.append({"code": "K2", "points": 0, "evidence": {"channel": "relogio", "amount_cents": amount_cents}})
                floor_applied = "K2"

            # V1: Rajada de Pix nos últimos 10 minutos
            since_10m = tx_date - timedelta(minutes=10)
            recent_count = self.repository.get_recent_payer_transactions_count(source_hash, since_10m)
            if recent_count >= 5:
                score += 40
                rules_fired.append({"code": "V1", "points": 40, "evidence": {"count_10m": recent_count}})
            elif recent_count >= 3:
                score += 25
                rules_fired.append({"code": "V1", "points": 25, "evidence": {"count_10m": recent_count}})

            # C1: Beneficiário novo
            score += 15
            rules_fired.append({"code": "C1", "points": 15, "evidence": {"is_new_recipient": True}})

            # Pisos e Decisão por Faixa de Valor
            thresholds = self._get_thresholds(value_band)
            if score >= thresholds["reject"]:
                status = "rejected"
                customer_message_key = "BLOCKED_FOR_SAFETY"
            elif score >= thresholds["two_factor"] or floor_applied is not None:
                status = "two_factor_required"
                customer_message_key = "CONFIRM_IDENTITY"

                # 2FA Social & Quebra de Feitiço
                if source.get("call_in_progress") is True:
                    challenge_type = "TRUSTED_CONTACT_APPROVAL"
                    friction_script_key = "CALL_COACHING_CHECK"
                else:
                    challenge_type = "BIOMETRIC_2FA"
                    friction_script_key = "CONFIRM_IDENTITY"

        # 4. Atualização e Persistência do resultado
        has_trusted_contact = bool(source_account.get("has_trusted_contact"))
        notify_trusted_contact = has_trusted_contact and status in ("two_factor_required", "rejected")

        analysis.status = status
        analysis.score = score
        analysis.challenge_type = challenge_type
        analysis.friction_script_key = friction_script_key
        analysis.notify_trusted_contact = notify_trusted_contact
        analysis.customer_message_key = customer_message_key

        # Anexa dados transitórios para o DTO
        analysis._floor_applied = floor_applied
        analysis._payer_class = payer_class
        analysis._destination_status = dest_flag.status if dest_flag else "NORMAL"

        self.repository.save_rule_results(analysis.id, rules_fired)

        if notify_trusted_contact and analysis.source_account_id:
            self.repository.notify_trusted_contacts(analysis.id, analysis.source_account_id)

        self.session.commit()
        return PixAnalysisDTO.to_dict(analysis), False

    def get_by_id(self, pix_id: str) -> dict:
        analysis = self.repository.get_analysis_by_pix_id(pix_id)
        if analysis is None:
            raise PixAnalysisNotFound()
        return PixAnalysisDTO.to_dict(analysis)

    def register_feedback(self, payload: dict) -> dict:
        feedback = self.repository.save_feedback(
            transaction_id=payload["transaction_id"],
            is_fraud=payload["is_fraud"],
            reason=payload.get("reason"),
        )
        return {
            "id": feedback.id,
            "transaction_id": feedback.transaction_id,
            "is_fraud": feedback.is_fraud,
            "reason": feedback.reason,
            "created_at": feedback.created_at.isoformat(),
        }

    def _parse_and_validate_date(self, date_str: str) -> datetime:
        try:
            dt = datetime.fromisoformat(date_str)
        except Exception:
            raise PixInvalidTransactionDate("timezone")

        if dt.tzinfo is None:
            raise PixInvalidTransactionDate("timezone")

        now = datetime.now(timezone.utc)
        if dt > now + timedelta(minutes=5):
            raise PixInvalidTransactionDate("future")

        return dt

    def _validate_documents(self, payload: dict) -> None:
        source_account = payload.get("source_account") or {}
        src_doc = source_account.get("document_number")
        if src_doc and not is_valid_document_number(src_doc):
            raise PixInvalidDocument("source_account.document_number")

        dest_account = payload.get("destination_account") or {}
        dest_doc = dest_account.get("document_number")
        if dest_doc and not is_valid_document_number(dest_doc):
            raise PixInvalidDocument("destination_account.document_number")

    def _determine_value_band(self, amount_cents: int) -> str:
        if amount_cents <= 20000:
            return "A"
        if amount_cents <= 100000:
            return "B"
        if amount_cents <= 500000:
            return "C"
        return "D"

    def _get_thresholds(self, value_band: str) -> dict:
        thresholds_map = {
            "A": {"two_factor": 45, "reject": 85},
            "B": {"two_factor": 35, "reject": 75},
            "C": {"two_factor": 30, "reject": 65},
            "D": {"two_factor": 25, "reject": 55},
        }
        return thresholds_map.get(value_band, {"two_factor": 30, "reject": 65})

    def _determine_payer_class(self, source_account: dict) -> str:
        doc = source_account.get("document_number") or ""
        digits = re.sub(r"\D", "", doc)
        if len(digits) == 11:
            return "PF"
        if len(digits) == 14:
            owner = source_account.get("owner") or {}
            name = (owner.get("name") or "").upper().strip()
            # Vetos de PJ real
            if any(suf in name for suf in ("LTDA", "EIRELI", "SLU", "EPP", "S/A", "S.A.")):
                return "PJ"
            # Reconhecimento MEI: CPF no fim do nome
            match = re.search(r"(\d{11})$", name)
            if match and is_valid_cpf(match.group(1)):
                return "MEI"
            return "PJ"
        return "PF"
