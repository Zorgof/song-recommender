"""Assembly of the agent graph (implementation plan, 2.1).

START -> route_request -> need_analyst -> [ask_clarification -> need_analyst]
      -> music_curator -> verify_candidates -> [music_curator (retry)] -> finalize -> END
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.nodes.ask_clarification import ask_clarification
from app.agents.nodes.finalize import finalize
from app.agents.nodes.music_curator import music_curator
from app.agents.nodes.need_analyst import after_need_analyst, need_analyst
from app.agents.nodes.route_request import route_request
from app.agents.nodes.verify_candidates import after_verification, verify_candidates
from app.agents.state import AgentDeps, GraphState

RecommendationGraph = CompiledStateGraph[GraphState, AgentDeps, GraphState, GraphState]


def build_graph(checkpointer: BaseCheckpointSaver[str]) -> RecommendationGraph:
    graph = StateGraph(GraphState, context_schema=AgentDeps)
    graph.add_node("route_request", route_request)
    graph.add_node("need_analyst", need_analyst)
    graph.add_node("ask_clarification", ask_clarification)
    graph.add_node("music_curator", music_curator)
    graph.add_node("verify_candidates", verify_candidates)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "route_request")
    graph.add_edge("route_request", "need_analyst")
    graph.add_conditional_edges(
        "need_analyst", after_need_analyst, ["ask_clarification", "music_curator"]
    )
    graph.add_edge("ask_clarification", "need_analyst")
    graph.add_edge("music_curator", "verify_candidates")
    graph.add_conditional_edges(
        "verify_candidates", after_verification, ["music_curator", "finalize"]
    )
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer, name="recommendation_graph")
