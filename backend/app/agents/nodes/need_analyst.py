"""need_analyst (Agent 1): description -> NeedProfile; may request one clarifying question."""

from typing import Any

from langgraph.config import get_config
from langgraph.runtime import Runtime

from app.agents.nodes.common import escalations
from app.agents.schemas import LOCALE_NAMES, NeedProfile
from app.agents.state import AgentDeps, GraphState
from app.llm.routing import RoutingDecision
from app.llm.structured import structured_call

NODE = "need_analyst"

_VOICE_NOTE = (
    "The description is a speech transcript; it may contain recognition errors and filler words."
)
_TEXT_NOTE = "The description was typed by the user."


def clarification_block(question: str | None, answer: str | None) -> str:
    if answer is None:
        return ""
    return (
        "You already asked the user a clarifying question; do not ask another one "
        "(needs_clarification must be false).\n"
        f"<clarifying_question>\n{question or ''}\n</clarifying_question>\n"
        f"<user_answer>\n{answer}\n</user_answer>"
    )


async def need_analyst(state: GraphState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    deps = runtime.context
    config = get_config()
    routing = RoutingDecision.model_validate(state["routing"])
    answer = state.get("clarification_answer")
    messages = deps.prompts.need_analyst.render(
        locale_name=LOCALE_NAMES[state["locale"]],
        input_mode_note=_VOICE_NOTE if state["input_mode"] == "voice" else _TEXT_NOTE,
        user_input=state["user_input"],
        clarification=clarification_block(state.get("clarification_question"), answer),
    )
    result = await structured_call(
        deps.models, routing.need_analyst_tier, NeedProfile, messages, config=config
    )
    profile = result.value
    update: dict[str, Any] = {
        "need_profile": profile.model_dump(),
        "models_used": {NODE: result.model},
        "escalations": escalations(NODE, result),
    }
    if wants_clarification(profile, answer):
        update["clarification_question"] = profile.clarification_question
    return update


def wants_clarification(profile: NeedProfile, answer: str | None) -> bool:
    """A question is asked at most once, and only if the model wrote one."""
    return (
        profile.needs_clarification
        and bool(profile.clarification_question and profile.clarification_question.strip())
        and answer is None
    )


def after_need_analyst(state: GraphState) -> str:
    profile = NeedProfile.model_validate(state["need_profile"])
    if wants_clarification(profile, state.get("clarification_answer")):
        return "ask_clarification"
    return "music_curator"
