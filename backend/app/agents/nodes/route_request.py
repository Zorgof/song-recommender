"""route_request: heuristics first; the light-model classifier only for uncertain cases."""

import logging
from typing import Any

from langgraph.config import get_config
from langgraph.runtime import Runtime

from app.agents.nodes.common import escalations
from app.agents.schemas import RouterClassification
from app.agents.state import AgentDeps, GraphState
from app.db.models import InputMode
from app.errors import LLMInvalidOutputError
from app.llm.routing import assess_complexity, decide
from app.llm.structured import structured_call

logger = logging.getLogger(__name__)

NODE = "route_request"


async def route_request(state: GraphState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    deps = runtime.context
    config = get_config()
    assessment = assess_complexity(state["user_input"], InputMode(state["input_mode"]))
    reasons = list(assessment.reasons)
    if assessment.verdict != "uncertain":
        return {"routing": decide(assessment.verdict, "heuristics", reasons).model_dump()}

    messages = deps.prompts.router.render(
        user_input=state["user_input"], heuristic_reasons="; ".join(reasons)
    )
    try:
        result = await structured_call(
            deps.models, "light", RouterClassification, messages, config=config
        )
    except LLMInvalidOutputError:
        # Routing must not fail a request; the heavy tier is the safe choice.
        logger.warning("Router classifier gave no valid answer; routing as complex")
        decision = decide("complex", "heuristics", [*reasons, "classifier failed"])
        return {"routing": decision.model_dump()}

    decision = decide(result.value.complexity, "classifier", [*reasons, result.value.reason])
    return {
        "routing": decision.model_dump(),
        "models_used": {NODE: result.model},
        "escalations": escalations(NODE, result),
    }
