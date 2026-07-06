# ERP AI Orchestration Backend

Scalable FastAPI + LangGraph backend for a generic ERP AI analytics assistant.

Architecture:

```text
React ERP Chat
  -> FastAPI /api/v1/ai/chat
  -> LangGraph Agent
  -> MCP Client
  -> Local Node.js MCP Server
  -> MongoDB read-only analytics data
```

The backend stays generic: ERP-specific knowledge comes from the Node MCP server through schema catalog and relationship map tools.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill `.env`:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=
NODE_MCP_SERVER_COMMAND=node
NODE_MCP_SERVER_CWD=D:/massedErpAgent/nodejsserver
NODE_MCP_SERVER_PATH=dist/server.js
AI_MAX_RETRIES=2
AI_TIMEOUT_SECONDS=60
API_CORS_ORIGINS=*
```

`OPENAI_BASE_URL` is optional. Set it when using an OpenAI-compatible provider.

## Run The Node MCP Server

Build and run your existing MCP server from its project directory. The FastAPI MCP client uses stdio and starts the configured command automatically:

```env
NODE_MCP_SERVER_COMMAND=node
NODE_MCP_SERVER_CWD=D:/massedErpAgent/nodejsserver
NODE_MCP_SERVER_PATH=dist/server.js
```

The MCP server should expose read-only tools such as:

- `list_collections`
- `describe_collection`
- `get_schema_catalog`
- `get_relationship_map`
- `run_find_query`
- `run_aggregation_query`

## Run FastAPI

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/api/v1/health
```

## Chat API

`POST /api/v1/ai/chat`

Request:

```json
{
  "userId": "user-1",
  "spaceId": "space-1",
  "message": "Show total sales by month this year",
  "conversationId": "optional-conversation-id"
}
```

Response:

```json
{
  "success": true,
  "answer": "| Month | Sales |\n|---|---|\n| Jan | 1000 |",
  "toolCalls": [],
  "metadata": {
    "conversationId": "optional-conversation-id",
    "intent": "analytics_query",
    "queryPlan": {}
  },
  "error": null
}
```

## Example Analytics Query

```bash
curl -X POST http://localhost:8000/api/v1/ai/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"userId\":\"u1\",\"spaceId\":\"s1\",\"message\":\"Which customers have the highest outstanding invoices?\"}"
```

## Agent Flow

```text
START
  -> IntentNode
  -> SchemaContextNode
  -> QueryPlannerNode
  -> ToolExecutionNode
  -> ResultVerifierNode
  -> ResponseFormatterNode
  -> END
```

Conditional routes send clarification, unsupported requests, and safe errors directly to the response formatter.

## Safety Rules

- Read-only analytics only.
- MongoDB data exposed by MCP tools is the source of truth.
- The planner must use schema catalog fields and relationship map context.
- The backend returns safe errors and does not expose stack traces.
