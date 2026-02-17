"""
JIRA Semantic Agent - LLM-based router using Cube metadata
No hardcoded queries - LLM generates JSON for Cube REST API
With detailed logging for UI
"""

import os
import json
import httpx
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from dotenv import load_dotenv

# Vector store
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document

# LLM
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

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
class LogEntry:
    """Single log entry for pipeline tracking"""
    timestamp: str
    step: str
    type: str  # "info", "llm", "cube", "sql", "error", "success"
    message: str
    data: Optional[Dict] = None
    duration_ms: Optional[int] = None


@dataclass
class CubeMember:
    """Represents a measure or dimension from Cube"""
    name: str
    title: str
    type: str
    cube_name: str
    member_type: str  # "measure" or "dimension"
    description: str = ""
    agg_type: str = ""  # for measures: count, sum, avg, etc.


@dataclass
class ToolCall:
    """Represents a tool call"""
    tool_type: str  # "cube" or "vulcan"
    endpoint: str
    params: Dict[str, Any]
    description: str


@dataclass
class AgentResponse:
    """Agent response with execution trace"""
    query: str
    intent: str
    relevant_members: List[str] = field(default_factory=list)
    generated_cube_query: Optional[Dict] = None
    steps: List[ToolCall] = field(default_factory=list)
    results: List[Dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    error: Optional[str] = None
    # NEW: Detailed logs
    logs: List[LogEntry] = field(default_factory=list)
    llm_prompt: Optional[str] = None
    llm_response: Optional[str] = None
    cube_sql: Optional[str] = None
    total_duration_ms: int = 0


# ============================================
# Cube Metadata Loader
# ============================================

class CubeMetadataLoader:
    """Load and parse Cube metadata from REST API"""
    
    def __init__(self, cube_url: str = CUBE_BASE_URL):
        self.cube_url = cube_url
        self.client = httpx.Client(timeout=30.0)
        self._metadata: Optional[Dict] = None
        self._members: List[CubeMember] = []
    
    def load(self) -> Dict:
        """Load metadata from Cube /meta endpoint"""
        url = f"{self.cube_url}/meta"
        resp = self.client.get(url)
        resp.raise_for_status()
        self._metadata = resp.json()
        self._parse_members()
        return self._metadata
    
    def _parse_members(self):
        """Parse cubes into flat list of members"""
        self._members = []
        
        for cube in self._metadata.get("cubes", []):
            cube_name = cube["name"]
            cube_title = cube.get("title", cube_name)
            cube_desc = cube.get("description", "")
            
            # Parse measures
            for measure in cube.get("measures", []):
                if not measure.get("isVisible", True):
                    continue
                self._members.append(CubeMember(
                    name=measure["name"],
                    title=measure.get("title", measure["name"]),
                    type=measure.get("type", "number"),
                    cube_name=cube_name,
                    member_type="measure",
                    description=measure.get("description", ""),
                    agg_type=measure.get("aggType", "")
                ))
            
            # Parse dimensions
            for dim in cube.get("dimensions", []):
                if not dim.get("isVisible", True):
                    continue
                self._members.append(CubeMember(
                    name=dim["name"],
                    title=dim.get("title", dim["name"]),
                    type=dim.get("type", "string"),
                    cube_name=cube_name,
                    member_type="dimension",
                    description=dim.get("description", "")
                ))
    
    @property
    def members(self) -> List[CubeMember]:
        return self._members
    
    @property
    def cubes(self) -> List[str]:
        return [c["name"] for c in self._metadata.get("cubes", [])]
    
    def get_cube_info(self, cube_name: str) -> Optional[Dict]:
        """Get full info for a specific cube"""
        for cube in self._metadata.get("cubes", []):
            if cube["name"] == cube_name:
                return cube
        return None


# ============================================
# Vector Store for Semantic Search
# ============================================

class CubeVectorStore:
    """FAISS vector store for Cube metadata"""
    
    def __init__(self, members: List[CubeMember]):
        self.members = members
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        self._store: Optional[FAISS] = None
        self._build_index()
    
    def _build_index(self):
        """Build FAISS index from members"""
        documents = []
        for m in self.members:
            # Create rich text for embedding
            text = f"{m.title}. {m.description}. Cube: {m.cube_name}. Type: {m.member_type}, {m.type}"
            if m.agg_type:
                text += f". Aggregation: {m.agg_type}"
            
            doc = Document(
                page_content=text,
                metadata={
                    "name": m.name,
                    "title": m.title,
                    "type": m.type,
                    "cube_name": m.cube_name,
                    "member_type": m.member_type,
                    "agg_type": m.agg_type,
                    "description": m.description
                }
            )
            documents.append(doc)
        
        if documents:
            self._store = FAISS.from_documents(documents, self.embeddings)
    
    def search(self, query: str, k: int = 10) -> List[Dict]:
        """Search for relevant measures/dimensions"""
        if not self._store:
            return []
        
        results = self._store.similarity_search_with_score(query, k=k)
        
        return [
            {
                "name": doc.metadata["name"],
                "title": doc.metadata["title"],
                "type": doc.metadata["type"],
                "cube_name": doc.metadata["cube_name"],
                "member_type": doc.metadata["member_type"],
                "agg_type": doc.metadata.get("agg_type", ""),
                "description": doc.metadata.get("description", ""),
                "score": float(score)
            }
            for doc, score in results
        ]


# ============================================
# LLM Query Generator
# ============================================

CUBE_QUERY_PROMPT = """You are a Cube.js query generator for JIRA analytics. Convert natural language questions into valid Cube REST API JSON queries.

## Available Measures (for aggregations):
{measures}

## Available Dimensions (for grouping/filtering):
{dimensions}

## Cube Query Format:
{{
  "measures": ["cube.measure_name"],
  "dimensions": ["cube.dimension_name"],
  "filters": [
    {{"member": "cube.dimension", "operator": "equals", "values": ["value"]}}
  ],
  "timeDimensions": [
    {{"dimension": "cube.time_dimension", "granularity": "day|week|month", "dateRange": "last 7 days"}}
  ],
  "order": {{"cube.measure": "desc"}},
  "limit": 100
}}

## CRITICAL RULES for measure selection:
1. "сколько задач" / "количество задач" / "how many issues" / "count issues" → use ".count" measure (e.g. issues.count, issues_overview.count)
2. "story points" / "стори поинты" → use ".total_story_points" or ".avg_story_points"  
3. "часов" / "время" / "hours" / "time spent" → use ".total_hours" or ".total_time_spent"
4. "топ исполнителей" / "by assignee" → group by assignee dimension (users_assignee.display_name or issues_overview.users_assignee_display_name)
5. "по проектам" / "by project" → group by project dimension (projects.key, projects.name, issues_overview.projects_key)

## CRITICAL RULES for filtering:
1. Filter by ASSIGNEE name (исполнитель): use "issues_overview.users_assignee_display_name" with "contains" operator
   Example: {{"member": "issues_overview.users_assignee_display_name", "operator": "contains", "values": ["Lisa"]}}
2. Filter by REPORTER name (автор): use "issues_overview.users_reporter_display_name" with "contains" operator
3. Filter by PROJECT: use "issues_overview.projects_key" with "equals" operator
4. Filter by STATUS: use "issues_overview.status_name" with "equals" operator

## General Rules:
1. PREFER issues_overview cube - it has all needed joins (assignee, reporter, project, status)
2. For queries about projects with assignee filter: use issues_overview.count + issues_overview.projects_key + filter by issues_overview.users_assignee_display_name
3. Add reasonable limit (default 100, max 1000)
4. For time-based analysis, use timeDimensions
5. Return ONLY valid JSON, no explanations

## User Question:
{question}

## JSON Query:"""


class CubeQueryGenerator:
    """Generate Cube queries using LLM"""
    
    def __init__(self, api_key: str = OPENAI_API_KEY, model: str = OPENAI_MODEL):
        self.llm = ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=0
        )
        self.prompt = ChatPromptTemplate.from_template(CUBE_QUERY_PROMPT)
        self.last_prompt: str = ""
        self.last_response: str = ""
    
    def generate(self, question: str, relevant_members: List[Dict]) -> Dict:
        """Generate Cube query from question and relevant members"""
        
        # Format measures and dimensions
        measures = []
        dimensions = []
        
        for m in relevant_members:
            if m["member_type"] == "measure":
                measures.append(f"- {m['name']}: {m['title']} ({m['agg_type']})")
            else:
                dimensions.append(f"- {m['name']}: {m['title']} (type: {m['type']})")
        
        measures_str = "\n".join(measures) if measures else "No measures found"
        dimensions_str = "\n".join(dimensions) if dimensions else "No dimensions found"
        
        # Generate query
        messages = self.prompt.format_messages(
            measures=measures_str,
            dimensions=dimensions_str,
            question=question
        )
        
        # Store prompt for logging
        self.last_prompt = messages[0].content if messages else ""
        
        response = self.llm.invoke(messages)
        self.last_response = response.content
        
        # Parse JSON from response
        try:
            # Clean response - extract JSON
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()
            
            return json.loads(content)
        except json.JSONDecodeError as e:
            return {"error": f"Failed to parse LLM response: {str(e)}", "raw": response.content}


