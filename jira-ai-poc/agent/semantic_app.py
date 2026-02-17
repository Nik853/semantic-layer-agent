"""
JIRA Semantic Agent - FastAPI Web Interface
LLM-powered query generation using Cube metadata
With detailed pipeline logging
"""

import os
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

# Use Universal Agent with config-driven architecture
from universal_agent import UniversalSemanticAgent as SemanticAgent

load_dotenv()

app = FastAPI(title="JIRA Semantic Agent", version="2.0.0")

# Global agent instance (initialized on first request)
_agent: Optional[SemanticAgent] = None

def get_agent() -> SemanticAgent:
    global _agent
    if _agent is None:
        _agent = SemanticAgent()
    return _agent


class QueryRequest(BaseModel):
    query: str
    llm_provider: Optional[str] = None  # "openai" or "gigachat"


class LogEntryResponse(BaseModel):
    timestamp: str
    step: str
    type: str
    message: str
    data: Optional[Dict] = None
    duration_ms: Optional[int] = None


class ToolCallResponse(BaseModel):
    tool_type: str
    endpoint: str
    params: Dict[str, Any]
    description: str


class AgentResponseModel(BaseModel):
    query: str
    intent: str
    relevant_members: List[str]
    generated_cube_query: Optional[Dict] = None
    steps: List[ToolCallResponse]
    results: List[Dict[str, Any]]
    final_answer: str
    error: Optional[str] = None
    # NEW: Detailed logs
    logs: List[LogEntryResponse]
    llm_prompt: Optional[str] = None
    llm_response: Optional[str] = None
    cube_sql: Optional[str] = None
    total_duration_ms: int = 0
    # LLM Provider info
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None


# ============================================
# API Endpoints
# ============================================

