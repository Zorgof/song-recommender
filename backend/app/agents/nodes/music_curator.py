"""music_curator (Agent 2): NeedProfile -> ranked song candidates with user-facing explanations.

Attempt 1 uses the routed tier; a retry (no candidate of the previous attempt was verified)
always uses the heavy tier and gets the rejected candidates as feedback.
"""

import json
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config
from langgraph.runtime import Runtime

from app.agents.nodes.common import escalations
from app.agents.schemas import LOCALE_NAMES, CuratorOutput
from app.agents.state import (
    CANDIDATE_COUNT,
    AgentDeps,
    Escalation,
    GraphState,
    RejectedCandidate,
)
from app.llm.models import Tier
from app.llm.routing import RoutingDecision
from app.llm.structured import structured_call

NODE = "music_curator"
ESCALATION_NO_VERIFIED = "no_verified_candidates"


def excluded_block(tracks: list[dict[str, str]]) -> str:
    if not tracks:
        return "(none)"
    return "\n".join(f"- {t['artist']} - {t['title']}" for t in tracks)


def rejected_block(rejected: list[RejectedCandidate]) -> str:
    if not rejected:
        return ""
    lines = "\n".join(f"- {r['artist']} - {r['title']}: {r['reason']}" for r in rejected)
    return (
        "Your earlier candidates were rejected; propose different songs and make sure they "
        f"exist on Spotify under exactly this title and artist:\n{lines}"
    )


async def music_curator(state: GraphState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    deps = runtime.context
    config = get_config()
    routing = RoutingDecision.model_validate(state["routing"])
    attempt = state.get("curation_attempts", 0) + 1
    tier: Tier = routing.curator_tier if attempt == 1 else "heavy"
    retry_escalation: list[Escalation] = []
    if attempt > 1 and routing.curator_tier == "light":
        retry_escalation.append(
            Escalation(node=NODE, from_tier="light", to_tier="heavy", reason=ESCALATION_NO_VERIFIED)
        )

    messages = deps.prompts.curator.render(
        candidate_count=str(CANDIDATE_COUNT),
        locale_name=LOCALE_NAMES[state["locale"]],
        need_profile=json.dumps(state["need_profile"], ensure_ascii=False, indent=2),
        excluded_tracks=excluded_block(state.get("excluded_tracks", [])),
        rejected_candidates=rejected_block(state.get("rejected", [])),
    )
    attempt_config: RunnableConfig = {
        **config,
        "metadata": {**config.get("metadata", {}), "curation_attempt": attempt},
    }
    result = await structured_call(
        deps.models, tier, CuratorOutput, messages, config=attempt_config
    )
    candidates = sorted(result.value.candidates, key=lambda c: c.rank)
    return {
        "curation_attempts": attempt,
        "candidates": [c.model_dump() for c in candidates],
        "verified": [],
        "models_used": {NODE: result.model},
        "escalations": [*retry_escalation, *escalations(NODE, result)],
    }