# ============================================
# Query Validator
# ============================================

class CubeQueryValidator:
    """Validate Cube queries before execution"""
    
    def __init__(self, valid_members: List[str]):
        self.valid_members = set(valid_members)
    
    def validate(self, query: Dict) -> tuple[bool, str]:
        """Validate query and return (is_valid, error_message)"""
        
        if "error" in query:
            return False, query["error"]
        
        # Check measures exist
        for measure in query.get("measures", []):
            if measure not in self.valid_members:
                return False, f"Invalid measure: {measure}"
        
        # Check dimensions exist
        for dim in query.get("dimensions", []):
            if dim not in self.valid_members:
                return False, f"Invalid dimension: {dim}"
        
        # Check limit is reasonable
        limit = query.get("limit", 100)
        if limit > 10000:
            query["limit"] = 10000  # Cap it
        
        # Ensure at least one measure for analytics
        if not query.get("measures"):
            return False, "Query must have at least one measure"
        
        return True, ""


# ============================================
# Intent Detector
# ============================================

class IntentDetector:
    """Detect if query is for analytics (Cube), list (VulcanSQL) or single issue details"""
    
    # Single issue detail patterns
    SINGLE_ISSUE_PATTERNS = [
        r"покажи задачу\s+[A-Z]+-\d+",
        r"детали задачи\s+[A-Z]+-\d+",
        r"информация по задаче\s+[A-Z]+-\d+",
        r"issue details",
        r"show issue\s+[A-Z]+-\d+",
        r"задача\s+[A-Z]+-\d+",
        r"[A-Z]+-\d+",  # Just issue key
        r"комментарии к задаче",
        r"comments for",
        r"связи задачи",
        r"links for"
    ]
    
    # List of issues patterns (VulcanSQL)
    LIST_PATTERNS = [
        r"список задач",
        r"покажи задачи",
        r"все задачи",
        r"задачи по проекту",
        r"задачи проекта",
        r"задачи в проекте",
        r"какие задачи",
        r"list issues",
        r"show issues",
        r"issues in project",
        r"issues for project",
        r"what issues",
        r"which issues",
        r"найди задачи",
        r"поиск задач",
        r"search issues"
    ]
    
    ANALYTICS_KEYWORDS = [
        "сколько", "количество", "статистика", "метрик", "топ",
        "по исполнителям", "динамика", "тренд", "среднее", "всего",
        "how many", "count", "total", "average", "by assignee",
        "trend", "statistics", "metrics", "top", "группировка",
        "распределение", "distribution"
    ]
    
    def detect(self, query: str) -> str:
        """Return 'analytics', 'list' or 'detail'"""
        import re
        query_lower = query.lower()
        
        # Check for analytics keywords FIRST (highest priority)
        for kw in self.ANALYTICS_KEYWORDS:
            if kw in query_lower:
                return "analytics"
        
        # Check for list patterns (show list of issues)
        for pattern in self.LIST_PATTERNS:
            if re.search(pattern, query_lower):
                return "list"
        
        # Check for single issue patterns
        for pattern in self.SINGLE_ISSUE_PATTERNS:
            if re.search(pattern, query_lower, re.IGNORECASE):
                return "detail"
        
        # Default to analytics
        return "analytics"


