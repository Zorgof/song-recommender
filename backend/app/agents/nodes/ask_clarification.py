"""ask_clarification: pauses the graph until the user answers the question."""

from typing import Any

from langgraph.types import interrupt

from app.agents.state import GraphState


async def ask_clarification(state: GraphState) -> dict[str, Any]:
    # The run stops here; the API returns the question. On resume (Command(resume=answer))
    # the node runs again from the top and `interrupt` returns the answer.
    answer = interrupt({"question": state["clarification_question"]})
    return {"clarification_answer": str(answer)}
