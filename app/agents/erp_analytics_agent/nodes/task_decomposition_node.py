import json

from app.agents.erp_analytics_agent.prompts import TASK_DECOMPOSITION_PROMPT
from app.agents.erp_analytics_agent.state import AgentState
from app.config.settings import settings
from app.core.llm import get_llm
from app.utils.json_utils import extract_json_object


async def task_decomposition_node(state: AgentState) -> AgentState:
    llm = get_llm(model=settings.openai_planner_model)
    prompt_context = {
        "user_message": state["message"],
        "chat_history": (state.get("chat_history") or [])[-10:],
        "conversation_reference": state.get("conversation_reference"),
        "schema_catalog": state.get("schema_catalog"),
        "relationship_map": state.get("relationship_map"),
    }
    try:
        response = await llm.ainvoke(
            [
                ("system", TASK_DECOMPOSITION_PROMPT),
                ("human", json.dumps(prompt_context, default=str)),
            ]
        )
        parsed = extract_json_object(str(response.content))
    except Exception:
        parsed = {
            "complexity": "clarification_needed",
            "recommended_plan_type": "clarification",
            "tasks": [],
            "entities": [],
            "question": "Which ERP data should I use, and what filter or time period should apply?",
            "reason": "The request could not be decomposed safely.",
        }
    return {"task_decomposition": parsed}
