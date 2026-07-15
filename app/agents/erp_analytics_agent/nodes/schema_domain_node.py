import re
from typing import Any

from app.agents.erp_analytics_agent.state import AgentState


DOMAIN_RULES = [
    {
        "name": "technician_hr",
        "description": "Technicians, employees, users, roles, designations, attendance, leave, salary, branch assignment.",
        "keywords": {
            "technician",
            "technicians",
            "engineer",
            "engineers",
            "employee",
            "employees",
            "user",
            "users",
            "designation",
            "designations",
            "role",
            "roles",
            "attendance",
            "leave",
            "salary",
            "branch",
            "staff",
            "hr",
        },
    },
    {
        "name": "service_operations",
        "description": "Services, tickets, complaints, jobs, work orders, visits, schedules, assignments.",
        "keywords": {
            "service",
            "services",
            "ticket",
            "tickets",
            "complaint",
            "complaints",
            "job",
            "jobs",
            "work",
            "visit",
            "visits",
            "schedule",
            "assigned",
            "assignment",
            "maintenance",
            "installation",
        },
    },
    {
        "name": "customers_locations",
        "description": "Clients, customers, sites, areas, branches, locations, contacts, addresses.",
        "keywords": {
            "client",
            "clients",
            "customer",
            "customers",
            "site",
            "sites",
            "area",
            "areas",
            "location",
            "locations",
            "address",
            "contact",
            "contacts",
            "branch",
            "branches",
        },
    },
    {
        "name": "finance_inventory",
        "description": "Invoices, payments, sales, purchases, products, inventory, stock, vendors.",
        "keywords": {
            "invoice",
            "invoices",
            "payment",
            "payments",
            "sale",
            "sales",
            "purchase",
            "purchases",
            "product",
            "products",
            "inventory",
            "stock",
            "vendor",
            "vendors",
            "amount",
            "revenue",
            "outstanding",
            "membership",
            "memberships",
            "plan",
            "plans",
            "benefit",
            "benefits",
            "amc",
        },
    },
]


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", value.lower()))


def _history_text(history: list[dict[str, Any]]) -> str:
    chunks = []
    for item in history[-4:]:
        content = item.get("content")
        if isinstance(content, str):
            chunks.append(content)
    return " ".join(chunks)


async def schema_domain_node(state: AgentState) -> AgentState:
    message = state.get("message", "")
    history = state.get("chat_history") or []
    token_set = _tokens(f"{_history_text(history)} {message}")

    scores = []
    for rule in DOMAIN_RULES:
        matched = sorted(token_set & rule["keywords"])
        if matched:
            scores.append((len(matched), rule, matched))

    if not scores:
        domain = {
            "name": "general",
            "description": "Use a compact global schema summary because no specific ERP domain was detected.",
            "matchedKeywords": [],
            "confidence": "low",
        }
    else:
        scores.sort(key=lambda item: item[0], reverse=True)
        _, rule, matched = scores[0]
        domain = {
            "name": rule["name"],
            "description": rule["description"],
            "matchedKeywords": matched,
            "confidence": "high" if len(matched) >= 2 else "medium",
        }

    return {"schema_domain": domain}
