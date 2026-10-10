"""Helpers shared by the LLM nodes."""

from typing import Any

from pydantic import BaseModel

from app.agents.state import Escalation
from app.llm.structured import StructuredResult


def escalations[T: BaseModel](node: str, result: StructuredResult[T]) -> list[Escalation]:
    """The escalation of one structured call, as recorded in the state (empty if none)."""
    if not result.escalated or result.escalation_reason is None:
        return []
    return [
        Escalation(
            node=node,
            from_tier=result.tier_requested,
            to_tier=result.tier_used,
            reason=result.escalation_reason,
        )
    ]


def without_catalog(inputs: dict[str, Any]) -> dict[str, Any]:
    """Inputs of a traced catalog call without the catalog object itself."""
    return {k: v for k, v in inputs.items() if k != "catalog"}
