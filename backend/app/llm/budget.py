"""Recognizing provider errors that mean the API budget is used up (ADR-11.2).

OpenAI answers `429` with one of these codes when a project or organization hard spend limit
is reached, or the prepaid balance is empty. Unlike a rate limit, retrying cannot help until the
next billing cycle or a top-up, so the app reports it as `budget_exhausted` instead of a generic
"provider unavailable".
"""

import openai

BUDGET_ERROR_CODES = frozenset(
    {
        "project_spend_limit_exceeded",
        "organization_spend_limit_exceeded",
        "credit_balance_exhausted",
        # Older name for an exhausted quota or balance.
        "insufficient_quota",
    }
)


def is_budget_exhausted(exc: BaseException) -> bool:
    """True if `exc`, or an exception it was raised from, is a budget error from OpenAI."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, openai.APIError) and current.code in BUDGET_ERROR_CODES:
            return True
        current = current.__cause__ or current.__context__
    return False
