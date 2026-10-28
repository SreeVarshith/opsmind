from fastapi import APIRouter, Depends, Query

from app.core.query_log import QueryLog, get_query_log
from app.core.security import User, require_role

router = APIRouter(prefix="/metrics", tags=["monitoring"])


@router.get("/summary")
def summary(hours: float = Query(24 * 7, gt=0, le=24 * 90), recent: int = Query(20, ge=0, le=200),
            _: User = Depends(require_role("admin", "sre")), log: QueryLog = Depends(get_query_log)) -> dict:
    """Usage, latency and answer-quality statistics (admins and SREs only)."""
    return log.summary(hours, recent)
