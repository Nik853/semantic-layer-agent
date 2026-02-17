"""
JIRA Router Agent - FastAPI Web Interface
"""

import os
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

from agent import JiraRouterAgent, DEMO_SCENARIOS, IntentType

load_dotenv()

app = FastAPI(title="JIRA Router Agent", version="1.0.0")

# Global agent instance
agent = JiraRouterAgent()


class QueryRequest(BaseModel):
    query: str
    use_semantic_layer: bool = True


class ToolCallResponse(BaseModel):
    tool_type: str
    endpoint: str
    params: Dict[str, Any]
    description: str


class AgentResponseModel(BaseModel):
    query: str
    intent: str
    steps: List[ToolCallResponse]
    results: List[Dict[str, Any]]
    final_answer: str
    error: Optional[str] = None


# ============================================
# API Endpoints
# ============================================

@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the web interface"""
    return HTML_TEMPLATE


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "jira-router-agent"}


@app.get("/api/demos")
async def get_demos():
    """Get list of demo scenarios"""
    return {"demos": DEMO_SCENARIOS}


@app.post("/api/query", response_model=AgentResponseModel)
async def process_query(request: QueryRequest):
    """Process natural language query"""
    try:
        response = agent.process(request.query, use_semantic_layer=request.use_semantic_layer)
        
        return AgentResponseModel(
            query=response.query,
            intent=response.intent.value,
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
            error=response.error
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# HTML Template (Single Page App)
# ============================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JIRA Router Agent</title>
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
            margin-bottom: 10px;
            color: #00d4ff;
            font-size: 2em;
        }
        .subtitle {
            text-align: center;
            color: #888;
            margin-bottom: 30px;
        }
        .input-section {
            background: rgba(255,255,255,0.05);
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
        }
        .query-input {
            width: 100%;
            padding: 15px;
            border: 2px solid #333;
            border-radius: 8px;
            background: #1a1a2e;
            color: #fff;
            font-size: 16px;
            margin-bottom: 15px;
        }
        .query-input:focus {
            outline: none;
            border-color: #00d4ff;
        }
        .btn-row {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.2s;
        }
        .btn-primary {
            background: linear-gradient(135deg, #00d4ff 0%, #0099ff 100%);
            color: #000;
        }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,212,255,0.3); }
        .btn-secondary {
            background: #333;
            color: #fff;
        }
        .btn-secondary:hover { background: #444; }
        .demos {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 15px;
        }
        .demo-btn {
            padding: 8px 16px;
            background: rgba(0,212,255,0.1);
            border: 1px solid rgba(0,212,255,0.3);
            border-radius: 20px;
            color: #00d4ff;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }
        .demo-btn:hover {
            background: rgba(0,212,255,0.2);
            border-color: #00d4ff;
        }
        .toggle-section {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 15px;
            padding: 10px;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
        }
        .toggle {
            position: relative;
            width: 50px;
            height: 26px;
        }
        .toggle input { opacity: 0; width: 0; height: 0; }
        .slider {
            position: absolute;
            cursor: pointer;
            top: 0; left: 0; right: 0; bottom: 0;
            background-color: #333;
            transition: .3s;
            border-radius: 26px;
        }
        .slider:before {
            position: absolute;
            content: "";
            height: 20px;
            width: 20px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: .3s;
            border-radius: 50%;
        }
        input:checked + .slider { background-color: #00d4ff; }
        input:checked + .slider:before { transform: translateX(24px); }
        .results-section {
            display: grid;
            grid-template-columns: 1fr 2fr;
            gap: 20px;
        }
        @media (max-width: 768px) {
            .results-section { grid-template-columns: 1fr; }
        }
        .panel {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px;
        }
        .panel h3 {
            color: #00d4ff;
            margin-bottom: 15px;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .intent-badge {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .intent-operational { background: #2ecc71; color: #000; }
        .intent-analytics { background: #9b59b6; color: #fff; }
        .intent-mixed { background: #f39c12; color: #000; }
        .step {
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 10px;
            border-left: 3px solid #00d4ff;
        }
        .step-title { font-weight: 600; margin-bottom: 5px; }
        .step-endpoint { 
            font-family: monospace; 
            font-size: 12px; 
            color: #888;
            word-break: break-all;
        }
        .output {
            background: #0a0a15;
            border-radius: 8px;
            padding: 15px;
            font-family: monospace;
            font-size: 13px;
            white-space: pre-wrap;
            max-height: 500px;
            overflow-y: auto;
            line-height: 1.5;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #888;
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
        .error { color: #e74c3c; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 JIRA Router Agent</h1>
        <p class="subtitle">Natural Language → VulcanSQL (Operational) + Cube (Analytics)</p>
        
        <div class="input-section">
            <input type="text" class="query-input" id="queryInput" 
                   placeholder="Ask a question about JIRA data... (e.g., 'Show issues for project AUTH')"
                   onkeypress="if(event.key==='Enter')sendQuery()">
            
            <div class="btn-row">
                <button class="btn btn-primary" onclick="sendQuery()">🔍 Send Query</button>
                <button class="btn btn-secondary" onclick="clearAll()">🗑️ Clear</button>
            </div>
            
            <div class="toggle-section">
                <label class="toggle">
                    <input type="checkbox" id="semanticToggle" checked>
                    <span class="slider"></span>
                </label>
                <span>Smart Routing (ON = Data API + Cube | OFF = Data API only)</span>
            </div>
            
            <div class="demos" id="demos"></div>
        </div>
        
        <div class="results-section">
            <div class="panel">
                <h3>🔧 Tool Calls</h3>
                <div id="intentBadge"></div>
                <div id="steps"></div>
            </div>
            
            <div class="panel">
                <h3>📊 Results</h3>
                <div class="output" id="output">Enter a query to see results...</div>
            </div>
        </div>
        
        <div class="loading hidden" id="loading">
            <div class="spinner"></div>
            <p>Processing query...</p>
        </div>
    </div>
    
    <script>
        const demos = [
            { id: 1, name: "📋 List AUTH issues", query: "Show issues for project AUTH" },
            { id: 2, name: "🔍 Issue details", query: "Show issue [AI-3] details" },
            { id: 3, name: "🔎 Search", query: "Search issues containing database" },
            { id: 4, name: "📈 Throughput", query: "How many issues resolved by project?" },
            { id: 5, name: "⏳ WIP", query: "Show WIP by assignee" },
            { id: 6, name: "👥 Top authors", query: "Top authors by worklogs last 14 days" },
            { id: 7, name: "🚀 Velocity", query: "Show sprint velocity committed vs completed" }
        ];
        
        // Render demo buttons
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
        
        async function sendQuery() {
            const query = document.getElementById('queryInput').value.trim();
            if (!query) return;
            
            const useSemanticLayer = document.getElementById('semanticToggle').checked;
            
            // Show loading
            document.getElementById('loading').classList.remove('hidden');
            document.getElementById('steps').innerHTML = '';
            document.getElementById('output').textContent = 'Processing...';
            document.getElementById('intentBadge').innerHTML = '';
            
            try {
                const response = await fetch('/api/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query, use_semantic_layer: useSemanticLayer })
                });
                
                const data = await response.json();
                
                if (!response.ok) {
                    throw new Error(data.detail || 'Request failed');
                }
                
                // Display intent
                const intentClass = `intent-${data.intent}`;
                document.getElementById('intentBadge').innerHTML = 
                    `<span class="intent-badge ${intentClass}">${data.intent}</span>`;
                
                // Display steps
                const stepsHtml = data.steps.map((step, i) => `
                    <div class="step">
                        <div class="step-title">${i + 1}. ${step.description}</div>
                        <div class="step-endpoint">${step.tool_type.toUpperCase()}: ${step.endpoint}</div>
                    </div>
                `).join('');
                document.getElementById('steps').innerHTML = stepsHtml;
                
                // Display results
                document.getElementById('output').textContent = data.final_answer;
                
                if (data.error) {
                    document.getElementById('output').innerHTML += 
                        `\\n\\n<span class="error">Error: ${data.error}</span>`;
                }
                
            } catch (error) {
                document.getElementById('output').innerHTML = 
                    `<span class="error">Error: ${error.message}</span>`;
            } finally {
                document.getElementById('loading').classList.add('hidden');
            }
        }
        
        function clearAll() {
            document.getElementById('queryInput').value = '';
            document.getElementById('steps').innerHTML = '';
            document.getElementById('output').textContent = 'Enter a query to see results...';
            document.getElementById('intentBadge').innerHTML = '';
        }
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("AGENT_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