# ============================================
# Semantic Agent
# ============================================

class SemanticAgent:
    """Main agent using semantic search + LLM for Cube queries"""
    
    def __init__(self):
        print("🔄 Loading Cube metadata...")
        self.metadata_loader = CubeMetadataLoader()
        self.metadata_loader.load()
        
        print("🔄 Building vector index...")
        self.vector_store = CubeVectorStore(self.metadata_loader.members)
        
        print("🔄 Initializing LLM...")
        self.query_generator = CubeQueryGenerator()
        
        # Build validator with all valid member names
        valid_members = [m.name for m in self.metadata_loader.members]
        self.validator = CubeQueryValidator(valid_members)
        
        self.intent_detector = IntentDetector()
        self.client = httpx.Client(timeout=30.0)
        
        print("✅ Semantic Agent ready!")
    
    def _log(self, response: AgentResponse, step: str, log_type: str, message: str, 
             data: Dict = None, duration_ms: int = None):
        """Add log entry to response"""
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            step=step,
            type=log_type,
            message=message,
            data=data,
            duration_ms=duration_ms
        )
        response.logs.append(entry)
    
    def process(self, question: str) -> AgentResponse:
        """Process natural language question"""
        start_time = time.time()
        response = AgentResponse(query=question, intent="")
        
        self._log(response, "start", "info", f"Processing query: {question}")
        
        try:
            # Step 1: Detect intent
            intent_start = time.time()
            response.intent = self.intent_detector.detect(question)
            intent_ms = int((time.time() - intent_start) * 1000)
            self._log(response, "intent", "info", f"Detected intent: {response.intent}", 
                     duration_ms=intent_ms)
            
            if response.intent == "detail":
                result = self._handle_detail_query(question, response)
            elif response.intent == "list":
                result = self._handle_list_query(question, response)
            else:
                result = self._handle_analytics_query(question, response)
            
            result.total_duration_ms = int((time.time() - start_time) * 1000)
            self._log(result, "complete", "success", 
                     f"Query completed in {result.total_duration_ms}ms")
            
            return result
        
        except Exception as e:
            response.error = str(e)
            response.final_answer = f"❌ Error: {str(e)}"
            self._log(response, "error", "error", str(e))
            response.total_duration_ms = int((time.time() - start_time) * 1000)
            return response
    
    def _handle_analytics_query(self, question: str, response: AgentResponse) -> AgentResponse:
        """Handle analytics query using Cube"""
        
        # Step 1: Semantic search for relevant members
        search_start = time.time()
        relevant = self.vector_store.search(question, k=15)
        response.relevant_members = [m["name"] for m in relevant]
        search_ms = int((time.time() - search_start) * 1000)
        
        self._log(response, "semantic_search", "info", 
                 f"Found {len(relevant)} relevant members",
                 data={"members": response.relevant_members[:5]},
                 duration_ms=search_ms)
        
        # Step 2: Generate Cube query using LLM
        llm_start = time.time()
        cube_query = self.query_generator.generate(question, relevant)
        llm_ms = int((time.time() - llm_start) * 1000)
        
        response.generated_cube_query = cube_query
        response.llm_prompt = self.query_generator.last_prompt
        response.llm_response = self.query_generator.last_response
        
        self._log(response, "llm_generate", "llm", 
                 f"LLM generated Cube query",
                 data={"query": cube_query, "model": OPENAI_MODEL},
                 duration_ms=llm_ms)
        
        # Step 3: Validate query
        is_valid, error = self.validator.validate(cube_query)
        if not is_valid:
            response.error = error
            response.final_answer = f"❌ Invalid query: {error}"
            self._log(response, "validation", "error", f"Validation failed: {error}")
            return response
        
        self._log(response, "validation", "info", "Query validated successfully")
        
        # Step 4: Get SQL from Cube (for logging)
        sql_start = time.time()
        sql_result = self._get_cube_sql(cube_query)
        sql_ms = int((time.time() - sql_start) * 1000)
        
        if sql_result and "sql" in sql_result:
            response.cube_sql = sql_result["sql"].get("sql", [""])[0] if isinstance(sql_result["sql"], dict) else str(sql_result["sql"])
            self._log(response, "cube_sql", "sql", 
                     "Generated SQL query",
                     data={"sql": response.cube_sql},
                     duration_ms=sql_ms)
        
        # Step 5: Execute query
        tool_call = ToolCall(
            tool_type="cube",
            endpoint="/load",
            params={"query": cube_query},
            description="Cube Analytics Query"
        )
        response.steps.append(tool_call)
        
        exec_start = time.time()
        result = self._call_cube(cube_query)
        exec_ms = int((time.time() - exec_start) * 1000)
        response.results.append(result)
        
        row_count = len(result.get("data", []))
        self._log(response, "cube_execute", "cube", 
                 f"Cube query executed, returned {row_count} rows",
                 data={"row_count": row_count, "endpoint": f"{CUBE_BASE_URL}/load"},
                 duration_ms=exec_ms)
        
        # Step 6: Format response
        response.final_answer = self._format_cube_result(result)
        
        return response
    
    def _handle_detail_query(self, question: str, response: AgentResponse) -> AgentResponse:
        """Handle detail query using VulcanSQL"""
        import re
        
        # Extract issue key
        issue_match = re.search(r'([A-Z]+-\d+)', question)
        if not issue_match:
            # Try to find issue number
            num_match = re.search(r'задач[уа]?\s+#?(\d+)', question, re.I)
            if num_match:
                issue_id = num_match.group(1)
            else:
                response.error = "Could not extract issue ID from query"
                response.final_answer = "❌ Не удалось определить ID задачи"
                self._log(response, "extract_id", "error", "Could not extract issue ID")
                return response
        else:
            issue_id = issue_match.group(1)
        
        self._log(response, "extract_id", "info", f"Extracted issue ID: {issue_id}")
        
        # Determine endpoint
        endpoint = f"/jira/issues/{issue_id}"
        if "комментар" in question.lower() or "comment" in question.lower():
            endpoint = f"/jira/issues/{issue_id}/comments"
        elif "связ" in question.lower() or "link" in question.lower():
            endpoint = f"/jira/issues/{issue_id}/links"
        
        tool_call = ToolCall(
            tool_type="vulcan",
            endpoint=endpoint,
            params={"view": "wide"},
            description=f"Get issue details: {issue_id}"
        )
        response.steps.append(tool_call)
        
        exec_start = time.time()
        result = self._call_vulcan(endpoint, {"view": "wide"})
        exec_ms = int((time.time() - exec_start) * 1000)
        response.results.append(result)
        
        self._log(response, "vulcan_execute", "cube", 
                 f"VulcanSQL query executed",
                 data={"endpoint": endpoint},
                 duration_ms=exec_ms)
        
        response.final_answer = self._format_vulcan_result(result)
        
        return response
    
    def _handle_list_query(self, question: str, response: AgentResponse) -> AgentResponse:
        """Handle list query using VulcanSQL - get list of issues with filters"""
        import re
        
        # Extract project key - look for uppercase words that could be project keys
        # Common patterns: "проекту PORTAL", "project PORTAL", just "PORTAL"
        project_key = None
        
        # Pattern 1: after "проект" word
        match = re.search(r'проект[уеа]?\s+([A-Z]{2,10})\b', question, re.IGNORECASE)
        if match:
            project_key = match.group(1).upper()
        
        # Pattern 2: after "project" word
        if not project_key:
            match = re.search(r'project\s+([A-Z]{2,10})\b', question, re.IGNORECASE)
            if match:
                project_key = match.group(1).upper()
        
        # Pattern 3: standalone project key (uppercase word 2-10 chars)
        if not project_key:
            # Find all uppercase words and check if they are valid project keys
            potential_keys = re.findall(r'\b([A-Z]{2,10})\b', question)
            if potential_keys:
                # Get list of valid projects first
                projects_result = self._call_vulcan("/jira/projects", {"view": "basic"})
                valid_keys = set()
                if isinstance(projects_result, dict) and "data" in projects_result:
                    for p in projects_result["data"]:
                        valid_keys.add(p.get("key", "").upper())
                
                for pk in potential_keys:
                    if pk.upper() in valid_keys:
                        project_key = pk.upper()
                        break
        
        params = {"view": "wide", "limit": "50"}
        
        if project_key:
            self._log(response, "extract_filter", "info", f"Extracted project key: {project_key}")
            
            # Get project_id from project key
            projects_result = self._call_vulcan("/jira/projects", {"view": "wide"})
            project_id = None
            
            # Handle response format {"count": N, "data": [...]}
            projects_data = projects_result
            if isinstance(projects_result, dict) and "data" in projects_result:
                projects_data = projects_result["data"]
            
            if isinstance(projects_data, list):
                for p in projects_data:
                    if p.get("key", "").upper() == project_key:
                        project_id = p.get("id")
                        break
            
            if project_id:
                params["project_id"] = str(project_id)
                self._log(response, "resolve_project", "info", f"Resolved {project_key} -> project_id: {project_id}")
            else:
                self._log(response, "resolve_project", "warning", f"Project {project_key} not found in database")
        
        # Extract status filter
        status_match = re.search(r'статус[ео]?м?\s+["\']?(\w+)["\']?', question, re.IGNORECASE)
        if status_match:
            params["status_category"] = status_match.group(1)
        
        endpoint = "/jira/issues"
        
        tool_call = ToolCall(
            tool_type="vulcan",
            endpoint=endpoint,
            params=params,
            description=f"List issues with filters: {params}"
        )
        response.steps.append(tool_call)
        
        exec_start = time.time()
        result = self._call_vulcan(endpoint, params)
        exec_ms = int((time.time() - exec_start) * 1000)
        response.results.append(result)
        
        self._log(response, "vulcan_execute", "cube", 
                 f"VulcanSQL list query executed",
                 data={"endpoint": endpoint, "params": params},
                 duration_ms=exec_ms)
        
        response.final_answer = self._format_issues_list(result)
        
        return response
    
    def _format_issues_list(self, result) -> str:
        """Format list of issues for display"""
        if isinstance(result, dict) and "error" in result:
            return f"❌ Error: {result['error']}"
        
        # Handle response format {"count": N, "data": [...]} or just list
        data = result
        total_count = None
        if isinstance(result, dict):
            if "data" in result:
                data = result["data"]
                total_count = result.get("count")
            elif "error" in result:
                return f"❌ Error: {result['error']}"
        
        if not data:
            return "📋 No issues found"
        
        count_str = f"{total_count}" if total_count else f"{len(data)}"
        lines = [f"📋 Found {count_str} issues:"]
        
        for i, issue in enumerate(data[:20], 1):
            key = issue.get("key", "?")
            summary = issue.get("summary", "")[:55]
            status = issue.get("status_name") or issue.get("status", "")
            assignee = issue.get("assignee_name") or issue.get("assignee_display_name") or issue.get("assignee", "") or "Unassigned"
            project = issue.get("project_key") or issue.get("project", "")
            
            lines.append(f"  {i}. [{key}] {summary}")
            lines.append(f"      Status: {status} | Assignee: {assignee}")
        
        if len(data) > 20:
            lines.append(f"  ... and {len(data) - 20} more issues")
        
        return "\n".join(lines)
    
    def _get_cube_sql(self, query: Dict) -> Optional[Dict]:
        """Get SQL from Cube /sql endpoint"""
        url = f"{CUBE_BASE_URL}/sql"
        try:
            resp = self.client.post(url, json={"query": query}, headers={"Content-Type": "application/json"})
            return resp.json()
        except Exception as e:
            return {"error": str(e)}
    
    def _call_cube(self, query: Dict) -> Dict:
        """Execute Cube query"""
        url = f"{CUBE_BASE_URL}/load"
        try:
            resp = self.client.post(url, json={"query": query}, headers={"Content-Type": "application/json"})
            return resp.json()
        except Exception as e:
            return {"error": str(e)}
    
    def _call_vulcan(self, endpoint: str, params: Dict) -> Dict:
        """Execute VulcanSQL query"""
        url = f"{VULCAN_BASE_URL}{endpoint}"
        try:
            resp = self.client.get(url, params=params)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}
    
    def _format_cube_result(self, result: Dict) -> str:
        """Format Cube result for display"""
        if "error" in result:
            return f"❌ Error: {result['error']}"
        
        data = result.get("data", [])
        if not data:
            return "📊 No data found"
        
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
    
    def _format_vulcan_result(self, result: Dict) -> str:
        """Format VulcanSQL result for display"""
        if "error" in result:
            return f"❌ Error: {result['error']}"
        
        # Single issue
        if "key" in result and "data" not in result:
            lines = [f"📋 [{result.get('key')}] {result.get('summary', '')}"]
            lines.append(f"📊 Status: {result.get('status', 'N/A')}")
            lines.append(f"👤 Assignee: {result.get('assignee') or 'Unassigned'}")
            lines.append(f"📁 Project: {result.get('project_name', '')}")
            if result.get('description'):
                lines.append(f"📝 {result.get('description', '')[:200]}")
            return "\n".join(lines)
        
        # List of items
        data = result.get("data", [])
        if not data:
            return "No results found"
        
        lines = [f"Found {len(data)} results:"]
        for i, item in enumerate(data[:10], 1):
            if "key" in item:
                lines.append(f"  {i}. [{item.get('key')}] {item.get('summary', '')[:50]}")
            elif "body" in item:
                lines.append(f"  {i}. {item.get('body', '')[:80]}")
            else:
                lines.append(f"  {i}. {str(item)[:80]}")
        
        return "\n".join(lines)


