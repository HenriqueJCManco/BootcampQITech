from datetime import datetime, timedelta

from sqlalchemy import and_, exists, func, literal, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from domain import (
    APPROVED,
    REJECTED,
    TWO_FACTOR_REQUIRED,
    Decision,
    DestinationFlag,
    DestinationReputation,
    DestinationSnapshot,
    DeviceSnapshot,
    EvaluationContext,
    FlagChange,
    Geolocation,
    MoneyMovement,
    OpenFinanceProfile,
    PastPix,
    PayerSnapshot,
)
from models import (
    Account,
    BankTransaction,
    BlockedMCC,
    Customer,
    DestinationFlagModel,
    DestinationReputationModel,
    DeviceSeenModel,
    EngineConfigModel,
    LedgerEntry,
    Merchant,
    NotificationOutbox,
    OfPayerProfileModel,
    PixAnalysisModel,
    PixFeedbackModel,
    PixRuleResultModel,
    PixShadowResultModel,
    TrustedContact,
)


HISTORY_DAYS = 125


def digits_only(column):
    return func.regexp_replace(column, "[^0-9]", "", "g")


BLOCKED_PIX_QUERY = text(
    """
    SELECT
        o.id AS outbox_id,
        o.contact_id,
        o.status AS outbox_status,
        o.created_at AS notified_at,
        a.pix_id,
        a.status,
        a.channel,
        a.amount_cents,
        a.score,
        a.value_band,
        a.challenge_type,
        a.friction_script_key,
        a.metadata -> 'rules_fired' AS rules_fired,
        r.rules_metadata
    FROM notification_outbox o
    JOIN fraude.pix_analysis a ON a.id = o.analysis_id
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(
                 jsonb_build_object('rule', rr.rule_code, 'points', rr.points, 'evidence', rr.evidence)
                 ORDER BY rr.id
               ) AS rules_metadata
        FROM fraude.pix_rule_result rr
        WHERE rr.analysis_id = a.id
    ) r ON true
    WHERE o.transaction_id IS NULL
    ORDER BY o.created_at DESC, o.id DESC
    LIMIT :limit OFFSET :offset
    """
)


