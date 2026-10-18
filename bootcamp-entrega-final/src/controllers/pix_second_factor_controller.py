from datetime import datetime, timedelta, timezone
from uuid import uuid4

from connectors import QITechConnector, QiTechError, QiTechUnavailable
from connectors.qitech_connector import PENDING, PENDING_2FA_APPROVAL, REJECTED, SENT, TOKEN_TTL_MINUTES
from controllers.base_controller import BaseController
from controllers.second_factor import SecondFactorService
from domain import APPROVED, TWO_FACTOR_REQUIRED
from domain.entities import CUSTOMER_TOKEN_2FA, TRUSTED_CONTACT_APPROVAL
from domain.identity import document_hash, only_digits
from dtos import PixAnalysisDTO
from errors import (
    PixAnalysisNotFound,
    PixInvalidApprover,
    PixInvalidDocument,
    PixSecondFactorNotPending,
    PixSecondFactorUnavailable,
    PixTokenAttemptsExceeded,
    PixTokenExpired,
    PixTokenIncorrect,
    PixTransferRefused,
    QIException,
)
from repositories import FraudRepository
from utils.document_number import is_valid_cpf


QI_NO_APPROVER_PERMISSION = "PXT000168"
QI_TOKEN_ATTEMPTS_EXCEEDED = "PXT000171"
QI_TOKEN_EXPIRED = "PXT000172"
QI_TOKEN_INCORRECT = "PXT000173"
QI_NOT_PENDING = "PXT000175"
QI_TOKEN_DELIVERY_ERRORS = {"PXT000170", "PXT000174", "PXT000176"}
QI_ACCEPTED = {SENT, PENDING}


class PixSecondFactorController(BaseController):
    """Segundo fator do Pix pela QI Tech (2FA v2), no papel da transaction-api.

    O motor só decide (two_factor_required, challenge_type, fricção). Este
    controller abre a transferência na QI com tfa_info, valida o token do
    aprovador e traduz status e erros da QI para a análise.
    """

    def __init__(self, connector: QITechConnector | None = None) -> None:
        super().__init__(__name__)
        self.repository = FraudRepository(self.session)
        self.second_factor = SecondFactorService(self.repository)
        self.qitech = connector or QITechConnector()

    def open_challenge(self, pix_id: str, payload: dict) -> tuple[dict, bool]:
        analysis = self._pending_analysis(pix_id)
        if analysis.qi_pix_transfer_key is not None and analysis.qi_transfer_status == PENDING_2FA_APPROVAL:
            return PixAnalysisDTO.with_second_factor(analysis), False

        approver = payload["approver"]
        approver_document = only_digits(approver["document_number"])
        self._check_approver(analysis, approver_document)

        request_control_key = str(uuid4())
        try:
            transfer = self.qitech.request_pix_transfer_2fa(
                account_key=payload["qi_account_key"],
                request_control_key=request_control_key,
                amount_cents=analysis.amount_cents,
                transfer=payload["transfer"],
                approver_document_number=approver_document,
                contact_type=approver["contact_type"],
            )
        except QiTechUnavailable:
            raise PixSecondFactorUnavailable() from None
        except QiTechError as error:
            raise self._provider_error(analysis, error) from None

        self.repository.open_qi_challenge(
            analysis, payload["qi_account_key"], request_control_key, transfer, approver["contact_type"],
            self._expiry(),
        )
        self.session.commit()
        return PixAnalysisDTO.with_second_factor(analysis), True

    def confirm_token(self, pix_id: str, payload: dict) -> dict:
        analysis = self._challenged_analysis(pix_id)
        answer = payload.get("friction_answer")
        now = datetime.now(timezone.utc)

        status, challenge_type = self.second_factor.outcome(analysis, answer)
        if status != APPROVED:
            self.second_factor.record(analysis, status, challenge_type, answer, now)
            self.repository.close_qi_challenge(analysis)
            self.session.commit()
            return PixAnalysisDTO.with_second_factor(analysis)

        try:
            transfer = self.qitech.validate_token(
                str(analysis.qi_account_key), str(analysis.qi_pix_transfer_key), payload["token"]
            )
        except QiTechUnavailable:
            raise PixSecondFactorUnavailable() from None
        except QiTechError as error:
            raise self._provider_error(analysis, error) from None

        self.repository.update_qi_status(analysis, transfer.status)
        if transfer.status in QI_ACCEPTED:
            self.second_factor.record(analysis, APPROVED, None, answer, now)
        elif transfer.status == REJECTED:
            self.second_factor.reject_by_provider(analysis, "validate_token", REJECTED)
        self.session.commit()
        return PixAnalysisDTO.with_second_factor(analysis)

    def resend_token(self, pix_id: str) -> dict:
        analysis = self._challenged_analysis(pix_id)
        try:
            transfer = self.qitech.resend_token(str(analysis.qi_account_key), str(analysis.qi_pix_transfer_key))
        except QiTechUnavailable:
            raise PixSecondFactorUnavailable() from None
        except QiTechError as error:
            raise self._provider_error(analysis, error) from None

        self.repository.update_qi_status(analysis, transfer.status, self._expiry())
        self.session.commit()
        return PixAnalysisDTO.with_second_factor(analysis)

    def _pending_analysis(self, pix_id: str):
        analysis = self.repository.get_analysis_by_pix_id(pix_id)
        if analysis is None or analysis.status is None:
            raise PixAnalysisNotFound()
        if analysis.status != TWO_FACTOR_REQUIRED:
            raise PixSecondFactorNotPending()
        return analysis

    def _challenged_analysis(self, pix_id: str):
        analysis = self._pending_analysis(pix_id)
        if analysis.qi_pix_transfer_key is None:
            raise PixSecondFactorNotPending("No second factor challenge was opened for this Pix.")
        return analysis

    @staticmethod
    def _check_approver(analysis, approver_document: str) -> None:
        if not is_valid_cpf(approver_document):
            raise PixInvalidDocument("approver.document_number")
        is_payer = document_hash(approver_document) == analysis.source_hash
        if analysis.challenge_type == CUSTOMER_TOKEN_2FA and not is_payer:
            raise PixInvalidApprover("The customer token must be sent to the payer.")
        if analysis.challenge_type == TRUSTED_CONTACT_APPROVAL and is_payer:
            raise PixInvalidApprover("Trusted contact approval must be sent to the trusted contact, not to the payer.")

    def _provider_error(self, analysis, error: QiTechError) -> QIException:
        rejected = error.code == QI_TOKEN_ATTEMPTS_EXCEEDED or (
            error.transfer is not None and error.transfer.status == REJECTED
        )
        if rejected:
            self.repository.update_qi_status(analysis, REJECTED)
            self.second_factor.reject_by_provider(analysis, error.code, REJECTED)
            self.session.commit()
            if error.code == QI_TOKEN_ATTEMPTS_EXCEEDED:
                return PixTokenAttemptsExceeded()
            return PixTransferRefused(error.code)

        if error.code == QI_TOKEN_INCORRECT:
            return PixTokenIncorrect()
        if error.code == QI_TOKEN_EXPIRED:
            return PixTokenExpired()
        if error.code == QI_NO_APPROVER_PERMISSION:
            return PixInvalidApprover("The approver is not registered at the payment provider for this account.")
        if error.code == QI_NOT_PENDING:
            return PixSecondFactorNotPending("The provider transfer is no longer waiting for a token.")
        if error.code in QI_TOKEN_DELIVERY_ERRORS:
            return PixSecondFactorUnavailable()
        return PixTransferRefused(error.code)

    @staticmethod
    def _expiry() -> datetime:
        return datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)
