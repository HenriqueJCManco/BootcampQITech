from datetime import datetime

from domain import APPROVED, REJECTED, EngineConfig, apply_second_factor
from domain.engine import BLOCKED_FOR_SAFETY
from repositories import FraudRepository


ESCALATION_RULE = "ESCALATION"
PROVIDER_RULE = "QI2FA"


class SecondFactorService:
    """Resolve o segundo fator de uma análise em two_factor_required.

    A decisão é do motor (apply_second_factor): a resposta de fricção só
    escala, nunca relaxa. Quem chama decide se e quando a prova vale.
    """

    def __init__(self, repository: FraudRepository) -> None:
        self.repository = repository

    def outcome(self, analysis, friction_answer: str | None) -> tuple[str, str | None]:
        config_row = self.repository.get_config(analysis.engine_version)
        config = EngineConfig(version=config_row.version, params=config_row.params)
        has_consented_contact = analysis.source_account_id is not None and self.repository.has_consented_contact(
            analysis.source_account_id
        )
        return apply_second_factor(
            analysis.status, analysis.friction_script_key, friction_answer, has_consented_contact, config
        )

    def record(self, analysis, status: str, challenge_type: str | None, friction_answer: str | None,
               at: datetime) -> None:
        if friction_answer is not None:
            self.repository.record_friction_answer(analysis, friction_answer, at)
        if status == APPROVED:
            self.repository.mark_second_factor(analysis, at)
        else:
            self.repository.add_rule_result(
                analysis,
                ESCALATION_RULE,
                {"from": analysis.status, "to": status, "friction_answer": friction_answer,
                 "challenge_type": challenge_type},
            )
        self.set_status(analysis, status, challenge_type)

    def reject_by_provider(self, analysis, provider_code: str, provider_status: str) -> None:
        self.repository.add_rule_result(
            analysis, PROVIDER_RULE, {"provider_code": provider_code, "provider_status": provider_status}
        )
        self.set_status(analysis, REJECTED)

    @staticmethod
    def set_status(analysis, status: str, challenge_type: str | None = None) -> None:
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
