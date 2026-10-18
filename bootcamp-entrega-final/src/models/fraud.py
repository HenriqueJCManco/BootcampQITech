from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from models.base import Base


FRAUD_SCHEMA = "fraude"


class EngineConfigModel(Base):
    __tablename__ = "engine_config"
    __table_args__ = (
        CheckConstraint("version >= 1", name="chk_engine_config_version"),
        Index("ix_engine_config_active_from", text("active_from DESC")),
        {"schema": FRAUD_SCHEMA},
    )

    version = Column(Integer, primary_key=True, autoincrement=False)
    params = Column(JSONB, nullable=False)
    active_from = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PixAnalysisModel(Base):
    __tablename__ = "pix_analysis"
    __table_args__ = (
        UniqueConstraint("pix_id", name="uq_pix_analysis_pix_id"),
        CheckConstraint(
            "status IN ('approved', 'two_factor_required', 'rejected')",
            name="chk_pix_analysis_status",
        ),
        CheckConstraint("value_band IN ('A', 'B', 'C', 'D')", name="chk_pix_analysis_value_band"),
        CheckConstraint("type IN ('payment', 'refund')", name="chk_pix_analysis_type"),
        CheckConstraint("amount_cents >= 1", name="chk_pix_analysis_amount"),
        CheckConstraint(
            "channel IN ('internet', 'celular', 'computador', 'tablet', 'relogio')",
            name="chk_pix_analysis_channel",
        ),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="chk_pix_analysis_geolocation"),
        CheckConstraint("geo_accuracy_m IS NULL OR geo_accuracy_m >= 0", name="chk_pix_analysis_geo_accuracy"),
        Index("ix_pix_analysis_source_date", "source_hash", text("transaction_date DESC")),
        Index("ix_pix_analysis_destination_date", "destination_key", text("transaction_date DESC")),
        Index(
            "ix_pix_analysis_device_date",
            "device_id",
            text("transaction_date DESC"),
            postgresql_where=text("device_id IS NOT NULL"),
        ),
        {"schema": FRAUD_SCHEMA},
    )

    id = Column(BigInteger, primary_key=True)
    analysis_key = Column(UUID(as_uuid=True), nullable=False, unique=True, server_default=text("gen_random_uuid()"))
    pix_id = Column(String(255), nullable=False)
    request_hash = Column(CHAR(64), nullable=False)
    status = Column(String(20))
    score = Column(Integer)
    value_band = Column(CHAR(1))
    engine_version = Column(Integer, ForeignKey(f"{FRAUD_SCHEMA}.engine_config.version"))
    type = Column(String(10), nullable=False, server_default="payment")
    amount_cents = Column(BigInteger, nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    source_account_id = Column(BigInteger, ForeignKey("account.id"))
    source_hash = Column(CHAR(64), nullable=False)
    destination_account_id = Column(BigInteger, ForeignKey("account.id"))
    destination_key = Column(CHAR(64), nullable=False)
    device_id = Column(String(255))
    channel = Column(String(20))
    latitude = Column(Float)
    longitude = Column(Float)
    geo_accuracy_m = Column(Integer)
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    second_factor = relationship(
        "PixSecondFactorModel",
        back_populates="analysis",
        uselist=False,
        cascade="all, delete-orphan",
    )
    rule_results = relationship(
        "PixRuleResultModel",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="PixRuleResultModel.id",
    )
    engine_config = relationship("EngineConfigModel")
    source_account = relationship("Account", foreign_keys=[source_account_id])
    destination_account = relationship("Account", foreign_keys=[destination_account_id])
    feedbacks = relationship("PixFeedbackModel", back_populates="analysis")
    shadow_results = relationship("PixShadowResultModel", back_populates="analysis")

    @property
    def challenge_type(self) -> str | None:
        return self.second_factor.challenge_type if self.second_factor else None

    @property
    def friction_script_key(self) -> str | None:
        return self.second_factor.friction_script_key if self.second_factor else None

    @property
    def friction_answer(self) -> str | None:
        return self.second_factor.friction_answer if self.second_factor else None

    @property
    def friction_answered_at(self):
        return self.second_factor.friction_answered_at if self.second_factor else None

    @property
    def second_factor_at(self):
        return self.second_factor.second_factor_at if self.second_factor else None

    @property
    def second_factor_contact_id(self) -> int | None:
        return self.second_factor.second_factor_contact_id if self.second_factor else None

    @property
    def qi_account_key(self):
        return self.second_factor.qi_account_key if self.second_factor else None

    @property
    def qi_request_control_key(self):
        return self.second_factor.qi_request_control_key if self.second_factor else None

    @property
    def qi_pix_transfer_key(self):
        return self.second_factor.qi_pix_transfer_key if self.second_factor else None

    @property
    def qi_end_to_end_id(self) -> str | None:
        return self.second_factor.qi_end_to_end_id if self.second_factor else None

    @property
    def qi_transfer_status(self) -> str | None:
        return self.second_factor.qi_transfer_status if self.second_factor else None

    @property
    def qi_contact_type(self) -> str | None:
        return self.second_factor.qi_contact_type if self.second_factor else None

    @property
    def challenge_expires_at(self):
        return self.second_factor.challenge_expires_at if self.second_factor else None


class PixSecondFactorModel(Base):
    __tablename__ = "pix_second_factor"
    __table_args__ = (
        UniqueConstraint("qi_pix_transfer_key", name="uq_pix_second_factor_qi_pix_transfer_key"),
        CheckConstraint(
            "challenge_type IN ('CUSTOMER_TOKEN_2FA', 'TRUSTED_CONTACT_APPROVAL')",
            name="chk_pix_second_factor_challenge_type",
        ),
        CheckConstraint("friction_answer IN ('YES', 'NO', 'SKIP')", name="chk_pix_second_factor_friction_answer"),
        CheckConstraint(
            "qi_transfer_status IN ('pending_2fa_approval', 'sent', 'pending', 'rejected')",
            name="chk_pix_second_factor_qi_transfer_status",
        ),
        CheckConstraint("qi_contact_type IN ('sms', 'email')", name="chk_pix_second_factor_qi_contact_type"),
        {"schema": FRAUD_SCHEMA},
    )

    analysis_id = Column(
        BigInteger,
        ForeignKey(f"{FRAUD_SCHEMA}.pix_analysis.id", ondelete="CASCADE"),
        primary_key=True,
    )
    challenge_type = Column(String(30))
    friction_script_key = Column(String(40))
    friction_answer = Column(String(4))
    friction_answered_at = Column(DateTime(timezone=True))
    second_factor_at = Column(DateTime(timezone=True))
    second_factor_contact_id = Column(BigInteger, ForeignKey("trusted_contact.id"))
    qi_account_key = Column(UUID(as_uuid=True))
    qi_request_control_key = Column(UUID(as_uuid=True))
    qi_pix_transfer_key = Column(UUID(as_uuid=True))
    qi_end_to_end_id = Column(String(32))
    qi_transfer_status = Column(String(30))
    qi_contact_type = Column(String(5))
    challenge_expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    analysis = relationship("PixAnalysisModel", back_populates="second_factor")


class PixRuleResultModel(Base):
    __tablename__ = "pix_rule_result"
    __table_args__ = (
        Index("ix_pix_rule_result_analysis", "analysis_id"),
        Index("ix_pix_rule_result_rule_code", "rule_code", text("created_at DESC")),
        {"schema": FRAUD_SCHEMA},
    )

    id = Column(BigInteger, primary_key=True)
    analysis_id = Column(
        BigInteger,
        ForeignKey(f"{FRAUD_SCHEMA}.pix_analysis.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_code = Column(String(10), nullable=False)
    points = Column(Integer, nullable=False, server_default="0")
    evidence = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    analysis = relationship("PixAnalysisModel", back_populates="rule_results")


class DeviceSeenModel(Base):
    __tablename__ = "device_seen"
    __table_args__ = (
        PrimaryKeyConstraint("device_id", "source_hash"),
        CheckConstraint("tx_count >= 1", name="chk_device_seen_tx_count"),
        CheckConstraint("last_seen >= first_seen", name="chk_device_seen_dates"),
        Index("ix_device_seen_device_first_seen", "device_id", "first_seen"),
        {"schema": FRAUD_SCHEMA},
    )

    device_id = Column(String(255), nullable=False)
    source_hash = Column(CHAR(64), nullable=False)
    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)
    tx_count = Column(Integer, nullable=False, server_default="1")


class DestinationFlagModel(Base):
    __tablename__ = "destination_flag"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OBSERVACAO', 'QUARENTENA', 'MARCADA')",
            name="chk_destination_flag_status",
        ),
        CheckConstraint("expires_at > starts_at", name="chk_destination_flag_period"),
        Index("ix_destination_flag_key_expires", "destination_key", text("expires_at DESC")),
        {"schema": FRAUD_SCHEMA},
    )

    id = Column(BigInteger, primary_key=True)
    destination_key = Column(CHAR(64), nullable=False)
    status = Column(String(20), nullable=False)
    reason = Column(String(255), nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DestinationReputationModel(Base):
    __tablename__ = "destination_reputation"
    __table_args__ = (
        CheckConstraint(
            "analyses_count >= 0 AND rejected_count >= 0 AND two_factor_count >= 0 "
            "AND payers_24h >= 0 AND rejected_count + two_factor_count <= analyses_count",
            name="chk_destination_reputation_counts",
        ),
        CheckConstraint(
            "forwarded_ratio_1h >= 0 AND forwarded_ratio_1h <= 1",
            name="chk_destination_reputation_ratio",
        ),
        {"schema": FRAUD_SCHEMA},
    )

    destination_key = Column(CHAR(64), primary_key=True)
    analyses_count = Column(Integer, nullable=False, server_default="0")
    rejected_count = Column(Integer, nullable=False, server_default="0")
    two_factor_count = Column(Integer, nullable=False, server_default="0")
    payers_24h = Column(Integer, nullable=False, server_default="0")
    forwarded_ratio_1h = Column(Numeric(5, 4), nullable=False, server_default="0")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BetDestinationModel(Base):
    __tablename__ = "bet_destination"
    __table_args__ = (
        CheckConstraint("cnpj ~ '^[0-9]{14}$'", name="chk_bet_destination_cnpj"),
        Index("ix_bet_destination_active", "cnpj", postgresql_where=text("active")),
        {"schema": FRAUD_SCHEMA},
    )

    cnpj = Column(CHAR(14), primary_key=True)
    razao_social = Column(String(255), nullable=False)
    source = Column(String(100), nullable=False)
    active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OfPayerProfileModel(Base):
    __tablename__ = "of_payer_profile"
    __table_args__ = (
        CheckConstraint(
            "other_income_cents >= 0 AND other_balance_cents >= 0 "
            "AND (other_balance_prev_cents IS NULL OR other_balance_prev_cents >= 0)",
            name="chk_of_payer_profile_values",
        ),
        {"schema": FRAUD_SCHEMA},
    )

    account_id = Column(BigInteger, ForeignKey("account.id", ondelete="CASCADE"), primary_key=True)
    other_income_cents = Column(BigInteger, nullable=False, server_default="0")
    other_balance_cents = Column(BigInteger, nullable=False, server_default="0")
    other_balance_prev_cents = Column(BigInteger)
    prev_loaded_at = Column(DateTime(timezone=True))
    loaded_at = Column(DateTime(timezone=True), nullable=False)
    consent_expires_at = Column(DateTime(timezone=True), nullable=False)

    account = relationship("Account")


class PixFeedbackModel(Base):
    __tablename__ = "pix_feedback"
    __table_args__ = (
        Index("ix_pix_feedback_transaction", "transaction_id"),
        {"schema": FRAUD_SCHEMA},
    )

    id = Column(BigInteger, primary_key=True)
    transaction_id = Column(String(255), ForeignKey(f"{FRAUD_SCHEMA}.pix_analysis.pix_id"), nullable=False)
    is_fraud = Column(Boolean, nullable=False)
    reason = Column(String(500))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    analysis = relationship("PixAnalysisModel", back_populates="feedbacks")


class PixShadowResultModel(Base):
    __tablename__ = "pix_shadow_result"
    __table_args__ = (
        Index("ix_pix_shadow_result_analysis", "analysis_id"),
        {"schema": FRAUD_SCHEMA},
    )

    id = Column(BigInteger, primary_key=True)
    analysis_id = Column(
        BigInteger,
        ForeignKey(f"{FRAUD_SCHEMA}.pix_analysis.id", ondelete="CASCADE"),
        nullable=False,
    )
    shadow_score = Column(Numeric(7, 4), nullable=False)
    model_version = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    analysis = relationship("PixAnalysisModel", back_populates="shadow_results")


PixAnalysis = PixAnalysisModel
PixSecondFactor = PixSecondFactorModel
PixRuleResult = PixRuleResultModel
PixFeedback = PixFeedbackModel
DeviceSeen = DeviceSeenModel
DestinationFlag = DestinationFlagModel
DestinationReputation = DestinationReputationModel
OfPayerProfile = OfPayerProfileModel
EngineConfig = EngineConfigModel
PixShadowResult = PixShadowResultModel
