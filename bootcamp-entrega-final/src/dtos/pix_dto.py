from models.fraud import PixAnalysisModel


class PixAnalysisDTO:
    @staticmethod
    def to_dict(analysis: PixAnalysisModel) -> dict:
        return {
            "key": str(analysis.analysis_key),
            "status": analysis.status,
            "metadata": analysis.metadata_,
        }
