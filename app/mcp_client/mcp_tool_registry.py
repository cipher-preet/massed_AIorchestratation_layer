from typing import Any, Dict, List, Optional

from app.mcp_client.node_mcp_client import node_mcp_client


async def list_tools() -> List[Dict[str, Any]]:
    return await node_mcp_client.list_tools()


async def get_schema_catalog() -> Dict[str, Any]:
    return await node_mcp_client.call_tool("get_schema_catalog", {})


async def get_relationship_map() -> Dict[str, Any]:
    return await node_mcp_client.call_tool("get_relationship_map", {})


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
        "get_relationship_map": get_relationship_map,
        "describe_collection": describe_collection,
        "run_find_query": run_find_query,
        "run_aggregation_query": run_aggregation_query,
    }
    if tool_name not in allowed_tools:
        raise ValueError(f"Unsupported MCP tool: {tool_name}")
    return await allowed_tools[tool_name](**arguments)