@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the web interface"""
    return HTML_TEMPLATE


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "jira-semantic-agent", "version": "2.1.0"}


@app.get("/api/providers")
async def get_providers():
    """Get available LLM providers"""
    agent = get_agent()
    return agent.get_current_provider()


@app.get("/api/meta")
async def get_meta():
    """Get Cube metadata summary"""
    agent = get_agent()
    members = agent.metadata_loader.members
    
    cubes = {}
    for m in members:
        if m.cube_name not in cubes:
            cubes[m.cube_name] = {"measures": [], "dimensions": []}
        if m.member_type == "measure":
            cubes[m.cube_name]["measures"].append(m.name)
        else:
            cubes[m.cube_name]["dimensions"].append(m.name)
    
    return {
        "total_members": len(members),
        "cubes": cubes
    }


@app.post("/api/query", response_model=AgentResponseModel)
async def process_query(request: QueryRequest):
    """Process natural language query using semantic search + LLM"""
    try:
        agent = get_agent()
        
        # Switch LLM provider if specified
        if request.llm_provider:
            try:
                agent.set_llm_provider(request.llm_provider)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        response = agent.process(request.query)
        
        # Get current provider info
        provider_info = agent.get_current_provider()
        
        return AgentResponseModel(
            query=response.query,
            intent=response.intent,
            relevant_members=response.relevant_members,
            generated_cube_query=response.generated_cube_query,
            steps=[
                ToolCallResponse(
                    tool_type=s.tool_type,
                    endpoint=s.endpoint,
                    params=s.params,
                    description=s.description
                ) for s in response.steps
            ],
            results=response.results,
            final_answer=response.final_answer,
            error=response.error,
            logs=[
                LogEntryResponse(
                    timestamp=log.timestamp,
                    step=log.step,
                    type=log.type,
                    message=log.message,
                    data=log.data,
                    duration_ms=log.duration_ms
                ) for log in response.logs
            ],
            llm_prompt=response.llm_prompt,
            llm_response=response.llm_response,
            cube_sql=response.cube_sql,
            total_duration_ms=response.total_duration_ms,
            llm_provider=provider_info["provider"],
            llm_model=provider_info["model"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/search")
async def semantic_search(request: QueryRequest):
    """Search for relevant Cube members"""
    agent = get_agent()
    results = agent.vector_store.search(request.query, k=15)
    return {"query": request.query, "results": results}


# ============================================
# HTML Template
# ============================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JIRA Semantic Agent</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1600px; margin: 0 auto; }
        h1 { 
            text-align: center; 
            margin-bottom: 10px;
            background: linear-gradient(135deg, #00d4ff, #7c3aed);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-size: 2.2em;
        }
        .subtitle {
            text-align: center;
            color: #888;
            margin-bottom: 30px;
        }
        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            margin-left: 10px;
            background: #7c3aed;
            color: white;
        }
        .input-section {
            background: rgba(255,255,255,0.03);
            padding: 25px;
            border-radius: 16px;
            margin-bottom: 25px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .query-input {
            width: 100%;
            padding: 16px 20px;
            border: 2px solid rgba(124,58,237,0.3);
            border-radius: 12px;
            background: rgba(0,0,0,0.3);
            color: #fff;
            font-size: 16px;
            margin-bottom: 15px;
            transition: all 0.3s;
        }
        .query-input:focus {
            outline: none;
            border-color: #7c3aed;
            box-shadow: 0 0 20px rgba(124,58,237,0.2);
        }
        .btn-row {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .btn {
            padding: 12px 28px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.2s;
        }
        .btn-primary {
            background: linear-gradient(135deg, #7c3aed 0%, #00d4ff 100%);
            color: #fff;
        }
        .btn-primary:hover { 
            transform: translateY(-2px); 
            box-shadow: 0 8px 20px rgba(124,58,237,0.4); 
        }
        .btn-secondary {
            background: rgba(255,255,255,0.1);
            color: #fff;
        }
        .btn-secondary:hover { background: rgba(255,255,255,0.15); }
        
        /* Model Selector Styles */
        .model-selector {
            display: flex;
            align-items: center;
            gap: 15px;
            margin-top: 15px;
            padding: 12px 15px;
            background: rgba(255,255,255,0.03);
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.08);
        }
        .model-selector label {
            font-size: 13px;
            color: #888;
        }
        .model-buttons {
            display: flex;
            gap: 8px;
        }
        .model-btn {
            padding: 8px 18px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            border: 2px solid transparent;
            transition: all 0.2s;
            background: rgba(255,255,255,0.05);
            color: #888;
        }
        .model-btn:hover {
            background: rgba(255,255,255,0.1);
            color: #fff;
        }
        .model-btn.active {
            border-color: #7c3aed;
            background: rgba(124,58,237,0.2);
            color: #fff;
        }
        .model-btn.openai.active {
            border-color: #10b981;
            background: rgba(16,185,129,0.2);
        }
        .model-btn.gigachat.active {
            border-color: #f59e0b;
            background: rgba(245,158,11,0.2);
        }
        .model-indicator {
            font-size: 11px;
            padding: 4px 10px;
            border-radius: 12px;
            margin-left: auto;
        }
        .model-indicator.openai {
            background: rgba(16,185,129,0.2);
            color: #10b981;
        }
        .model-indicator.gigachat {
            background: rgba(245,158,11,0.2);
            color: #f59e0b;
        }
        
        .demos {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 20px;
        }
        .demo-btn {
            padding: 8px 16px;
            background: rgba(124,58,237,0.1);
            border: 1px solid rgba(124,58,237,0.3);
            border-radius: 20px;
            color: #b794f6;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }
        .demo-btn:hover {
            background: rgba(124,58,237,0.2);
            border-color: #7c3aed;
            transform: translateY(-1px);
        }
        .results-section {
            display: grid;
            grid-template-columns: 350px 1fr 400px;
            gap: 20px;
        }
        @media (max-width: 1200px) {
            .results-section { grid-template-columns: 1fr; }
        }
        .panel {
            background: rgba(255,255,255,0.03);
            border-radius: 16px;
            padding: 20px;
            border: 1px solid rgba(255,255,255,0.08);
        }
        .panel h3 {
            color: #b794f6;
            margin-bottom: 15px;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .intent-badge {
            display: inline-block;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            margin-bottom: 15px;
        }
        .intent-analytics { background: linear-gradient(135deg, #7c3aed, #00d4ff); color: #fff; }
        .intent-detail { background: #10b981; color: #fff; }
        .members-list {
            font-size: 11px;
            color: #888;
            margin-bottom: 15px;
            padding: 10px;
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
            max-height: 100px;
            overflow-y: auto;
        }
        .cube-query {
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 11px;
            background: rgba(0,0,0,0.4);
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 15px;
            max-height: 200px;
            overflow-y: auto;
            border-left: 3px solid #7c3aed;
        }
        .step {
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            padding: 14px;
            margin-bottom: 10px;
            border-left: 3px solid #00d4ff;
        }
        .step-title { 
            font-weight: 600; 
            margin-bottom: 6px;
            color: #fff;
        }
        .step-endpoint { 
            font-family: monospace; 
            font-size: 11px; 
            color: #888;
            word-break: break-all;
        }
        .output {
            background: rgba(0,0,0,0.4);
            border-radius: 12px;
            padding: 20px;
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 13px;
            white-space: pre-wrap;
            max-height: 400px;
            overflow-y: auto;
            line-height: 1.6;
            border: 1px solid rgba(255,255,255,0.05);
        }
        .loading {
            text-align: center;
            padding: 50px;
            color: #888;
        }
        .spinner {
            width: 50px;
            height: 50px;
            border: 3px solid rgba(124,58,237,0.2);
            border-top-color: #7c3aed;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .hidden { display: none; }
        .error { color: #f87171; }
        
        /* Log Panel Styles */
        .log-panel {
            max-height: 700px;
            overflow-y: auto;
        }
        .log-entry {
            padding: 10px 12px;
            margin-bottom: 8px;
            border-radius: 8px;
            font-size: 12px;
            border-left: 3px solid #555;
            background: rgba(0,0,0,0.3);
        }
        .log-entry.log-info { border-left-color: #60a5fa; }
        .log-entry.log-llm { border-left-color: #f59e0b; background: rgba(245,158,11,0.1); }
        .log-entry.log-cube { border-left-color: #10b981; background: rgba(16,185,129,0.1); }
        .log-entry.log-sql { border-left-color: #8b5cf6; background: rgba(139,92,246,0.1); }
        .log-entry.log-error { border-left-color: #ef4444; background: rgba(239,68,68,0.1); }
        .log-entry.log-success { border-left-color: #22c55e; background: rgba(34,197,94,0.1); }
        
        .log-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 6px;
        }
        .log-step {
            font-weight: 600;
            color: #fff;
        }
        .log-time {
            color: #888;
            font-size: 11px;
        }
        .log-duration {
            color: #00d4ff;
            font-size: 11px;
            font-weight: 600;
        }
        .log-message {
            color: #ccc;
            margin-bottom: 6px;
        }
        .log-data {
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 10px;
            color: #888;
            background: rgba(0,0,0,0.3);
            padding: 8px;
            border-radius: 4px;
            max-height: 150px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }
        
        .sql-panel {
            margin-top: 15px;
        }
        .sql-code {
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 11px;
            background: rgba(139,92,246,0.1);
            padding: 12px;
            border-radius: 8px;
            border-left: 3px solid #8b5cf6;
            max-height: 200px;
            overflow-y: auto;
            white-space: pre-wrap;
            color: #e9d5ff;
        }
        
        .llm-panel {
            margin-top: 15px;
        }
        .llm-section {
            margin-bottom: 12px;
        }
        .llm-label {
            font-size: 11px;
            color: #f59e0b;
            margin-bottom: 5px;
            font-weight: 600;
        }
        .llm-content {
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 10px;
            background: rgba(245,158,11,0.1);
            padding: 10px;
            border-radius: 6px;
            max-height: 150px;
            overflow-y: auto;
            white-space: pre-wrap;
            color: #fcd34d;
        }
        
        .duration-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            background: rgba(0,212,255,0.2);
            color: #00d4ff;
            margin-left: 10px;
        }
        
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 15px;
        }
        .tab {
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            background: rgba(255,255,255,0.05);
            color: #888;
            border: none;
            transition: all 0.2s;
        }
        .tab.active {
            background: rgba(124,58,237,0.3);
            color: #fff;
        }
        .tab:hover {
            background: rgba(124,58,237,0.2);
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🧠 JIRA Semantic Agent <span class="badge">v2.1 LLM</span></h1>
        <p class="subtitle">Natural Language → Semantic Search → LLM Query Generation → Cube/VulcanSQL</p>
        
        <div class="input-section">
            <input type="text" class="query-input" id="queryInput" 
                   placeholder="Задай вопрос на естественном языке... (напр. 'Сколько задач по проектам?')"
                   onkeypress="if(event.key==='Enter')sendQuery()">
            
            <div class="btn-row">
                <button class="btn btn-primary" onclick="sendQuery()">🔍 Analyze Query</button>
                <button class="btn btn-secondary" onclick="clearAll()">🗑️ Clear</button>
            </div>
            
            <div class="model-selector">
                <label>🤖 LLM Model:</label>
                <div class="model-buttons">
                    <button class="model-btn openai active" onclick="selectModel('openai')" id="btn-openai">
                        OpenAI GPT-4o
                    </button>
                    <button class="model-btn gigachat" onclick="selectModel('gigachat')" id="btn-gigachat">
                        GigaChat
                    </button>
                </div>
                <span class="model-indicator openai" id="modelIndicator">OpenAI</span>
            </div>
            
            <div class="demos" id="demos"></div>
        </div>
        
        <div class="results-section">
            <div class="panel">
                <h3>🔧 Pipeline</h3>
                <div id="intentBadge"></div>
                <div id="members"></div>
                <div id="cubeQuery"></div>
                <div id="steps"></div>
            </div>
            
            <div class="panel">
                <h3>📊 Results <span class="duration-badge" id="totalDuration"></span></h3>
                <div class="output" id="output">Введите запрос для анализа...</div>
            </div>
            
            <div class="panel log-panel">
                <h3>📋 Pipeline Logs</h3>
                <div class="tabs">
                    <button class="tab active" onclick="showTab('logs')">Logs</button>
                    <button class="tab" onclick="showTab('sql')">SQL</button>
                    <button class="tab" onclick="showTab('llm')">LLM</button>
                </div>
                
                <div id="logsTab" class="tab-content active">
                    <div id="logEntries">
                        <div style="color: #888; text-align: center; padding: 30px;">
                            Logs will appear here after query execution
                        </div>
                    </div>
                </div>
                
                <div id="sqlTab" class="tab-content">
                    <div class="sql-panel">
                        <h4 style="color: #8b5cf6; font-size: 12px; margin-bottom: 10px;">💾 Generated SQL Query</h4>
                        <div class="sql-code" id="sqlCode">No SQL generated yet</div>
                    </div>
                </div>
                
                <div id="llmTab" class="tab-content">
                    <div class="llm-panel">
                        <div class="llm-section">
                            <div class="llm-label">📤 LLM Prompt</div>
                            <div class="llm-content" id="llmPrompt">No prompt yet</div>
                        </div>
                        <div class="llm-section">
                            <div class="llm-label">📥 LLM Response</div>
                            <div class="llm-content" id="llmResponse">No response yet</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="loading hidden" id="loading">
            <div class="spinner"></div>
            <p>🧠 Analyzing query with LLM...</p>
        </div>
    </div>
    
    <script>
        // Current LLM provider
        let currentProvider = 'openai';
        let availableProviders = ['openai'];
        
        // Load available providers on page load
        async function loadProviders() {
            try {
                const response = await fetch('/api/providers');
                const data = await response.json();
                availableProviders = data.available_providers || ['openai'];
                currentProvider = data.provider || 'openai';
                
                // Update UI based on available providers
                updateModelButtons();
                updateModelIndicator();
            } catch (e) {
                console.error('Failed to load providers:', e);
            }
        }
        
        function updateModelButtons() {
            const openaiBtn = document.getElementById('btn-openai');
            const gigachatBtn = document.getElementById('btn-gigachat');
            
            // Enable/disable buttons based on availability
            openaiBtn.style.opacity = availableProviders.includes('openai') ? '1' : '0.4';
            openaiBtn.style.cursor = availableProviders.includes('openai') ? 'pointer' : 'not-allowed';
            
            gigachatBtn.style.opacity = availableProviders.includes('gigachat') ? '1' : '0.4';
            gigachatBtn.style.cursor = availableProviders.includes('gigachat') ? 'pointer' : 'not-allowed';
            
            // Set active state
            openaiBtn.classList.toggle('active', currentProvider === 'openai');
            gigachatBtn.classList.toggle('active', currentProvider === 'gigachat');
        }
        
        function updateModelIndicator() {
            const indicator = document.getElementById('modelIndicator');
            indicator.className = 'model-indicator ' + currentProvider;
            indicator.textContent = currentProvider === 'openai' ? 'OpenAI' : 'GigaChat';
        }
        
        function selectModel(provider) {
            if (!availableProviders.includes(provider)) {
                alert(`Provider ${provider} is not available. Please configure it in .env file.`);
                return;
            }
            currentProvider = provider;
            updateModelButtons();
            updateModelIndicator();
        }
        
        // Load providers on page load
        loadProviders();
        
        const demos = [
            { name: "📊 Задачи по проектам", query: "Сколько задач по проектам?" },
            { name: "👥 Топ исполнителей", query: "Топ исполнителей по количеству закрытых задач" },
            { name: "⏱️ Время по авторам", query: "Сколько часов затрачено по авторам?" },
            { name: "🏃 Velocity спринтов", query: "Покажи velocity по спринтам" },
            { name: "📈 Открытые задачи", query: "Сколько открытых задач в каждом проекте?" },
            { name: "📋 Детали задачи", query: "Покажи задачу AUTH-1" },
            { name: "💬 Комментарии", query: "Комментарии к задаче AUTH-5" },
            { name: "📉 Story Points", query: "Средние story points по проектам" }
        ];
        
        const demosContainer = document.getElementById('demos');
        demos.forEach(d => {
            const btn = document.createElement('button');
            btn.className = 'demo-btn';
            btn.textContent = d.name;
            btn.onclick = () => {
                document.getElementById('queryInput').value = d.query;
                sendQuery();
            };
            demosContainer.appendChild(btn);
        });
        
        function showTab(tabName) {
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            
            // Show selected tab
            document.getElementById(tabName + 'Tab').classList.add('active');
            event.target.classList.add('active');
        }
        
        function formatLogEntry(log) {
            const typeClass = `log-${log.type}`;
            const duration = log.duration_ms ? `<span class="log-duration">${log.duration_ms}ms</span>` : '';
            const time = new Date(log.timestamp).toLocaleTimeString();
            
            let dataHtml = '';
            if (log.data) {
                dataHtml = `<div class="log-data">${JSON.stringify(log.data, null, 2)}</div>`;
            }
            
            return `
                <div class="log-entry ${typeClass}">
                    <div class="log-header">
                        <span class="log-step">${log.step}</span>
                        <span>
                            ${duration}
                            <span class="log-time">${time}</span>
                        </span>
                    </div>
                    <div class="log-message">${log.message}</div>
                    ${dataHtml}
                </div>
            `;
        }
        
        async function sendQuery() {
            const query = document.getElementById('queryInput').value.trim();
            if (!query) return;
            
            document.getElementById('loading').classList.remove('hidden');
            document.getElementById('steps').innerHTML = '';
            document.getElementById('members').innerHTML = '';
            document.getElementById('cubeQuery').innerHTML = '';
            document.getElementById('output').textContent = 'Processing...';
            document.getElementById('intentBadge').innerHTML = '';
            document.getElementById('logEntries').innerHTML = '<div style="color: #888;">Processing...</div>';
            document.getElementById('totalDuration').textContent = '';
            
            try {
                const response = await fetch('/api/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query, llm_provider: currentProvider })
                });
                
                const data = await response.json();
                
                if (!response.ok) {
                    throw new Error(data.detail || 'Request failed');
                }
                
                // Intent and LLM info
                const intentClass = `intent-${data.intent}`;
                const providerBadge = data.llm_provider === 'gigachat' 
                    ? '<span class="model-indicator gigachat" style="margin-left: 8px;">GigaChat</span>'
                    : '<span class="model-indicator openai" style="margin-left: 8px;">OpenAI</span>';
                document.getElementById('intentBadge').innerHTML = 
                    `<span class="intent-badge ${intentClass}">🎯 ${data.intent}</span>${providerBadge}`;
                
                // Total duration
                document.getElementById('totalDuration').textContent = `${data.total_duration_ms}ms`;
                
                // Relevant members
                if (data.relevant_members && data.relevant_members.length > 0) {
                    document.getElementById('members').innerHTML = `
                        <div class="members-list">
                            <strong>🔎 Found ${data.relevant_members.length} relevant members:</strong><br>
                            ${data.relevant_members.slice(0, 8).join(', ')}${data.relevant_members.length > 8 ? '...' : ''}
                        </div>
                    `;
                }
                
                // Generated Cube query
                if (data.generated_cube_query) {
                    document.getElementById('cubeQuery').innerHTML = `
                        <div class="cube-query">
                            <strong>📝 Generated Cube Query:</strong>
                            <pre>${JSON.stringify(data.generated_cube_query, null, 2)}</pre>
                        </div>
                    `;
                }
                
                // Steps
                const stepsHtml = data.steps.map((step, i) => `
                    <div class="step">
                        <div class="step-title">${i + 1}. ${step.description}</div>
                        <div class="step-endpoint">${step.tool_type.toUpperCase()}: ${step.endpoint}</div>
                    </div>
                `).join('');
                document.getElementById('steps').innerHTML = stepsHtml;
                
                // Results
                document.getElementById('output').textContent = data.final_answer;
                
                if (data.error) {
                    document.getElementById('output').innerHTML += 
                        `\\n\\n<span class="error">⚠️ ${data.error}</span>`;
                }
                
                // Logs
                if (data.logs && data.logs.length > 0) {
                    const logsHtml = data.logs.map(formatLogEntry).join('');
                    document.getElementById('logEntries').innerHTML = logsHtml;
                }
                
                // SQL
                if (data.cube_sql) {
                    document.getElementById('sqlCode').textContent = data.cube_sql;
                } else {
                    document.getElementById('sqlCode').textContent = 'No SQL generated for this query';
                }
                
                // LLM
                if (data.llm_prompt) {
                    document.getElementById('llmPrompt').textContent = data.llm_prompt;
                } else {
                    document.getElementById('llmPrompt').textContent = 'No LLM prompt for this query';
                }
                
                if (data.llm_response) {
                    document.getElementById('llmResponse').textContent = data.llm_response;
                } else {
                    document.getElementById('llmResponse').textContent = 'No LLM response for this query';
                }
                
            } catch (error) {
                document.getElementById('output').innerHTML = 
                    `<span class="error">❌ Error: ${error.message}</span>`;
                document.getElementById('logEntries').innerHTML = 
                    `<div class="log-entry log-error"><div class="log-message">${error.message}</div></div>`;
            } finally {
                document.getElementById('loading').classList.add('hidden');
            }
        }
        
        function clearAll() {
            document.getElementById('queryInput').value = '';
            document.getElementById('steps').innerHTML = '';
            document.getElementById('members').innerHTML = '';
            document.getElementById('cubeQuery').innerHTML = '';
            document.getElementById('output').textContent = 'Введите запрос для анализа...';
            document.getElementById('intentBadge').innerHTML = '';
            document.getElementById('logEntries').innerHTML = '<div style="color: #888; text-align: center; padding: 30px;">Logs will appear here after query execution</div>';
            document.getElementById('sqlCode').textContent = 'No SQL generated yet';
            document.getElementById('llmPrompt').textContent = 'No prompt yet';
            document.getElementById('llmResponse').textContent = 'No response yet';
            document.getElementById('totalDuration').textContent = '';
        }
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("AGENT_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
