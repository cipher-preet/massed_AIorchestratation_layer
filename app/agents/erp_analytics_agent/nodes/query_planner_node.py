import json

from app.agents.erp_analytics_agent.prompts import QUERY_PLANNER_PROMPT
from app.agents.erp_analytics_agent.state import AgentState
from app.core.llm import get_llm
from app.mcp_client.mcp_tool_registry import list_tools
from app.utils.json_utils import extract_json_object


async def query_planner_node(state: AgentState) -> AgentState:
    if state.get("intent") == "schema_question":
        return {
            "query_plan": {
                "tool": "schema_answer",
                "arguments": {},
                "reason": "The user asked about available ERP data schema.",
            }
        }

    llm = get_llm()
    available_tools = await list_tools()
    prompt_context = {
        "user_message": state["message"],
        "chat_history": (state.get("chat_history") or [])[-10:],
        "schema_catalog": state.get("schema_catalog"),
        "relationship_map": state.get("relationship_map"),
        "available_mcp_tools": available_tools,
    }
    response = await llm.ainvoke(
        [
            ("system", QUERY_PLANNER_PROMPT),
            ("human", json.dumps(prompt_context, default=str)),
        ]
    )
    parsed = extract_json_object(str(response.content))
    return {"query_plan": parsed}
