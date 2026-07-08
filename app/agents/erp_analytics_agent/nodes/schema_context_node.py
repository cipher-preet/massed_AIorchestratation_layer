import asyncio

from app.agents.erp_analytics_agent.state import AgentState
from app.mcp_client.mcp_tool_registry import get_relationship_map_by_domain, get_schema_catalog_by_domain, list_tools


async def schema_context_node(state: AgentState) -> AgentState:
    try:
        await list_tools()
        schema_domain = state.get("schema_domain") or {}
        domain_name = schema_domain.get("name") if isinstance(schema_domain, dict) else None
        domain_name = domain_name or "general"
        schema_catalog, relationship_map = await asyncio.gather(
            get_schema_catalog_by_domain(domain_name),
            get_relationship_map_by_domain(domain_name),
        )

        tool_calls = list(state.get("tool_calls", []))
        tool_calls.extend(
            [
                {"tool": "get_schema_catalog_by_domain", "arguments": {"domain": domain_name}},
                {"tool": "get_relationship_map_by_domain", "arguments": {"domain": domain_name}},
            ]
        )
        return {
            "schema_domain": schema_domain,
            "schema_catalog": schema_catalog,
            "relationship_map": relationship_map,
            "tool_calls": tool_calls,
        }
    except Exception:
        return {"error": "Could not load ERP schema context."}
