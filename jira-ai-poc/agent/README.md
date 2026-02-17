# JIRA Router Agent

Natural Language → Tool Calls router для JIRA Semantic Layer.

## Архитектура

```
┌─────────────────────────────────────────┐
│           User Query (NL)               │
│  "Show issues for project AUTH"         │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│           Router Agent                   │
│  ┌─────────────────────────────────┐    │
│  │ 1. Intent Detection             │    │
│  │    operational | analytics | mixed   │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │ 2. Parameter Extraction         │    │
│  │    project_id, sprint_id, etc.  │    │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │ 3. Tool Selection               │    │
│  │    VulcanSQL endpoint / Cube query  │
│  └─────────────────────────────────┘    │
└────────────────┬────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
┌───────────────┐ ┌───────────────┐
│  VulcanSQL    │ │    Cube       │
│  (Records)    │ │  (Metrics)    │
│  Port 3001    │ │  Port 4000    │
└───────────────┘ └───────────────┘
```

## Quick Start

### 1. Install dependencies

```bash
cd jira-ai-poc/agent
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env if needed
```

### 3. Run agent

**CLI mode:**
```bash
python agent.py
```

**Web mode:**
```bash
python app.py
# Open http://localhost:8000
```

## Intent Detection

| Intent | Keywords | Tool |
|--------|----------|------|
| `operational` | список, покажи, задачи, комментарии, связи | VulcanSQL |
| `analytics` | сколько, динамика, throughput, velocity, WIP | Cube |
| `mixed` | найди задачи и посчитай, топ авторов + профили | Both |

## 7 Demo Scenarios

| # | Query | Intent | Tool |
|---|-------|--------|------|
| 1 | "Show issues for project AUTH" | operational | VulcanSQL |
| 2 | "Show issue #1 with details" | operational | VulcanSQL |
| 3 | "Search issues containing database" | operational | VulcanSQL |
| 4 | "How many issues resolved by project?" | analytics | Cube |
| 5 | "Show WIP by assignee" | analytics | Cube |
| 6 | "Top authors by worklogs + profiles" | mixed | Cube → VulcanSQL |
| 7 | "Sprint velocity: committed vs completed" | analytics | Cube |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/health` | GET | Health check |
| `/api/demos` | GET | List demo scenarios |
| `/api/query` | POST | Process NL query |

### POST /api/query

Request:
```json
{
  "query": "Show issues for project AUTH",
  "use_semantic_layer": true
}
```

Response:
```json
{
  "query": "Show issues for project AUTH",
  "intent": "operational",
  "steps": [
    {
      "tool_type": "vulcan",
      "endpoint": "/jira/issues",
      "params": {"project_id": 1, "limit": 10},
      "description": "VulcanSQL: list_issues"
    }
  ],
  "results": [...],
  "final_answer": "Found 25 results:\n  1. [AUTH-1] Fix database..."
}
```

## Run Demo Script

```bash
chmod +x demo.sh

# Start agent first
python app.py &

# Run all 7 scenarios
./demo.sh
```

## Files

```
agent/
├── README.md           # This file
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── agent.py            # Core router logic + CLI
├── app.py              # FastAPI web app
└── demo.sh             # Demo script (7 scenarios)
```

## Web UI Features

- 🔍 Natural language input
- 📋 7 demo scenario buttons
- 🔧 Tool calls visualization (steps + endpoints)
- 📊 Results display
- 🎚️ Semantic Layer toggle (on/off comparison)
