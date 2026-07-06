from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None


class AgentResult(BaseModel):
    answer: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
