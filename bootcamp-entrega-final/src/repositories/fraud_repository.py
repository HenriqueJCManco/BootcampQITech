import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import joinedload

from models import (
    Account,
    BlockedMCC,
    DestinationFlag,
    DestinationReputation,
    DeviceSeen,
    Merchant,
    NotificationOutbox,
    PixAnalysis,
    PixFeedback,
    PixRuleResult,
    TrustedContact,
)


class FraudRepository:
    def __init__(self, session) -> None:
        self.session = session

    def lock_payer(self, source_hash: str) -> None:
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:source_hash))"),
            {"source_hash": source_hash},
        )

    def reserve_analysis(
        self,
        *,
        pix_id: str,
        request_hash: str,
        amount_cents: int,
        transaction_date: datetime,
        source_hash: str,
        destination_key: str,
        value_band: str,
        source_masked: str = "***",
        destination_masked: str = "***",
        source_account_id: int | None = None,
        device_id: str | None = None,
        channel: str | None = None,
        engine_version: str = "v0.1",
        inputs_missing: list | None = None,
    ) -> tuple[PixAnalysis, bool]:
        statement = (
            insert(PixAnalysis)
            .values(
                analysis_key=uuid4(),
                pix_id=pix_id,
                request_hash=request_hash,
                status="pending",
                score=0,
                value_band=value_band,
                amount_cents=amount_cents,
                transaction_date=transaction_date,
                source_account_id=source_account_id,
                source_hash=source_hash,
                source_masked=source_masked or "***",
                destination_key=destination_key,
                destination_masked=destination_masked or "***",
                device_id=device_id,
                channel=channel,
            )
            .on_conflict_do_nothing(index_elements=[PixAnalysis.pix_id])
            .returning(PixAnalysis.id)
        )
        analysis_id = self.session.execute(statement).scalar_one_or_none()

        if analysis_id is not None:
            analysis = self.session.get(PixAnalysis, analysis_id)
            return analysis, True

        analysis = (
            self.session.query(PixAnalysis)
            .options(joinedload(PixAnalysis.rule_results))
            .filter(PixAnalysis.pix_id == pix_id)
            .first()
        )
        return analysis, False

    def get_analysis_by_pix_id(self, pix_id: str) -> PixAnalysis | None:
        return (
            self.session.query(PixAnalysis)
            .options(joinedload(PixAnalysis.rule_results))
            .filter(PixAnalysis.pix_id == pix_id)
            .first()
        )

    def save_rule_results(self, analysis_id: int, rules_fired: list[dict]) -> None:
        for rule in rules_fired:
            rule_entry = PixRuleResult(
                analysis_id=analysis_id,
                rule_code=rule["code"],
                points=rule.get("points", 0),
                evidence=rule.get("evidence", {}),
            )
            self.session.add(rule_entry)

    def notify_trusted_contacts(self, analysis_id: int, account_id: int) -> bool:
        contacts = (
            self.session.query(TrustedContact)
            .filter(TrustedContact.account_id == account_id)
            .all()
        )
        if not contacts:
            return False

        for contact in contacts:
            outbox_entry = NotificationOutbox(
                analysis_id=analysis_id,
                contact_id=contact.id,
                status="PENDING",
            )
            self.session.add(outbox_entry)
        return True

    def save_feedback(self, transaction_id: str, is_fraud: bool, reason: str | None = None) -> PixFeedback:
        feedback = PixFeedback(
            transaction_id=transaction_id,
            is_fraud=is_fraud,
            reason=reason,
        )
        self.session.add(feedback)
        self.session.commit()
        return feedback

    def is_mcc_blocked_for_account(self, account_id: int, mcc: str) -> bool:
        return (
            self.session.query(BlockedMCC)
            .filter(BlockedMCC.account_id == account_id, BlockedMCC.mcc == mcc)
            .first()
            is not None
        )

    def get_destination_flag(self, destination_key: str) -> DestinationFlag | None:
        now = datetime.now(timezone.utc)
        return (
            self.session.query(DestinationFlag)
            .filter(
                DestinationFlag.destination_key == destination_key,
                (DestinationFlag.expires_at.is_(None)) | (DestinationFlag.expires_at > now),
            )
            .first()
        )

    def get_recent_payer_transactions_count(self, source_hash: str, since: datetime) -> int:
        return (
            self.session.query(func.count(PixAnalysis.id))
            .filter(PixAnalysis.source_hash == source_hash, PixAnalysis.transaction_date >= since)
            .scalar()
            or 0
        )
