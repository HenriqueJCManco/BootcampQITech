from dataclasses import dataclass, field
from datetime import datetime


APPROVED = "approved"
TWO_FACTOR_REQUIRED = "two_factor_required"
REJECTED = "rejected"

PAYMENT = "payment"
REFUND = "refund"

CHANNELS = ("internet", "celular", "computador", "tablet", "relogio")

NORMAL = "NORMAL"
OBSERVACAO = "OBSERVACAO"
QUARENTENA = "QUARENTENA"
MARCADA = "MARCADA"

BIOMETRIC_2FA = "BIOMETRIC_2FA"
TRUSTED_CONTACT_APPROVAL = "TRUSTED_CONTACT_APPROVAL"


@dataclass(frozen=True)
class Geolocation:
    latitude: float
    longitude: float
    accuracy_m: float | None = None


@dataclass(frozen=True)
class Interaction:
    raw: dict = field(default_factory=dict)
    is_robotic_movement: bool | None = None
    typing_cadence_std_ms: float | None = None
    session_idle_then_burst: bool | None = None


@dataclass(frozen=True)
class PixRequest:
    pix_id: str
    amount_cents: int
    transaction_date: datetime
    source_document: str
    destination_document: str
    destination_key: str
    type: str = PAYMENT
    source_name: str | None = None
    channel: str | None = None
    device_id: str | None = None
    geolocation: Geolocation | None = None
    remote_access_detected: bool | None = None
    call_in_progress: bool | None = None
    has_trusted_contact: bool | None = None
    interaction: Interaction | None = None


@dataclass(frozen=True)
class PastPix:
    transaction_date: datetime
    amount_cents: int
    destination_key: str
    status: str | None
    completed: bool = False
    device_id: str | None = None
    channel: str | None = None
    geolocation: Geolocation | None = None


@dataclass(frozen=True)
class MoneyMovement:
    occurred_at: datetime
    amount_cents: int


@dataclass(frozen=True)
class OpenFinanceProfile:
    other_income_cents: int
    other_balance_cents: int
    loaded_at: datetime
    consent_expires_at: datetime
    other_balance_prev_cents: int | None = None
    prev_loaded_at: datetime | None = None

    def is_valid(self, at: datetime) -> bool:
        return self.consent_expires_at > at


@dataclass(frozen=True)
class PayerSnapshot:
    source_hash: str
    history: tuple[PastPix, ...] = ()
    amount_history: tuple[MoneyMovement, ...] = ()
    deposits: tuple[MoneyMovement, ...] = ()
    account_created_at: datetime | None = None
    balance_cents: int | None = None
    blocked_mccs: frozenset[str] = frozenset()
    has_consented_trusted_contact: bool = False
    open_finance: OpenFinanceProfile | None = None


@dataclass(frozen=True)
class DestinationFlag:
    status: str
    starts_at: datetime
    expires_at: datetime

    def is_active(self, at: datetime) -> bool:
        return self.starts_at <= at < self.expires_at


@dataclass(frozen=True)
class DestinationReputation:
    analyses_count: int = 0
    rejected_count: int = 0
    two_factor_count: int = 0
    payers_24h: int = 0
    forwarded_ratio_1h: float = 0.0

    @property
    def suspicious_ratio(self) -> float:
        if self.analyses_count == 0:
            return 0.0
        return (self.rejected_count + self.two_factor_count) / self.analyses_count


@dataclass(frozen=True)
class DestinationSnapshot:
    destination_key: str
    document: str
    account_created_at: datetime | None = None
    merchant_mcc: str | None = None
    bet_registered: bool = False
    flags: tuple[DestinationFlag, ...] = ()
    reputation: DestinationReputation = field(default_factory=DestinationReputation)


@dataclass(frozen=True)
class DeviceSnapshot:
    first_seen: datetime | None = None
    distinct_payers_7d: int = 0


@dataclass(frozen=True)
class EvaluationContext:
    pix: PixRequest
    payer: PayerSnapshot
    destination: DestinationSnapshot
    device: DeviceSnapshot = field(default_factory=DeviceSnapshot)


@dataclass(frozen=True)
class RuleHit:
    code: str
    points: int = 0
    evidence: dict = field(default_factory=dict)
    floor: bool = False
    eliminatory: bool = False

    def to_dict(self) -> dict:
        return {"code": self.code, "points": self.points, "evidence": self.evidence}


@dataclass(frozen=True)
class FlagChange:
    status: str
    reason: str
    starts_at: datetime
    expires_at: datetime


@dataclass
class Decision:
    status: str
    score: int
    value_band: str
    thresholds: dict
    engine_version: int
    payer_class: str
    destination_status: str
    rules_fired: list[RuleHit] = field(default_factory=list)
    floor_applied: list[str] = field(default_factory=list)
    inputs_missing: list[str] = field(default_factory=list)
    challenge_type: str | None = None
    friction_script_key: str | None = None
    friction_params: dict = field(default_factory=dict)
    notify_trusted_contact: bool = False
    customer_message_key: str | None = None
    flag_changes: list[FlagChange] = field(default_factory=list)
    family_caps_applied: dict = field(default_factory=dict)

    def metadata(self, context: "EvaluationContext") -> dict:
        reputation = context.destination.reputation
        metadata = {
            "engine_version": self.engine_version,
            "score": self.score,
            "value_band": self.value_band,
            "thresholds": self.thresholds,
            "rules_fired": [hit.to_dict() for hit in self.rules_fired],
            "floor_applied": self.floor_applied,
            "payer_class": self.payer_class,
            "destination_status": self.destination_status,
            "destination_reputation": {
                "analyses_count": reputation.analyses_count,
                "suspicious_ratio": round(reputation.suspicious_ratio, 4),
            },
            "notify_trusted_contact": self.notify_trusted_contact,
            "customer_message_key": self.customer_message_key,
            "inputs_missing": self.inputs_missing,
        }
        if self.family_caps_applied:
            metadata["family_caps_applied"] = self.family_caps_applied
        if context.pix.interaction is not None:
            metadata["inputs"] = {"interaction": context.pix.interaction.raw}
        if self.status == TWO_FACTOR_REQUIRED:
            metadata["challenge_type"] = self.challenge_type
            metadata["friction_script_key"] = self.friction_script_key
            metadata["friction_params"] = self.friction_params
        return metadata
