from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.erp_analytics_agent.nodes.conversation_reference_node import conversation_reference_node
from app.agents.erp_analytics_agent.nodes.intent_node import intent_node
from app.agents.erp_analytics_agent.nodes.query_planner_node import query_planner_node
from app.agents.erp_analytics_agent.nodes.response_formatter_node import response_formatter_node
from app.agents.erp_analytics_agent.nodes.result_verifier_node import result_verifier_node
from app.agents.erp_analytics_agent.nodes.schema_context_node import schema_context_node
from app.agents.erp_analytics_agent.nodes.task_decomposition_node import task_decomposition_node
from app.agents.erp_analytics_agent.nodes.tool_execution_node import tool_execution_node
from app.agents.erp_analytics_agent.state import AgentState


def route_after_intent(state: AgentState) -> str:
    if state.get("intent") in {"clarification_needed", "unsupported", "conversation_response"} or state.get("error"):
        return "response_formatter_node"
    return "schema_context_node"


def route_after_schema(state: AgentState) -> str:
    if state.get("error"):
        return "response_formatter_node"
    if state.get("intent") == "schema_question":
        return "query_planner_node"
    return "task_decomposition_node"


def route_after_decomposition(state: AgentState) -> str:
    if state.get("error"):
        return "response_formatter_node"
    if state.get("task_decomposition", {}).get("complexity") == "clarification_needed":
        return "response_formatter_node"
    return "query_planner_node"


def route_after_planner(state: AgentState) -> str:
    if state.get("error"):
        return "response_formatter_node"
    if state.get("query_plan", {}).get("tool") in {"clarification_needed", "schema_answer"}:
        return "response_formatter_node"
    return "tool_execution_node"


def route_after_execution(state: AgentState) -> str:
    if state.get("error"):
        return "response_formatter_node"
    return "result_verifier_node"


checkpointer = MemorySaver()


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("conversation_reference_node", conversation_reference_node)
    graph.add_node("intent_node", intent_node)
    graph.add_node("schema_context_node", schema_context_node)
    graph.add_node("task_decomposition_node", task_decomposition_node)
    graph.add_node("query_planner_node", query_planner_node)
    graph.add_node("tool_execution_node", tool_execution_node)
    graph.add_node("result_verifier_node", result_verifier_node)
    graph.add_node("response_formatter_node", response_formatter_node)

    graph.add_edge(START, "conversation_reference_node")
    graph.add_edge("conversation_reference_node", "intent_node")
    graph.add_conditional_edges("intent_node", route_after_intent)
    graph.add_conditional_edges("schema_context_node", route_after_schema)
    graph.add_conditional_edges("task_decomposition_node", route_after_decomposition)
    graph.add_conditional_edges("query_planner_node", route_after_planner)
    graph.add_conditional_edges("tool_execution_node", route_after_execution)
    graph.add_edge("result_verifier_node", "response_formatter_node")
    graph.add_edge("response_formatter_node", END)
    return graph.compile(checkpointer=checkpointer)


erp_analytics_graph = build_graph()
