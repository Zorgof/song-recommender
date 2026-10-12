"""Daily limits, so the shared LLM budget is not used up by one visitor (ADR-11.1) or by all
visitors together in one day (ADR-11.2)."""

import logging

from app.db.base import utc_now
from app.db.models import UsageAction
from app.db.repositories import UsageRepository
from app.errors import DailyCapacityReachedError, DailyLimitReachedError

logger = logging.getLogger(__name__)

# Counter key of the totals of all visitors. Visitor ids are URL-safe base64, which has no "*".
ALL_VISITORS = "*"


class DailyLimits:
    def __init__(
        self,
        usage: UsageRepository,
        limits: dict[UsageAction, int],
        total_limits: dict[UsageAction, int] | None = None,
    ) -> None:
        # 0 = no limit for that action.
        self._usage = usage
        self._limits = limits
        self._total_limits = total_limits or {}

    async def use(self, visitor_id: str, action: UsageAction) -> None:
        """Count one use of `action` today (UTC), or raise when a daily limit is reached.

        The visitor's own limit is checked first, so a visitor who is over it does not use up
        the total that other visitors share.
        """
        day = utc_now().date()
        limit = self._limits.get(action, 0)
        if limit and not await self._usage.try_use(visitor_id, action, day=day, limit=limit):
            # The visitor id is not logged: it is the key to the visitor's history.
            logger.info("Daily limit reached", extra={"action": action.value, "limit": limit})
            raise DailyLimitReachedError()
        total = self._total_limits.get(action, 0)
        if total and not await self._usage.try_use(ALL_VISITORS, action, day=day, limit=total):
            logger.warning(
                "Daily limit of all visitors reached",
                extra={"action": action.value, "limit": total},
            )
            raise DailyCapacityReachedError()
