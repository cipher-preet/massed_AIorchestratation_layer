import asyncio

from app.agents.erp_analytics_agent.state import AgentState
from app.mcp_client.mcp_tool_registry import get_relationship_map, get_schema_catalog, list_tools


async def schema_context_node(state: AgentState) -> AgentState:
    try:
        
        tools_list = await list_tools()
        print("this is tools list data --------------- ", tools_list)
        
        schema_catalog, relationship_map = await asyncio.gather(
            get_schema_catalog(),
            get_relationship_map(),
        )

        # print("this is schema catalog data ****************", schema_catalog)
        # print("this is relationship map data *************** ", relationship_map)
        
        tool_calls = list(state.get("tool_calls", []))
        
        print("this is tool call data ---->> ", tool_calls)
        
        tool_calls.extend(
            [
                {"tool": "get_schema_catalog", "arguments": {}},
                {"tool": "get_relationship_map", "arguments": {}},
            ]
        )
        return {
            "schema_catalog": schema_catalog,
            "relationship_map": relationship_map,
            "tool_calls": tool_calls,
        }
    except Exception:
        return {"error": "Could not load ERP schema context."}
