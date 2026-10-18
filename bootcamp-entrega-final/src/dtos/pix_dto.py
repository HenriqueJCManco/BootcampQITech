from models.fraud import PixAnalysis


class PixAnalysisDTO:
    @staticmethod
    def to_dict(analysis: PixAnalysis) -> dict:
        metadata = {
            "engine_version": analysis.engine_version,
            "score": analysis.score,
            "value_band": analysis.value_band,
            "thresholds": _get_thresholds_for_band(analysis.value_band),
            "rules_fired": [
                {
                    "code": r.rule_code,
                    "points": r.points,
                    "evidence": r.evidence or {},
                }
                for r in (analysis.rule_results or [])
            ],
            "floor_applied": getattr(analysis, "_floor_applied", None),
            "payer_class": getattr(analysis, "_payer_class", "PF"),
            "destination_status": getattr(analysis, "_destination_status", "NORMAL"),
            "destination_reputation": getattr(analysis, "_destination_reputation", None),
            "notify_trusted_contact": analysis.notify_trusted_contact,
            "customer_message_key": analysis.customer_message_key,
            "inputs_missing": analysis.inputs_missing or [],
        }

        if analysis.status == "two_factor_required":
            metadata["challenge_type"] = analysis.challenge_type or "BIOMETRIC_2FA"
            if analysis.friction_script_key:
                metadata["friction_script_key"] = analysis.friction_script_key
                metadata["friction_params"] = getattr(analysis, "_friction_params", {})

        return {
            "key": str(analysis.analysis_key),
            "status": analysis.status,
            "metadata": metadata,
        }


def _get_thresholds_for_band(value_band: str) -> dict:
    thresholds_map = {
        "A": {"two_factor": 45, "reject": 85},
        "B": {"two_factor": 35, "reject": 75},
        "C": {"two_factor": 30, "reject": 65},
        "D": {"two_factor": 25, "reject": 55},
    }
    return thresholds_map.get(value_band, {"two_factor": 30, "reject": 65})
