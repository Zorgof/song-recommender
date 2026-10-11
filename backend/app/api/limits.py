"""Daily limits per visitor, so one person cannot use up the shared LLM budget (ADR-11.1)."""

import logging

from app.db.base import utc_now
from app.db.models import UsageAction
from app.db.repositories import UsageRepository
from app.errors import DailyLimitReachedError

logger = logging.getLogger(__name__)


class DailyLimits:
    def __init__(self, usage: UsageRepository, limits: dict[UsageAction, int]) -> None:
        # 0 = no limit for that action.
        self._usage = usage
        self._limits = limits

    async def use(self, visitor_id: str, action: UsageAction) -> None:
        """Count one use of `action` today (UTC), or raise when the daily limit is reached."""
        limit = self._limits.get(action, 0)
        if limit == 0:
            return
        if not await self._usage.try_use(visitor_id, action, day=utc_now().date(), limit=limit):
            # The visitor id is not logged: it is the key to the visitor's history.
            logger.info("Daily limit reached", extra={"action": action.value, "limit": limit})
            raise DailyLimitReachedError()
