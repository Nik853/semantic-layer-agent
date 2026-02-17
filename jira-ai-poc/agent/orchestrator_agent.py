"""
Orchestrator Agent - Thin orchestrator for Semantic Layer

This agent:
- Does NOT generate SQL
- Does NOT contain business logic
- ONLY selects tools from Function Registry and fills parameters
- Works through DataAPI (operational) and Cube API (analytics)
"""

import os
import json
import httpx
import re
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from function_registry import (
    FunctionRegistry, ToolDefinition, ToolType, 
    get_registry, VULCAN_TOOLS, CUBE_TOOLS
)

load_dotenv()

# ============================================
# Configuration
# ============================================

CUBE_BASE_URL = os.getenv("CUBE_BASE_URL", "http://localhost:4000/cubejs-api/v1")
VULCAN_BASE_URL = os.getenv("VULCAN_BASE_URL", "http://localhost:3001")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# ============================================
# Data Classes
# ============================================

@dataclass
class ToolCall:
    """Represents a tool call with parameters"""
    tool_name: str
    tool_type: str  # "cube" or "vulcan"
    endpoint: str
    params: Dict[str, Any]
    description: str


@dataclass
class AgentResponse:
    """Agent response with execution trace"""
    query: str
    intent: str  # "operational", "analytics", "mixed"
    selected_tool: Optional[str] = None
    tool_params: Dict[str, Any] = field(default_factory=dict)
    steps: List[ToolCall] = field(default_factory=list)
    results: List[Dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    error: Optional[str] = None
    total_duration_ms: int = 0


# ============================================
# Intent Classifier
# ============================================

class IntentClassifier:
    """Classify query intent: operational, analytics, or mixed"""
    
    ANALYTICS_KEYWORDS = [
        # Russian
        "сколько", "количество", "статистика", "метрик", "топ",
        "среднее", "всего", "динамика", "тренд", "распределение",
        "группировка", "по проектам", "по исполнителям", "по статусам",
        "velocity", "throughput", "wip", "backlog", "lead time",
        "reopen", "cycle time",
        # English
        "how many", "count", "total", "average", "statistics",
        "metrics", "top", "trend", "distribution", "group by",
        "by project", "by assignee", "by status"
    ]
    
    OPERATIONAL_KEYWORDS = [
        # Russian
        "покажи", "список", "найди", "поиск", "детали",
        "информация", "комментарии", "связи", "задача", "задачи",
        # English
        "show", "list", "find", "search", "details",
        "info", "comments", "links", "issue", "issues"
    ]
    
    DETAIL_PATTERNS = [
        r"[A-Z]+-\d+",  # Issue key like AUTH-1
        r"задач[уа]?\s+#?\d+",
        r"issue\s+#?\d+",
    ]
    
    def classify(self, query: str) -> str:
        """Return 'analytics', 'operational', or 'detail'"""
        query_lower = query.lower()
        
        # Check for specific issue patterns first (detail)
        for pattern in self.DETAIL_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                # But if it also has analytics keywords, it's analytics
                if not any(kw in query_lower for kw in self.ANALYTICS_KEYWORDS):
                    return "detail"
        
        # Check for analytics keywords (highest priority for aggregations)
        analytics_score = sum(1 for kw in self.ANALYTICS_KEYWORDS if kw in query_lower)
        operational_score = sum(1 for kw in self.OPERATIONAL_KEYWORDS if kw in query_lower)
        
        if analytics_score > operational_score:
            return "analytics"
        elif operational_score > 0:
            return "operational"
        
        # Default to analytics for ambiguous queries
        return "analytics"


# ============================================
# Tool Selector
# ============================================

TOOL_SELECTION_PROMPT = """You are a tool selector for a JIRA analytics system. 
Given a user query, select the most appropriate tool from the available tools.

## Available Tools:

{tools_description}

## Rules:
1. Select EXACTLY ONE tool that best matches the user's query
2. Extract parameter values from the query
3. Return ONLY valid JSON in this format:
{{
  "tool_name": "tool_name_here",
  "params": {{
    "param1": "value1",
    "param2": "value2"
  }}
}}

## User Query:
{query}

## JSON Response:"""


class ToolSelector:
    """Select appropriate tool using LLM"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=OPENAI_MODEL,
            temperature=0
        )
        self.registry = get_registry()
        self.prompt = ChatPromptTemplate.from_template(TOOL_SELECTION_PROMPT)
    
    def select(self, query: str, intent: str) -> tuple[Optional[ToolDefinition], Dict[str, Any]]:
        """Select tool and extract parameters"""
        
        # First, try to match by keywords (fast path)
        matching_tools = self.registry.find_matching_tools(query, max_results=3)
        
        # Filter by intent
        if intent == "analytics":
            matching_tools = [t for t in matching_tools if t.tool_type == ToolType.CUBE] or matching_tools
        elif intent in ("operational", "detail"):
            matching_tools = [t for t in matching_tools if t.tool_type == ToolType.VULCAN] or matching_tools
        
        if not matching_tools:
            # Fallback: use all tools of the right type
            if intent == "analytics":
                matching_tools = self.registry.get_tools_by_type(ToolType.CUBE)
            else:
                matching_tools = self.registry.get_tools_by_type(ToolType.VULCAN)
        
        # If only one strong match, use it directly
        if len(matching_tools) == 1:
            tool = matching_tools[0]
            params = self._extract_params_simple(query, tool)
            return tool, params
        
        # Use LLM to select from matching tools
        tools_desc = self._format_tools_for_prompt(matching_tools)
        
        messages = self.prompt.format_messages(
            tools_description=tools_desc,
            query=query
        )
        
        response = self.llm.invoke(messages)
        
        try:
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()
            
            result = json.loads(content)
            tool_name = result.get("tool_name")
            params = result.get("params", {})
            
            tool = self.registry.get_tool(tool_name)
            return tool, params
            
        except (json.JSONDecodeError, KeyError) as e:
            # Fallback to first matching tool
            if matching_tools:
                tool = matching_tools[0]
                params = self._extract_params_simple(query, tool)
                return tool, params
            return None, {}
    
    def _format_tools_for_prompt(self, tools: List[ToolDefinition]) -> str:
        """Format tools for LLM prompt"""
        lines = []
        for tool in tools:
            lines.append(f"- **{tool.name}**: {tool.description}")
            if tool.parameters:
                params = [f"{p.name}({p.type})" for p in tool.parameters if p.required or p.name in ["project_id", "id", "q"]]
                if params:
                    lines.append(f"  Required/key params: {', '.join(params)}")
            lines.append(f"  Examples: {'; '.join(tool.examples[:2])}")
        return "\n".join(lines)
    
    def _extract_params_simple(self, query: str, tool: ToolDefinition) -> Dict[str, Any]:
        """Extract parameters using simple regex patterns"""
        params = {}
        
        # Extract issue key
        issue_match = re.search(r'([A-Z]+-\d+)', query)
        if issue_match and any(p.name == "id" for p in tool.parameters):
            params["id"] = issue_match.group(1)
        
        # Extract project name/key
        project_match = re.search(r'проект[уеа]?\s+([A-Z]{2,10})\b', query, re.I)
        if not project_match:
            project_match = re.search(r'project\s+([A-Z]{2,10})\b', query, re.I)
        if project_match:
            params["project_name"] = project_match.group(1).upper()
        
        # Extract search query
        search_match = re.search(r'(?:про|about|containing|поиск|search|find)\s+["\']?(\w+)["\']?', query, re.I)
        if search_match and any(p.name == "q" for p in tool.parameters):
            params["q"] = search_match.group(1)
        
        # Extract limit
        limit_match = re.search(r'(?:top|топ|первые|limit)\s+(\d+)', query, re.I)
        if limit_match:
            params["limit"] = int(limit_match.group(1))
        
        # Set defaults
        for param in tool.parameters:
            if param.name not in params and param.default is not None:
                params[param.name] = param.default
        
        return params


# ============================================
# Tool Executor
# ============================================

class ToolExecutor:
    """Execute tools via APIs"""
    
    def __init__(self):
        self.client = httpx.Client(timeout=30.0)
    
    def execute(self, tool: ToolDefinition, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tool and return result"""
        if tool.tool_type == ToolType.VULCAN:
            return self._execute_vulcan(tool, params)
        else:
            return self._execute_cube(tool, params)
    
    def _execute_vulcan(self, tool: ToolDefinition, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute VulcanSQL tool"""
        endpoint = tool.endpoint
        
        # Replace path parameters
        if "{id}" in endpoint:
            issue_id = params.pop("id", None)
            if issue_id:
                endpoint = endpoint.replace("{id}", str(issue_id))
            else:
                return {"error": "Missing required parameter: id"}
        
        url = f"{VULCAN_BASE_URL}{endpoint}"
        
        try:
            resp = self.client.get(url, params=params)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}
    
    def _execute_cube(self, tool: ToolDefinition, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Cube tool"""
        # Build Cube query from tool definition
        query = {
            "measures": tool.cube_measures.copy(),
            "dimensions": tool.cube_dimensions.copy(),
            "limit": params.get("limit", 100)
        }
        
        # Add filters from params
        filters = []
        if "project_name" in params:
            # Find the right dimension for project
            for dim in tool.cube_dimensions:
                if "project" in dim.lower():
                    filters.append({
                        "member": dim,
                        "operator": "contains",
                        "values": [params["project_name"]]
                    })
                    break
        
        if filters:
            query["filters"] = filters
        
        url = f"{CUBE_BASE_URL}/load"
        
        try:
            resp = self.client.post(url, json={"query": query}, headers={"Content-Type": "application/json"})
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


# ============================================
# Response Formatter
# ============================================

class ResponseFormatter:
    """Format API responses for user"""
    
    def format(self, result: Dict[str, Any], tool: ToolDefinition) -> str:
        """Format result based on tool type"""
        if "error" in result:
            return f"❌ Error: {result['error']}"
        
        if tool.tool_type == ToolType.CUBE:
            return self._format_cube(result)
        else:
            return self._format_vulcan(result, tool)
    
    def _format_cube(self, result: Dict[str, Any]) -> str:
        """Format Cube analytics result"""
        data = result.get("data", [])
        if not data:
            return "📊 No analytics data found"
        
        lines = [f"📊 Analytics Results ({len(data)} rows):"]
        
        for i, row in enumerate(data[:15], 1):
            parts = []
            for k, v in row.items():
                short_key = k.split(".")[-1]
                if isinstance(v, float):
                    v = round(v, 2)
                parts.append(f"{short_key}: {v}")
            lines.append(f"  {i}. {', '.join(parts)}")
        
        if len(data) > 15:
            lines.append(f"  ... and {len(data) - 15} more rows")
        
        return "\n".join(lines)
    
    def _format_vulcan(self, result: Dict[str, Any], tool: ToolDefinition) -> str:
        """Format VulcanSQL operational result"""
        # Single issue detail
        if "key" in result and "data" not in result:
            lines = [f"📋 [{result.get('key')}] {result.get('summary', '')}"]
            lines.append(f"  Status: {result.get('status_name', result.get('status', 'N/A'))}")
            lines.append(f"  Assignee: {result.get('assignee_name', result.get('assignee', 'Unassigned'))}")
            lines.append(f"  Project: {result.get('project_name', result.get('project_key', ''))}")
            if result.get("description"):
                lines.append(f"  Description: {result.get('description', '')[:150]}...")
            return "\n".join(lines)
        
        # List of items
        data = result.get("data", result) if isinstance(result, dict) else result
        if isinstance(data, dict):
            data = data.get("data", [])
        
        if not data:
            return "📋 No results found"
        
        count = result.get("count", len(data)) if isinstance(result, dict) else len(data)
        lines = [f"📋 Found {count} results:"]
        
        for i, item in enumerate(data[:20], 1):
            if isinstance(item, dict):
                if "key" in item:
                    status = item.get("status_name", item.get("status", ""))
                    lines.append(f"  {i}. [{item.get('key')}] {item.get('summary', '')[:50]}")
                    lines.append(f"      Status: {status} | Assignee: {item.get('assignee_name', 'Unassigned')}")
                elif "name" in item:
                    lines.append(f"  {i}. {item.get('key', '')} - {item.get('name', '')}")
                elif "body" in item:
                    lines.append(f"  {i}. {item.get('body', '')[:80]}")
                else:
                    lines.append(f"  {i}. {str(item)[:80]}")
        
        if len(data) > 20:
            lines.append(f"  ... and {len(data) - 20} more")
        
        return "\n".join(lines)


# ============================================
# Orchestrator Agent
# ============================================

class OrchestratorAgent:
    """
    Thin orchestrator agent that:
    - Classifies intent
    - Selects appropriate tool from registry
    - Fills parameters
    - Executes tool
    - Formats response
    
    Does NOT generate SQL or contain business logic.
    """
    
    def __init__(self):
        print("🔄 Initializing Orchestrator Agent...")
        self.registry = get_registry()
        self.classifier = IntentClassifier()
        self.selector = ToolSelector()
        self.executor = ToolExecutor()
        self.formatter = ResponseFormatter()
        print(f"✅ Orchestrator Agent ready! Registered {len(self.registry.tools)} tools")
    
    def process(self, query: str) -> AgentResponse:
        """Process natural language query"""
        start_time = time.time()
        response = AgentResponse(query=query, intent="")
        
        try:
            # Step 1: Classify intent
            response.intent = self.classifier.classify(query)
            
            # Step 2: Select tool
            tool, params = self.selector.select(query, response.intent)
            
            if not tool:
                response.error = "Could not find appropriate tool for this query"
                response.final_answer = "❌ Не удалось подобрать инструмент для этого запроса"
                return response
            
            response.selected_tool = tool.name
            response.tool_params = params
            
            # Step 3: Create tool call
            tool_call = ToolCall(
                tool_name=tool.name,
                tool_type=tool.tool_type.value,
                endpoint=tool.endpoint,
                params=params,
                description=tool.description
            )
            response.steps.append(tool_call)
            
            # Step 4: Execute tool
            result = self.executor.execute(tool, params)
            response.results.append(result)
            
            # Step 5: Format response
            response.final_answer = self.formatter.format(result, tool)
            
        except Exception as e:
            response.error = str(e)
            response.final_answer = f"❌ Error: {str(e)}"
        
        response.total_duration_ms = int((time.time() - start_time) * 1000)
        return response


# ============================================
# CLI
# ============================================

def run_cli():
    """Run interactive CLI"""
    agent = OrchestratorAgent()
    
    print("\n" + "=" * 60)
    print("JIRA Orchestrator Agent - Tool-based Query Router")
    print("=" * 60)
    print(f"Cube API: {CUBE_BASE_URL}")
    print(f"VulcanSQL: {VULCAN_BASE_URL}")
    print(f"Registered tools: {len(agent.registry.tools)}")
    print("-" * 60)
    print("Examples:")
    print("  - Сколько задач по проектам?")
    print("  - Покажи задачи проекта AUTH")
    print("  - Покажи задачу AUTH-1")
    print("  - Топ по залогированному времени")
    print("-" * 60)
    print("Type 'tools' to list all tools, 'quit' to exit")
    print("=" * 60)
    
    while True:
        try:
            user_input = input("\n🔍 Query: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if user_input.lower() == 'tools':
                print("\n📦 Available Tools:")
                for tool in agent.registry.get_all_tools():
                    print(f"  - {tool.name} ({tool.tool_type.value}): {tool.description}")
                continue
            
            response = agent.process(user_input)
            
            print(f"\n📊 Intent: {response.intent}")
            print(f"🔧 Selected tool: {response.selected_tool}")
            print(f"📝 Parameters: {json.dumps(response.tool_params, ensure_ascii=False)}")
            
            if response.steps:
                print(f"\n📞 Tool call:")
                step = response.steps[0]
                print(f"   Type: {step.tool_type}")
                print(f"   Endpoint: {step.endpoint}")
            
            print(f"\n📝 Result:")
            print(response.final_answer)
            
            print(f"\n⏱️ Total time: {response.total_duration_ms}ms")
            
            if response.error:
                print(f"\n⚠️ Error: {response.error}")
        
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    run_cli()