class FraudRepository:
    def __init__(self, session) -> None:
        self.session = session

    def get_active_config(self, at: datetime) -> EngineConfigModel | None:
        return (
            self.session.query(EngineConfigModel)
            .filter(EngineConfigModel.active_from <= at)
            .order_by(EngineConfigModel.active_from.desc(), EngineConfigModel.version.desc())
            .first()
        )

    def get_config(self, version: int) -> EngineConfigModel | None:
        return self.session.get(EngineConfigModel, version)

    def get_account_by_document(self, document_number: str) -> Account | None:
        return (
            self.session.query(Account)
            .join(Customer, Customer.id == Account.customer_id)
            .filter(digits_only(Customer.document_number) == digits_only(literal(document_number)))
            .first()
        )

    def reserve_analysis(self, **fields) -> tuple[PixAnalysisModel, bool]:
        statement = (
            insert(PixAnalysisModel)
            .values(**fields)
            .on_conflict_do_nothing(index_elements=[PixAnalysisModel.pix_id])
            .returning(PixAnalysisModel.id)
        )
        analysis_id = self.session.execute(statement).scalar_one_or_none()

        if analysis_id is not None:
            return self.session.get(PixAnalysisModel, analysis_id), True
        return self.get_analysis_by_pix_id(fields["pix_id"]), False

    def get_analysis_by_pix_id(self, pix_id: str) -> PixAnalysisModel | None:
        return (
            self.session.query(PixAnalysisModel)
            .options(selectinload(PixAnalysisModel.rule_results))
            .filter(PixAnalysisModel.pix_id == pix_id)
            .first()
        )

    def lock_payer(self, source_hash: str) -> None:
        lock_key = int(source_hash[:15], 16)
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

    def load_payer_snapshot(
        self,
        source_hash: str,
        account: Account | None,
        at: datetime,
        exclude_pix_id: str,
    ) -> PayerSnapshot:
        history = self._payer_history(source_hash, at - timedelta(days=HISTORY_DAYS), at, exclude_pix_id)
        if account is None:
            amount_history = tuple(
                MoneyMovement(pix.transaction_date, pix.amount_cents)
                for pix in history
                if pix.status != REJECTED
            )
            return PayerSnapshot(source_hash=source_hash, history=history, amount_history=amount_history)

        return PayerSnapshot(
            source_hash=source_hash,
            history=history,
            amount_history=self._ledger_movements(account.id, "DEBIT", "TRANSFER", at - timedelta(days=HISTORY_DAYS), at),
            deposits=self._ledger_movements(account.id, "CREDIT", "DEPOSIT", at - timedelta(days=HISTORY_DAYS), at),
            account_created_at=account.created_at,
            balance_cents=account.balance_cents,
            blocked_mccs=frozenset(self._blocked_mccs(account.id)),
            has_consented_trusted_contact=self.has_consented_contact(account.id),
            open_finance=self._open_finance_profile(account.id),
        )

    def _payer_history(
        self, source_hash: str, since: datetime, until: datetime, exclude_pix_id: str
    ) -> tuple[PastPix, ...]:
        completed = exists().where(BankTransaction.idempotency_key == PixAnalysisModel.pix_id)
        rows = (
            self.session.query(PixAnalysisModel, completed.label("has_transaction"))
            .filter(
                PixAnalysisModel.source_hash == source_hash,
                PixAnalysisModel.transaction_date >= since,
                PixAnalysisModel.transaction_date <= until,
                PixAnalysisModel.pix_id != exclude_pix_id,
                PixAnalysisModel.status.isnot(None),
            )
            .order_by(PixAnalysisModel.transaction_date)
            .all()
        )
        return tuple(self._to_past_pix(analysis, has_transaction) for analysis, has_transaction in rows)

    @staticmethod
    def _to_past_pix(analysis: PixAnalysisModel, has_transaction: bool) -> PastPix:
        geolocation = None
        if analysis.latitude is not None:
            geolocation = Geolocation(analysis.latitude, analysis.longitude)
        standalone_approved = analysis.source_account_id is None and analysis.status == APPROVED
        return PastPix(
            transaction_date=analysis.transaction_date,
            amount_cents=analysis.amount_cents,
            destination_key=analysis.destination_key,
            status=analysis.status,
            completed=bool(has_transaction) or standalone_approved,
            device_id=analysis.device_id,
            channel=analysis.channel,
            geolocation=geolocation,
        )

    def _ledger_movements(
        self, account_id: int, direction: str, kind: str, since: datetime, until: datetime
    ) -> tuple[MoneyMovement, ...]:
        rows = (
            self.session.query(LedgerEntry.entry_datetime, LedgerEntry.amount_cents)
            .filter(
                LedgerEntry.account_id == account_id,
                LedgerEntry.direction == direction,
                LedgerEntry.kind == kind,
                LedgerEntry.entry_datetime >= since,
                LedgerEntry.entry_datetime <= until,
            )
            .order_by(LedgerEntry.entry_datetime)
            .all()
        )
        return tuple(MoneyMovement(occurred_at, amount) for occurred_at, amount in rows)

    def _blocked_mccs(self, account_id: int) -> list[str]:
        return [mcc for (mcc,) in self.session.query(BlockedMCC.mcc).filter(BlockedMCC.account_id == account_id)]

    def has_consented_contact(self, account_id: int) -> bool:
        return self.session.query(
            exists().where(
                TrustedContact.account_id == account_id,
                TrustedContact.approval_consent_at.isnot(None),
            )
        ).scalar()

    def _open_finance_profile(self, account_id: int) -> OpenFinanceProfile | None:
        profile = self.session.get(OfPayerProfileModel, account_id)
        if profile is None:
            return None
        return OpenFinanceProfile(
            other_income_cents=profile.other_income_cents,
            other_balance_cents=profile.other_balance_cents,
            other_balance_prev_cents=profile.other_balance_prev_cents,
            prev_loaded_at=profile.prev_loaded_at,
            loaded_at=profile.loaded_at,
            consent_expires_at=profile.consent_expires_at,
        )

    def has_trusted_contact(self, account_id: int) -> bool:
        return self.session.query(exists().where(TrustedContact.account_id == account_id)).scalar()

    def load_destination_snapshot(
        self, destination_key: str, document: str, account: Account | None, at: datetime
    ) -> DestinationSnapshot:
        flags = (
            self.session.query(DestinationFlagModel)
            .filter(DestinationFlagModel.destination_key == destination_key, DestinationFlagModel.expires_at > at)
            .all()
        )
        reputation = self.session.get(DestinationReputationModel, destination_key)
        merchant_mcc = (
            self.session.query(Merchant.mcc)
            .filter(digits_only(Merchant.document_number) == digits_only(literal(document)))
            .scalar()
        )
        return DestinationSnapshot(
            destination_key=destination_key,
            document=document,
            account_created_at=account.created_at if account is not None else None,
            merchant_mcc=merchant_mcc,
            flags=tuple(DestinationFlag(flag.status, flag.starts_at, flag.expires_at) for flag in flags),
            reputation=self._to_reputation(reputation),
        )

    @staticmethod
    def _to_reputation(model: DestinationReputationModel | None) -> DestinationReputation:
        if model is None:
            return DestinationReputation()
        return DestinationReputation(
            analyses_count=model.analyses_count,
            rejected_count=model.rejected_count,
            two_factor_count=model.two_factor_count,
            payers_24h=model.payers_24h,
            forwarded_ratio_1h=float(model.forwarded_ratio_1h),
        )

    def load_device_snapshot(self, device_id: str | None, source_hash: str, at: datetime) -> DeviceSnapshot:
        if device_id is None:
            return DeviceSnapshot()
        first_seen = (
            self.session.query(DeviceSeenModel.first_seen)
            .filter(DeviceSeenModel.device_id == device_id, DeviceSeenModel.source_hash == source_hash)
            .scalar()
        )
        others = (
            self.session.query(func.count(DeviceSeenModel.source_hash))
            .filter(
                DeviceSeenModel.device_id == device_id,
                DeviceSeenModel.source_hash != source_hash,
                DeviceSeenModel.last_seen >= at - timedelta(days=7),
            )
            .scalar()
        )
        return DeviceSnapshot(first_seen=first_seen, distinct_payers_7d=others + 1)

    def persist_analysis(
        self,
        analysis: PixAnalysisModel,
        decision: Decision,
        context: EvaluationContext,
        source_account_id: int | None,
        destination_account_id: int | None,
    ) -> None:
        pix = context.pix
        self.save_decision(analysis, decision, decision.metadata(context))
        self.add_flags(pix.destination_key, decision.flag_changes)
        if pix.device_id is not None:
            self.touch_device(pix.device_id, context.payer.source_hash, pix.transaction_date)
        self.session.flush()
        self.bump_destination_reputation(
            pix.destination_key, decision.status, destination_account_id, pix.transaction_date
        )
        if decision.notify_trusted_contact and source_account_id is not None:
            self.add_outbox_notifications(analysis.id, source_account_id)

    def list_blocked_pix(self, limit: int = 50, offset: int = 0) -> list[dict]:
        rows = self.session.execute(BLOCKED_PIX_QUERY, {"limit": limit, "offset": offset}).mappings().all()
        return [dict(row) for row in rows]

    def save_decision(self, analysis: PixAnalysisModel, decision: Decision, metadata: dict) -> None:
        analysis.status = decision.status
        analysis.score = decision.score
        analysis.value_band = decision.value_band
        analysis.engine_version = decision.engine_version
        analysis.payer_class = decision.payer_class
        analysis.challenge_type = decision.challenge_type
        analysis.friction_script_key = decision.friction_script_key
        analysis.metadata_ = metadata
        for hit in decision.rules_fired:
            analysis.rule_results.append(
                PixRuleResultModel(rule_code=hit.code, points=hit.points, evidence=hit.evidence)
            )

    def add_rule_result(self, analysis: PixAnalysisModel, rule_code: str, evidence: dict, points: int = 0) -> None:
        analysis.rule_results.append(PixRuleResultModel(rule_code=rule_code, points=points, evidence=evidence))

    def touch_device(self, device_id: str, source_hash: str, seen_at: datetime) -> None:
        statement = insert(DeviceSeenModel).values(
            device_id=device_id, source_hash=source_hash, first_seen=seen_at, last_seen=seen_at, tx_count=1
        )
        statement = statement.on_conflict_do_update(
            index_elements=[DeviceSeenModel.device_id, DeviceSeenModel.source_hash],
            set_={
                "first_seen": func.least(DeviceSeenModel.first_seen, statement.excluded.first_seen),
                "last_seen": func.greatest(DeviceSeenModel.last_seen, statement.excluded.last_seen),
                "tx_count": DeviceSeenModel.tx_count + 1,
            },
        )
        self.session.execute(statement)

    def bump_destination_reputation(
        self, destination_key: str, status: str, destination_account_id: int | None, at: datetime
    ) -> None:
        rejected = 1 if status == REJECTED else 0
        two_factor = 1 if status == TWO_FACTOR_REQUIRED else 0
        payers_24h = (
            select(func.count(func.distinct(PixAnalysisModel.source_hash)))
            .where(
                PixAnalysisModel.destination_key == destination_key,
                PixAnalysisModel.transaction_date > at - timedelta(hours=24),
                PixAnalysisModel.transaction_date <= at,
            )
            .scalar_subquery()
        )
        forwarded = self._forwarded_ratio_1h(destination_account_id, at)

        statement = insert(DestinationReputationModel).values(
            destination_key=destination_key,
            analyses_count=1,
            rejected_count=rejected,
            two_factor_count=two_factor,
            payers_24h=payers_24h,
            forwarded_ratio_1h=forwarded,
            updated_at=func.now(),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[DestinationReputationModel.destination_key],
            set_={
                "analyses_count": DestinationReputationModel.analyses_count + 1,
                "rejected_count": DestinationReputationModel.rejected_count + rejected,
                "two_factor_count": DestinationReputationModel.two_factor_count + two_factor,
                "payers_24h": statement.excluded.payers_24h,
                "forwarded_ratio_1h": statement.excluded.forwarded_ratio_1h,
                "updated_at": func.now(),
            },
        )
        self.session.execute(statement)

    def _forwarded_ratio_1h(self, account_id: int | None, at: datetime):
        if account_id is None:
            return literal(0)

        since = at - timedelta(hours=24)
        credit = LedgerEntry.__table__.alias("credit")
        debit = LedgerEntry.__table__.alias("debit")
        received = (
            select(func.coalesce(func.sum(credit.c.amount_cents), 0))
            .where(
                credit.c.account_id == account_id,
                credit.c.direction == "CREDIT",
                credit.c.entry_datetime > since,
            )
            .scalar_subquery()
        )
        later_credit = LedgerEntry.__table__.alias("later_credit")
        forwarded = (
            select(func.coalesce(func.sum(debit.c.amount_cents), 0))
            .where(
                debit.c.account_id == account_id,
                debit.c.direction == "DEBIT",
                debit.c.kind.in_(["TRANSFER", "PURCHASE"]),
                exists().where(
                    and_(
                        later_credit.c.account_id == account_id,
                        later_credit.c.direction == "CREDIT",
                        later_credit.c.entry_datetime > since,
                        later_credit.c.entry_datetime <= debit.c.entry_datetime,
                        later_credit.c.entry_datetime >= debit.c.entry_datetime - timedelta(hours=1),
                    )
                ),
            )
            .scalar_subquery()
        )
        return func.least(1, func.coalesce(forwarded * 1.0 / func.nullif(received, 0), 0))

    def add_flags(self, destination_key: str, changes: list[FlagChange]) -> None:
        for change in changes:
            self.session.add(
                DestinationFlagModel(
                    destination_key=destination_key,
                    status=change.status,
                    reason=change.reason,
                    starts_at=change.starts_at,
                    expires_at=change.expires_at,
                )
            )

    def add_outbox_notifications(self, analysis_id: int, account_id: int) -> None:
        contact_ids = select(TrustedContact.id).where(TrustedContact.account_id == account_id)
        for (contact_id,) in self.session.execute(contact_ids).all():
            statement = (
                insert(NotificationOutbox)
                .values(analysis_id=analysis_id, contact_id=contact_id)
                .on_conflict_do_nothing(index_elements=[NotificationOutbox.analysis_id, NotificationOutbox.contact_id])
            )
            self.session.execute(statement)

    def mark_second_factor(self, analysis: PixAnalysisModel, at: datetime, contact_id: int | None = None) -> None:
        analysis.second_factor_at = at
        analysis.second_factor_contact_id = contact_id

    def record_friction_answer(self, analysis: PixAnalysisModel, answer: str, at: datetime) -> None:
        analysis.friction_answer = answer
        analysis.friction_answered_at = at

    def add_feedback(self, transaction_id: str, is_fraud: bool, reason: str | None) -> PixFeedbackModel:
        feedback = PixFeedbackModel(transaction_id=transaction_id, is_fraud=is_fraud, reason=reason)
        self.session.add(feedback)
        return feedback

    def add_shadow_result(self, analysis_id: int, shadow_score: float, model_version: str) -> PixShadowResultModel:
        result = PixShadowResultModel(analysis_id=analysis_id, shadow_score=shadow_score, model_version=model_version)
        self.session.add(result)
        return result
