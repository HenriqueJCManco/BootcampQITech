from models.fraud import PixAnalysisModel


class PixAnalysisDTO:
    @staticmethod
    def to_dict(analysis: PixAnalysisModel) -> dict:
        return {
            "key": str(analysis.analysis_key),
            "status": analysis.status,
            "metadata": analysis.metadata_,
        }

    @staticmethod
    def with_second_factor(analysis: PixAnalysisModel) -> dict:
        body = PixAnalysisDTO.to_dict(analysis)
        body["second_factor"] = {
            "provider": "qitech",
            "challenge_type": analysis.challenge_type,
            "pix_transfer_key": str(analysis.qi_pix_transfer_key) if analysis.qi_pix_transfer_key else None,
            "provider_status": analysis.qi_transfer_status,
            "contact_type": analysis.qi_contact_type,
            "expires_at": analysis.challenge_expires_at.isoformat() if analysis.challenge_expires_at else None,
            "completed_at": analysis.second_factor_at.isoformat() if analysis.second_factor_at else None,
        }
        return body
