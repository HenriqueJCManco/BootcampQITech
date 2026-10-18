import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from controllers.base_controller import BaseController
from domain import (
    APPROVED,
    REJECTED,
    TWO_FACTOR_REQUIRED,
    EngineConfig,
    EvaluationContext,
    Geolocation,
    Interaction,
    PixRequest,
    apply_second_factor,
    evaluate,
)
from domain.engine import BLOCKED_FOR_SAFETY
from domain.identity import destination_key, document_hash, mask_document, only_digits
from dtos import PixAnalysisDTO
from errors import (
    PixAnalysisNotFound,
    PixIdempotencyConflict,
    PixInvalidAmount,
    PixInvalidDocument,
    PixInvalidTransactionDate,
    PixLockTimeout,
)
from models import Account
from repositories import FraudRepository
from utils.document_number import is_valid_document_number


CHANNEL_ALIASES = {"app": "celular"}
HASH_EXCLUDED_FIELDS = ("second_factor_passed", "friction_answer")
MAX_FUTURE = timedelta(minutes=5)
LOCK_TIMEOUT = "2s"
OWN_PARTICIPANT = "BANCO60"
OWN_BRANCH = "0001"
ESCALATION_RULE = "ESCALATION"


class AvaliarPixController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = FraudRepository(self.session)

    def avaliar(self, payload: dict) -> tuple[dict, bool]:
        payload = self._normalize(payload)
        transaction_date = self._validate(payload)
        request_hash = self._request_hash(payload)

        source_account = self._find_account(payload["source_account"])
        destination_account = self._find_account(payload["destination_account"])
        pix = self._to_domain(payload, transaction_date)
        if pix.has_trusted_contact is None and source_account is not None:
            pix = replace(pix, has_trusted_contact=self.repository.has_trusted_contact(source_account.id))

        source_hash = document_hash(pix.source_document)
        analysis, is_new = self.repository.reserve_analysis(
            pix_id=pix.pix_id,
            request_hash=request_hash,
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
            geo_accuracy_m=self._accuracy(pix),
        )

        if not is_new:
            if analysis.request_hash != request_hash:
                raise PixIdempotencyConflict()
            return self._replay(analysis, payload), True

        self._lock_payer(source_hash)
        config = self._active_config(pix.transaction_date)
        context = EvaluationContext(
            pix=pix,
            payer=self.repository.load_payer_snapshot(source_hash, source_account, pix.transaction_date, pix.pix_id),
            destination=self.repository.load_destination_snapshot(
                pix.destination_key, pix.destination_document, destination_account, pix.transaction_date
            ),
            device=self.repository.load_device_snapshot(pix.device_id, source_hash, pix.transaction_date),
        )
        decision = evaluate(context, config)
        self.repository.persist_analysis(
            analysis,
            decision,
            context,
            source_account.id if source_account is not None else None,
            destination_account.id if destination_account is not None else None,
        )
        self.session.commit()
        return PixAnalysisDTO.to_dict(analysis), False

    def get_by_id(self, pix_id: str) -> dict:
        analysis = self.repository.get_analysis_by_pix_id(pix_id)
        if analysis is None or analysis.status is None:
            raise PixAnalysisNotFound()
        return PixAnalysisDTO.to_dict(analysis)

    def register_feedback(self, payload: dict) -> dict:
        if self.repository.get_analysis_by_pix_id(payload["transaction_id"]) is None:
            raise PixAnalysisNotFound()
        feedback = self.repository.add_feedback(payload["transaction_id"], payload["is_fraud"], payload.get("reason"))
        self.session.commit()
        return {
            "id": feedback.id,
            "transaction_id": feedback.transaction_id,
            "is_fraud": feedback.is_fraud,
            "reason": feedback.reason,
            "created_at": feedback.created_at.isoformat(),
        }

    def _replay(self, analysis, payload: dict) -> dict:
        if not payload.get("second_factor_passed") or analysis.status != TWO_FACTOR_REQUIRED:
            return PixAnalysisDTO.to_dict(analysis)
        if analysis.second_factor_at is not None:
            return PixAnalysisDTO.to_dict(analysis)

        config_row = self.repository.get_config(analysis.engine_version)
        config = EngineConfig(version=config_row.version, params=config_row.params)
        has_consented_contact = analysis.source_account_id is not None and self.repository.has_consented_contact(
            analysis.source_account_id
        )
        answer = payload.get("friction_answer")
        status, challenge_type = apply_second_factor(
            analysis.status, analysis.friction_script_key, answer, has_consented_contact, config
        )

        now = datetime.now(timezone.utc)
        if answer is not None:
            self.repository.record_friction_answer(analysis, answer, now)
        if status == APPROVED:
            self.repository.mark_second_factor(analysis, now)
        else:
            self.repository.add_rule_result(
                analysis,
                ESCALATION_RULE,
                {"from": analysis.status, "to": status, "friction_answer": answer, "challenge_type": challenge_type},
            )

        metadata = dict(analysis.metadata_)
        if status == APPROVED:
            metadata["customer_message_key"] = None
        elif status == REJECTED:
            metadata["customer_message_key"] = BLOCKED_FOR_SAFETY
        if challenge_type is not None:
            analysis.challenge_type = challenge_type
            metadata["challenge_type"] = challenge_type
        analysis.status = status
        analysis.metadata_ = metadata
        self.session.commit()
        return PixAnalysisDTO.to_dict(analysis)

    @staticmethod
    def _normalize(payload: dict) -> dict:
        source = payload.get("source")
        if not source or source.get("channel") not in CHANNEL_ALIASES:
            return payload
        return {**payload, "source": {**source, "channel": CHANNEL_ALIASES[source["channel"]]}}

    @staticmethod
    def _validate(payload: dict) -> datetime:
        amount = payload["amount"]
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
            raise PixInvalidAmount()

        try:
            transaction_date = datetime.fromisoformat(payload["transaction_date"])
        except ValueError:
            raise PixInvalidTransactionDate("format") from None
        if transaction_date.tzinfo is None:
            raise PixInvalidTransactionDate("timezone")
        if transaction_date > datetime.now(timezone.utc) + MAX_FUTURE:
            raise PixInvalidTransactionDate("not_future")

        for field in ("source_account", "destination_account"):
            if not is_valid_document_number(payload[field]["document_number"]):
                raise PixInvalidDocument(f"{field}.document_number")

        return transaction_date

    @staticmethod
    def _request_hash(payload: dict) -> str:
        body = {key: value for key, value in payload.items() if key not in HASH_EXCLUDED_FIELDS}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"/pix/transaction\n{canonical}".encode("utf-8")).hexdigest()

    def _find_account(self, data: dict) -> Account | None:
        account_key = data.get("account_key")
        if account_key is not None:
            account = self.session.query(Account).filter(Account.account_key == UUID(account_key)).first()
            if account is not None:
                return account
        return self.repository.get_account_by_document(only_digits(data["document_number"]))

    @staticmethod
    def _to_domain(payload: dict, transaction_date: datetime) -> PixRequest:
        source = payload.get("source") or {}
        source_account = payload["source_account"]
        destination = payload["destination_account"]

        geolocation = None
        if source.get("geolocation") is not None:
            point = source["geolocation"]
            geolocation = Geolocation(point["latitude"], point["longitude"], point.get("accuracy_m"))
        interaction = None
        if source.get("interaction") is not None:
            raw = source["interaction"]
            interaction = Interaction(
                raw=raw,
                is_robotic_movement=raw.get("is_robotic_movement"),
                typing_cadence_std_ms=raw.get("typing_cadence_std_ms"),
                session_idle_then_burst=raw.get("session_idle_then_burst"),
            )

        destination_document = only_digits(destination["document_number"])
        return PixRequest(
            pix_id=payload["id"],
            amount_cents=payload["amount"],
            transaction_date=transaction_date,
            source_document=only_digits(source_account["document_number"]),
            destination_document=destination_document,
            destination_key=destination_key(
                destination.get("participant", OWN_PARTICIPANT),
                destination.get("branch", OWN_BRANCH),
                destination.get("number") or destination.get("account_key", ""),
                destination_document,
            ),
            type=payload.get("type", "payment"),
            source_name=(source_account.get("owner") or {}).get("name"),
            channel=source.get("channel"),
            device_id=source.get("device_id"),
            geolocation=geolocation,
            remote_access_detected=source.get("remote_access_detected"),
            call_in_progress=source.get("call_in_progress"),
            has_trusted_contact=source_account.get("has_trusted_contact"),
            interaction=interaction,
        )

    @staticmethod
    def _accuracy(pix: PixRequest) -> int | None:
        if pix.geolocation is None or pix.geolocation.accuracy_m is None:
            return None
        return round(pix.geolocation.accuracy_m)

    def _lock_payer(self, source_hash: str) -> None:
        try:
            self.session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
            self.repository.lock_payer(source_hash)
        except DBAPIError as error:
            sqlstate = getattr(error.orig, "pgcode", None) or getattr(error.orig, "sqlstate", None)
            if sqlstate == "55P03":
                raise PixLockTimeout() from error
            raise

    def _active_config(self, at: datetime) -> EngineConfig:
        row = self.repository.get_active_config(at)
        if row is None:
            raise RuntimeError("fraude.engine_config has no version active for this date.")
        return EngineConfig(version=row.version, params=row.params)
