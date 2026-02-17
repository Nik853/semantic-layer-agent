"""
JIRA Orchestrator Agent - FastAPI Web Interface
Tool-based orchestrator without SQL generation
"""

import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

from orchestrator_agent import OrchestratorAgent
from function_registry import get_registry, ToolType

load_dotenv()

app = FastAPI(title="JIRA Orchestrator Agent", version="3.0.0")

# Global agent instance
_agent: Optional[OrchestratorAgent] = None

def get_agent() -> OrchestratorAgent:
    global _agent
    if _agent is None:
        _agent = OrchestratorAgent()
    return _agent


class QueryRequest(BaseModel):
    query: str


class ToolCallResponse(BaseModel):
    tool_name: str
    tool_type: str
    endpoint: str
    params: Dict[str, Any]
    description: str


class AgentResponseModel(BaseModel):
    query: str
    intent: str
    selected_tool: Optional[str] = None
    tool_params: Dict[str, Any] = {}
    steps: List[ToolCallResponse] = []
    results: List[Dict[str, Any]] = []
    final_answer: str = ""
    error: Optional[str] = None
    total_duration_ms: int = 0


# ============================================
# API Endpoints
# ============================================

@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the web interface"""
    return HTML_TEMPLATE


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "jira-orchestrator-agent", "version": "3.0.0"}


@app.get("/api/tools")
async def get_tools():
    """Get all registered tools"""
    registry = get_registry()
    tools = []
    for tool in registry.get_all_tools():
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "type": tool.tool_type.value,
            "endpoint": tool.endpoint,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default
                }
                for p in tool.parameters
            ],
            "examples": tool.examples[:3],
            "keywords": tool.keywords[:5]
        })
    return {"tools": tools, "count": len(tools)}


@app.get("/api/demos")
async def get_demos():
    """Get demo scenarios"""
    return {
        "demos": [
            {"id": 1, "query": "Сколько задач по проектам?", "type": "analytics"},
            {"id": 2, "query": "Покажи задачи проекта AUTH", "type": "operational"},
            {"id": 3, "query": "Покажи задачу AUTH-1", "type": "detail"},
            {"id": 4, "query": "Топ по залогированному времени", "type": "analytics"},
            {"id": 5, "query": "WIP по исполнителям", "type": "analytics"},
            {"id": 6, "query": "Velocity спринтов", "type": "analytics"},
            {"id": 7, "query": "Список проектов", "type": "operational"},
        ]
    }


@app.post("/api/query", response_model=AgentResponseModel)
async def process_query(request: QueryRequest):
    """Process natural language query"""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    agent = get_agent()
    response = agent.process(request.query)
    
    return AgentResponseModel(
        query=response.query,
        intent=response.intent,
        selected_tool=response.selected_tool,
        tool_params=response.tool_params,
        steps=[
            ToolCallResponse(
                tool_name=s.tool_name,
                tool_type=s.tool_type,
                endpoint=s.endpoint,
                params=s.params,
                description=s.description
            )
            for s in response.steps
        ],
        results=response.results,
        final_answer=response.final_answer,
        error=response.error,
        total_duration_ms=response.total_duration_ms
    )


# ============================================
# HTML Template
# ============================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>JIRA Orchestrator Agent</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 {
            text-align: center;
            color: #00d4ff;
            margin-bottom: 10px;
            font-size: 2rem;
        }
        .subtitle {
            text-align: center;
            color: #888;
            margin-bottom: 30px;
        }
        .input-section {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .input-row {
            display: flex;
            gap: 10px;
        }
        input[type="text"] {
            flex: 1;
            padding: 15px 20px;
            font-size: 16px;
            border: 2px solid #333;
            border-radius: 8px;
            background: #1a1a2e;
            color: #fff;
            outline: none;
        }
        input[type="text"]:focus { border-color: #00d4ff; }
        button {
            padding: 15px 30px;
            font-size: 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-primary {
            background: linear-gradient(135deg, #00d4ff, #7c3aed);
            color: #fff;
        }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(0,212,255,0.4); }
        .demos {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 15px;
        }
        .demo-btn {
            background: rgba(255,255,255,0.1);
            color: #ccc;
            padding: 8px 15px;
            font-size: 13px;
            border-radius: 20px;
        }
        .demo-btn:hover { background: rgba(0,212,255,0.2); color: #00d4ff; }
        .results {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        @media (max-width: 900px) { .results { grid-template-columns: 1fr; } }
        .card {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px;
        }
        .card h3 {
            color: #00d4ff;
            margin-bottom: 15px;
            font-size: 1rem;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .intent-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .intent-analytics { background: linear-gradient(135deg, #7c3aed, #00d4ff); }
        .intent-operational { background: #10b981; }
        .intent-detail { background: #f59e0b; }
        .tool-card {
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 10px;
        }
        .tool-name {
            color: #00d4ff;
            font-weight: 600;
            margin-bottom: 5px;
        }
        .tool-type {
            display: inline-block;
            padding: 2px 8px;
            background: rgba(0,212,255,0.2);
            border-radius: 4px;
            font-size: 11px;
            margin-left: 8px;
        }
        .params {
            font-family: monospace;
            font-size: 12px;
            background: rgba(0,0,0,0.3);
            padding: 8px;
            border-radius: 4px;
            margin-top: 8px;
            overflow-x: auto;
        }
        .answer {
            white-space: pre-wrap;
            font-family: monospace;
            font-size: 14px;
            line-height: 1.6;
            background: rgba(0,0,0,0.2);
            padding: 15px;
            border-radius: 8px;
            max-height: 400px;
            overflow-y: auto;
        }
        .stats {
            display: flex;
            gap: 20px;
            margin-top: 15px;
            font-size: 13px;
            color: #888;
        }
        .stat { display: flex; align-items: center; gap: 5px; }
        .loading {
            text-align: center;
            padding: 40px;
            color: #00d4ff;
        }
        .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid #333;
            border-top-color: #00d4ff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .hidden { display: none; }
        .error { color: #ef4444; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 JIRA Orchestrator Agent</h1>
        <p class="subtitle">Tool-based query router • No SQL generation • Pure orchestration</p>
        
        <div class="input-section">
            <div class="input-row">
                <input type="text" id="query" placeholder="Ask a question about JIRA data..." />
                <button class="btn-primary" onclick="submitQuery()">Ask</button>
            </div>
            <div class="demos" id="demos"></div>
        </div>
        
        <div id="loading" class="loading hidden">
            <div class="spinner"></div>
            <div>Processing query...</div>
        </div>
        
        <div id="results" class="results hidden">
            <div class="card">
                <h3>🔧 Tool Selection</h3>
                <div id="intent"></div>
                <div id="tool-info"></div>
            </div>
            <div class="card">
                <h3>📝 Answer</h3>
                <div id="answer" class="answer"></div>
                <div id="stats" class="stats"></div>
            </div>
        </div>
    </div>
    
    <script>
        async function loadDemos() {
            const resp = await fetch('/api/demos');
            const data = await resp.json();
            const container = document.getElementById('demos');
            container.innerHTML = data.demos.map(d => 
                `<button class="demo-btn" onclick="runDemo('${d.query.replace(/'/g, "\\'")}')">${d.query}</button>`
            ).join('');
        }
        
        function runDemo(query) {
            document.getElementById('query').value = query;
            submitQuery();
        }
        
        async function submitQuery() {
            const query = document.getElementById('query').value.trim();
            if (!query) return;
            
            document.getElementById('loading').classList.remove('hidden');
            document.getElementById('results').classList.add('hidden');
            
            try {
                const resp = await fetch('/api/query', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({query})
                });
                
                const data = await resp.json();
                displayResults(data);
            } catch (e) {
                document.getElementById('answer').innerHTML = `<span class="error">Error: ${e.message}</span>`;
            }
            
            document.getElementById('loading').classList.add('hidden');
            document.getElementById('results').classList.remove('hidden');
        }
        
        function displayResults(data) {
            // Intent
            const intentClass = data.intent === 'analytics' ? 'intent-analytics' : 
                               data.intent === 'detail' ? 'intent-detail' : 'intent-operational';
            document.getElementById('intent').innerHTML = 
                `<span class="intent-badge ${intentClass}">${data.intent.toUpperCase()}</span>`;
            
            // Tool info
            let toolHtml = '';
            if (data.selected_tool) {
                toolHtml = `<div class="tool-card">
                    <div class="tool-name">${data.selected_tool}
                        <span class="tool-type">${data.steps[0]?.tool_type || ''}</span>
                    </div>
                    <div>Endpoint: ${data.steps[0]?.endpoint || ''}</div>
                    <div class="params">${JSON.stringify(data.tool_params, null, 2)}</div>
                </div>`;
            }
            document.getElementById('tool-info').innerHTML = toolHtml;
            
            // Answer
            document.getElementById('answer').textContent = data.final_answer || 'No answer';
            
            // Stats
            document.getElementById('stats').innerHTML = `
                <div class="stat">⏱️ ${data.total_duration_ms}ms</div>
                ${data.error ? `<div class="stat error">⚠️ ${data.error}</div>` : ''}
            `;
        }
        
        document.getElementById('query').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') submitQuery();
        });
        
        loadDemos();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
