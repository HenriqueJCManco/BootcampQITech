import os
from fastapi import Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from constants import SERVICE_NAME
from database import get_context


class HealthCheckResource:
    def _build_diagnostics(self) -> dict:
        db_status = "connected"
        metrics = {}
        try:
            context = get_context()
            session = context.get_or_create_session()
            res = session.execute(
                text(
                    """
                    SELECT 
                        (SELECT count(*) FROM customer) AS customers,
                        (SELECT count(*) FROM account) AS accounts,
                        (SELECT count(*) FROM fraude.pix_analysis) AS pix_analyses,
                        (SELECT count(*) FROM trusted_location) AS trusted_locations,
                        (SELECT count(*) FROM merchant) AS merchants
                    """
                )
            ).fetchone()
            if res:
                metrics = {
                    "total_customers": res.customers,
                    "total_accounts": res.accounts,
                    "total_pix_analyses": res.pix_analyses,
                    "trusted_locations": res.trusted_locations,
                    "merchants": res.merchants,
                }
        except Exception as e:
            db_status = f"degraded: {str(e)}"

        return {
            "status": "healthy",
            "service": SERVICE_NAME,
            "pid": str(os.getpid()),
            "database": {
                "status": db_status,
                "metrics": metrics,
            },
            "antifraud_engine": {
                "version": 1,
                "status": "active",
                "rules_loaded": 22,
            },
        }

    def on_get_home(self) -> JSONResponse:
        data = self._build_diagnostics()
        return JSONResponse(content=data, status_code=status.HTTP_200_OK)

    def on_get_health_check(self) -> JSONResponse:
        data = self._build_diagnostics()
        return JSONResponse(content=data, status_code=status.HTTP_200_OK)
