from typing import TypedDict, Annotated, Optional
from langgraph.graph import StateGraph, END
import operator
import structlog

logger = structlog.get_logger()


class AgentState(TypedDict):
    """
    The shared state object passed between all agent nodes.
    Each node reads from this and adds its results back to it.
    Think of it as a shared whiteboard for the entire agent run.
    """
    # Input
    question: str                          # the user's question
    user_id: str                           # who is asking
    session_id: str                        # which conversation
    document_ids: Optional[list[str]]      # which documents to search (None = all)

    # Routing
    route: Optional[str]                   # supervisor's decision: "retriever", "summarizer", etc.

    # Retriever output
    retrieved_chunks: Optional[list[dict]] # chunks from Qdrant with text + scores

    # Summarizer output
    summary: Optional[str]                 # summary of document(s)

    # Final output
    final_answer: str                      # the answer sent to the user
    sources: Optional[list[dict]]          # citations shown to the user

    # Observability — this is what makes it production-grade
    nodes_invoked: Annotated[list[str], operator.add]  # tracks which nodes ran
    agent_trace: Annotated[list[dict], operator.add]   # full execution log
    tokens_used: int                       # total tokens consumed
    latency_ms: int                        # total time taken


def build_graph():
    """
    Builds and compiles the LangGraph agent graph.
    Nodes are connected based on the supervisor's routing decision.
    """
    from backend.app.agents.supervisor import supervisor_node
    from backend.app.agents.retriever import retriever_node
    from backend.app.agents.summarizer import summarizer_node
    from backend.app.agents.synthesizer import synthesizer_node

    # Create the graph with our state schema
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("summarizer", summarizer_node)
    graph.add_node("synthesizer", synthesizer_node)

    # Entry point — always starts at supervisor
    graph.set_entry_point("supervisor")

    # Conditional routing — supervisor decides where to go
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,   # function that reads the route decision
        {
            "retriever": "retriever",
            "summarizer": "summarizer",
            "synthesizer": "synthesizer",  # go directly if no retrieval needed
        }
    )

    # After retriever or summarizer — always go to synthesizer
    graph.add_edge("retriever", "synthesizer")
    graph.add_edge("summarizer", "synthesizer")

    # Synthesizer is always the last node
    graph.add_edge("synthesizer", END)

    # Compile the graph into a runnable
    return graph.compile()


def route_after_supervisor(state: AgentState) -> str:
    """
    Reads the supervisor's routing decision from state.
    Returns the name of the next node to run.
    """
    route = state.get("route", "retriever")
    logger.info("Routing decision", route=route)
    return route


# Compile once at import time — reused for every query
agent_graph = build_graph()
