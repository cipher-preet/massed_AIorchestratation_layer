from typing import Any, Dict, List, Optional
from time import monotonic

from app.mcp_client.node_mcp_client import node_mcp_client


_TOOLS_CACHE: List[Dict[str, Any]] | None = None
_TOOLS_CACHE_EXPIRES_AT = 0.0
_TOOLS_CACHE_TTL_SECONDS = 300


async def list_tools() -> List[Dict[str, Any]]:
    global _TOOLS_CACHE, _TOOLS_CACHE_EXPIRES_AT

    now = monotonic()
    if _TOOLS_CACHE is not None and now < _TOOLS_CACHE_EXPIRES_AT:
        return _TOOLS_CACHE

    _TOOLS_CACHE = await node_mcp_client.list_tools()
    _TOOLS_CACHE_EXPIRES_AT = now + _TOOLS_CACHE_TTL_SECONDS
    return _TOOLS_CACHE


async def _has_tool(tool_name: str) -> bool:
    tools = await list_tools()
    return any(tool.get("name") == tool_name for tool in tools)


async def get_schema_catalog() -> Dict[str, Any]:
    return await node_mcp_client.call_tool("get_schema_catalog", {})


async def get_schema_catalog_by_domain(domain: str) -> Dict[str, Any]:
    if await _has_tool("get_schema_catalog_by_domain"):
        return await node_mcp_client.call_tool("get_schema_catalog_by_domain", {"domain": domain})
    if await _has_tool("get_schema_catalog_for_domain"):
        return await node_mcp_client.call_tool("get_schema_catalog_for_domain", {"domain": domain})
    return await get_schema_catalog()


async def get_relationship_map() -> Dict[str, Any]:
    return await node_mcp_client.call_tool("get_relationship_map", {})


async def get_relationship_map_by_domain(domain: str) -> Dict[str, Any]:
    if await _has_tool("get_relationship_map_by_domain"):
        return await node_mcp_client.call_tool("get_relationship_map_by_domain", {"domain": domain})
    if await _has_tool("get_relationship_map_for_domain"):
        return await node_mcp_client.call_tool("get_relationship_map_for_domain", {"domain": domain})
    return await get_relationship_map()


async def describe_collection(collectionName: str) -> Dict[str, Any]:
    return await node_mcp_client.call_tool("describe_collection", {"collectionName": collectionName})


async def run_find_query(
    collectionName: str,
    filter: Optional[Dict[str, Any]] = None,
    projection: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    return await node_mcp_client.call_tool(
        "run_find_query",
        {
            "collectionName": collectionName,
            "filter": filter or {},
            "projection": projection or {},
            "sort": sort or {},
            "limit": limit,
        },
    )


async def run_aggregation_query(collectionName: str, pipeline: List[Dict[str, Any]], limit: int = 100) -> Dict[str, Any]:
    return await node_mcp_client.call_tool(
        "run_aggregation_query",
        {"collectionName": collectionName, "pipeline": pipeline, "limit": limit},
    )


async def call_registered_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    allowed_tools = {
        "get_schema_catalog": get_schema_catalog,
        "get_schema_catalog_by_domain": get_schema_catalog_by_domain,
        "get_relationship_map": get_relationship_map,
        "get_relationship_map_by_domain": get_relationship_map_by_domain,
        "describe_collection": describe_collection,
        "run_find_query": run_find_query,
        "run_aggregation_query": run_aggregation_query,
    }
    if tool_name not in allowed_tools:
        raise ValueError(f"Unsupported MCP tool: {tool_name}")
    return await allowed_tools[tool_name](**arguments)