# ============================================
# CLI
# ============================================

def run_cli():
    """Run interactive CLI"""
    agent = SemanticAgent()
    
    print("\n" + "=" * 60)
    print("JIRA Semantic Agent - LLM-powered Query Generator")
    print("=" * 60)
    print(f"Cube API: {CUBE_BASE_URL}")
    print(f"VulcanSQL: {VULCAN_BASE_URL}")
    print(f"Indexed: {len(agent.metadata_loader.members)} measures/dimensions")
    print("-" * 60)
    print("Examples:")
    print("  - Сколько задач по проектам?")
    print("  - Топ исполнителей по количеству закрытых задач")
    print("  - Покажи задачу AUTH-1")
    print("  - Статистика по спринтам")
    print("-" * 60)
    print("Type 'quit' to exit")
    print("=" * 60)
    
    while True:
        try:
            user_input = input("\n🔍 Query: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            response = agent.process(user_input)
            
            print(f"\n📊 Intent: {response.intent}")
            
            if response.relevant_members:
                print(f"🔎 Relevant members: {', '.join(response.relevant_members[:5])}")
            
            if response.generated_cube_query:
                print(f"📝 Generated query:")
                print(json.dumps(response.generated_cube_query, indent=2, ensure_ascii=False)[:500])
            
            if response.cube_sql:
                print(f"\n💾 SQL:")
                print(response.cube_sql[:500])
            
            print(f"\n📞 Steps:")
            for i, step in enumerate(response.steps, 1):
                print(f"   {i}. {step.description}")
                print(f"      Endpoint: {step.endpoint}")
            
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
