"""
JIRA Router Agent - NL → Tool Calls
Semantic Layer router for VulcanSQL (operational) and Cube (analytics)
"""

import os
import re
import json
import httpx
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from dotenv import load_dotenv

load_dotenv()

# ============================================
# Configuration
# ============================================

VULCAN_BASE_URL = os.getenv("VULCAN_BASE_URL", "http://localhost:3001")
CUBE_BASE_URL = os.getenv("CUBE_BASE_URL", "http://localhost:4000/cubejs-api/v1")

# ============================================
# Intent Types
# ============================================

class IntentType(Enum):
    OPERATIONAL = "operational"  # VulcanSQL endpoints
    ANALYTICS = "analytics"      # Cube queries
    MIXED = "mixed"              # Multi-step chains


@dataclass
class ToolCall:
    """Represents a single tool call"""
    tool_type: str  # "vulcan" or "cube"
    endpoint: str
    params: Dict[str, Any]
    description: str


@dataclass
class AgentResponse:
    """Agent response with execution trace"""
    query: str
    intent: IntentType
    steps: List[ToolCall] = field(default_factory=list)
    results: List[Dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    error: Optional[str] = None


# ============================================
# Intent Detection Rules (Semantic Layer)
# ============================================

OPERATIONAL_KEYWORDS = [
    # Russian
    "список", "покажи", "найди", "задач", "карточк", "комментар", "связ", 
    "вложен", "custom field", "кастомн", "спринт",
    "время по задаче", "детали", "подробн",
    # English
    "list", "show", "find", "issue", "card", "comment", "link", "attachment",
    "custom field", "sprint", "detail"
]

ANALYTICS_KEYWORDS = [
    # Russian
    "сколько", "количество", "динамик", "по неделям", "по месяцам", "тренд",
    "throughput", "velocity", "burndown", "wip", "cycle time", "lead time",
    "estimate accuracy", "оценк", "точност", "топ", "рейтинг", "статистик",
    "метрик", "kpi", "производительност", "скорост", "worklogs",
    "среднее", "время выполнения", "в работе", "по исполнителям",
    # English  
    "how many", "count", "trend", "weekly", "monthly", "metrics", "kpi",
    "throughput", "velocity", "burndown", "wip", "cycle time", "lead time",
    "estimate", "accuracy", "top", "ranking", "statistics", "performance",
    "by worklogs", "time spent", "by assignee", "average"
]

MIXED_KEYWORDS = [
    # Patterns that suggest multi-step (Russian)
    "и посчитай", "и оцени", "затем", "потом", "а также", "плюс",
    "и покажи метрики", "и статистику", "со статистикой", "с метриками",
    # Patterns that suggest multi-step (English)
    "and calculate", "and then", "also show", "plus metrics", "with stats",
    "and show metrics", "and analytics"
]

# ============================================
# Tool Mapping (Semantic Layer Core)
# ============================================

VULCAN_TOOLS = {
    "list_issues": {
        "endpoint": "/jira/issues",
        "params": ["project_id", "sprint_id", "assignee_id", "status_category", "limit", "view"],
        "keywords": ["список задач", "задачи", "issues", "list issues", "карточки"]
    },
    "get_issue": {
        "endpoint": "/jira/issues/{issue_id}",
        "params": ["issue_id", "view"],
        "keywords": ["задача", "issue", "карточка", "детали задачи", "issue detail", "подробност", "details", "detail"]
    },
    "search_issues": {
        "endpoint": "/jira/issues/search",
        "params": ["q", "project_id", "status_category", "limit"],
        "keywords": ["найди", "поиск", "search", "find", "искать"]
    },
    "issue_comments": {
        "endpoint": "/jira/issues/{issue_id}/comments",
        "params": ["issue_id", "limit"],
        "keywords": ["комментарии", "comments", "обсуждение"]
    },
    "issue_links": {
        "endpoint": "/jira/issues/{issue_id}/links",
        "params": ["issue_id"],
        "keywords": ["связи", "links", "связанные", "зависимости"]
    },
    "issue_worklogs": {
        "endpoint": "/jira/issues/{issue_id}/worklogs",
        "params": ["issue_id"],
        "keywords": ["worklogs", "время", "затраченное время", "time spent"]
    },
    "list_projects": {
        "endpoint": "/jira/projects",
        "params": ["limit", "view"],
        "keywords": ["проекты", "projects", "список проектов"]
    },
    "list_sprints": {
        "endpoint": "/jira/sprints",
        "params": ["project_id", "status", "limit", "view"],
        "keywords": ["спринты", "sprints", "список спринтов"]
    },
    "list_users": {
        "endpoint": "/jira/users",
        "params": ["q", "limit", "view"],
        "keywords": ["пользователи", "пользователей", "users", "команда", "команды", "team", "members"]
    }
}

CUBE_QUERIES = {
    "issue_count": {
        "measures": ["fact_issues.created_count", "fact_issues.open_count", "fact_issues.throughput"],
        "dimensions": ["fact_issues.project_name"],
        "keywords": ["количество", "сколько", "count", "how many", "total", "всего"]
    },
    "throughput": {
        "measures": ["fact_issues.throughput", "fact_issues.created_count"],
        "dimensions": ["fact_issues.project_name"],
        "keywords": ["throughput", "пропускная способность", "завершено", "resolved"]
    },
    "throughput_weekly": {
        "measures": ["fact_issues.throughput", "fact_issues.created_count"],
        "timeDimensions": [{"dimension": "fact_issues.created_at", "granularity": "week"}],
        "keywords": ["по неделям", "weekly", "динамика", "тренд"]
    },
    "backlog": {
        "measures": ["fact_issues.open_count", "fact_issues.created_count"],
        "dimensions": ["fact_issues.project_name"],
        "keywords": ["backlog", "бэклог", "открытые", "open issues"]
    },
    "wip": {
        "measures": ["fact_issues.wip_count"],
        "dimensions": ["fact_issues.project_name", "fact_issues.assignee_name"],
        "keywords": ["wip", "в работе", "in progress", "work in progress", "по исполнителям", "по assignee", "задач в работе"]
    },
    "lead_time": {
        "measures": ["fact_issues.avg_lead_time", "fact_issues.avg_open_age"],
        "dimensions": ["fact_issues.project_name"],
        "keywords": ["lead time", "cycle time", "время выполнения", "среднее время", "среднее время выполнения", "average time"]
    },
    "reopen_rate": {
        "measures": ["fact_status_changes.reopen_count", "fact_status_changes.issues_completed"],
        "dimensions": ["fact_status_changes.project_name"],
        "keywords": ["reopen", "переоткрытие", "reopened"]
    },
    "worklogs_by_author": {
        "measures": ["fact_worklogs.total_time_spent_hours"],
        "dimensions": ["fact_worklogs.author_name"],
        "keywords": ["время по автору", "worklogs", "топ по времени", "time by author", "top authors", "топ авторов", "by worklogs"]
    },
    "worklogs_by_project": {
        "measures": ["fact_worklogs.total_time_spent_hours"],
        "dimensions": ["fact_worklogs.project_name"],
        "keywords": ["время по проекту", "project time"]
    },
    "estimate_accuracy": {
        "measures": ["fact_issues.avg_estimate_accuracy", "fact_issues.total_time_spent_hours"],
        "dimensions": ["fact_issues.project_name"],
        "keywords": ["estimate", "accuracy", "точность оценки", "оценка"]
    },
    "sprint_velocity": {
        "measures": ["fact_sprint_reports.avg_committed_points", "fact_sprint_reports.avg_completed_points"],
        "dimensions": ["fact_sprint_reports.sprint_name", "fact_sprint_reports.project_name"],
        "keywords": ["velocity", "скорость", "спринт", "committed", "completed"]
    },
    "burndown": {
        "dimensions": ["fact_sprint_reports.sprint_name", "fact_sprint_reports.burndown_data"],
        "keywords": ["burndown", "сгорание", "график"]
    },
    "user_stats": {
        "measures": ["users.count", "users.active_count", "users.inactive_count"],
        "dimensions": [],
        "keywords": ["статистика пользователей", "сколько пользователей", "количество пользователей", 
                     "user stats", "user count", "active users count", "inactive users count",
                     "сколько активных", "сколько неактивных", "всего пользователей"]
    }
}


# ============================================
# Router Agent
# ============================================

class JiraRouterAgent:
    """Main router agent for JIRA queries"""
    
    def __init__(self, vulcan_url: str = VULCAN_BASE_URL, cube_url: str = CUBE_BASE_URL):
        self.vulcan_url = vulcan_url
        self.cube_url = cube_url
        self.client = httpx.Client(timeout=30.0)
        self._projects_cache: Dict[str, int] = {}
        self._users_cache: Dict[str, int] = {}
    
    def detect_intent(self, query: str) -> IntentType:
        """Detect intent type from natural language query"""
        query_lower = query.lower()
        
        # Check for MIXED intent FIRST (explicit chain keywords)
        has_mixed = any(kw in query_lower for kw in MIXED_KEYWORDS)
        if has_mixed:
            return IntentType.MIXED
        
        # Strong analytics keywords - these override operational keywords
        strong_analytics = [
            "throughput", "velocity", "burndown", "wip", "cycle time", "lead time",
            "estimate accuracy", "reopen", "metrics", "kpi", "статистик", 
            "сколько", "количество", "топ", "top", "performance", "count",
            "how many", "total", "среднее", "average", "в работе", "время выполнения"
        ]
        
        # Check for strong analytics keywords
        has_strong_analytics = any(kw in query_lower for kw in strong_analytics)
        if has_strong_analytics:
            return IntentType.ANALYTICS
        
        # Check for mixed intent (both operational and analytics keywords)
        has_operational = any(kw in query_lower for kw in OPERATIONAL_KEYWORDS)
        has_analytics = any(kw in query_lower for kw in ANALYTICS_KEYWORDS)
        
        if has_operational and has_analytics:
            return IntentType.MIXED
        elif has_analytics:
            return IntentType.ANALYTICS
        else:
            return IntentType.OPERATIONAL
    
    def extract_params(self, query: str) -> Dict[str, Any]:
        """Extract parameters from natural language query"""
        params = {}
        query_lower = query.lower()
        
        # Extract issue ID/key FIRST - formats: [AI-3], AI-3, задача #3, issue #3
        issue_match = re.search(r'\[([A-Z]+-\d+)\]', query)  # [AUTH-1] format
        if not issue_match:
            issue_match = re.search(r'([A-Z]+-\d+)', query)  # AUTH-1 format
        if not issue_match:
            issue_match = re.search(r'задач[а-яё]*\s+#?(\d+)', query, re.I)
        if not issue_match:
            issue_match = re.search(r'issue\s+#?(\d+)', query, re.I)
        if issue_match:
            params["issue_id"] = issue_match.group(1)
        
        # Extract project key/name - support formats: project AUTH, проект AUTH, [AUTH], "AUTH"
        project_match = re.search(r'проект[а-яё]*\s+[\["\']?([A-Za-zА-Яа-яЁё0-9_-]+)[\]"\']?', query, re.I)
        if not project_match:
            project_match = re.search(r'project\s+[\["\']?([A-Za-z0-9_-]+)[\]"\']?', query, re.I)
        if not project_match:
            # Match standalone [PROJECT] format - but not issue keys like [AI-3]
            project_match = re.search(r'\[([A-Za-z0-9_]+)\]', query)
            if project_match and re.match(r'^[A-Z]+-\d+$', project_match.group(1)):
                project_match = None
        if project_match:
            params["project_key"] = project_match.group(1).upper()
        
        # Extract sprint
        sprint_match = re.search(r'спринт[а-яё]*\s+["\']?(\d+|[A-Za-zА-Яа-яЁё0-9\s]+)["\']?', query, re.I)
        if not sprint_match:
            sprint_match = re.search(r'sprint\s+["\']?(\d+|[A-Za-z0-9\s]+)["\']?', query, re.I)
        if sprint_match:
            params["sprint_id"] = sprint_match.group(1).strip()
        
        # Extract limit
        limit_match = re.search(r'(\d+)\s*(задач|issues|результат|records|топ|top)', query, re.I)
        if not limit_match:
            limit_match = re.search(r'(top|топ|первые|last)\s*(\d+)', query, re.I)
        if limit_match:
            params["limit"] = int(limit_match.group(2) if limit_match.lastindex == 2 else limit_match.group(1))
        
        # Extract search query
        # Pattern: "по слову X", "содержащие X", "со словом X"
        search_match = re.search(r'по слов[у|а|ом]\s+["\']?(\w+)["\']?', query, re.I)
        if not search_match:
            search_match = re.search(r'содержащ\w*\s+["\']?(\w+)["\']?', query, re.I)
        if not search_match:
            search_match = re.search(r'(search|find)\s+(?:for\s+)?["\']?(\w+)["\']?', query, re.I)
            if search_match:
                search_match = type('obj', (object,), {'group': lambda self, n: search_match.group(2)})()
        if search_match:
            params["search_query"] = search_match.group(1).strip()
        
        # Extract date range keywords
        weeks_match = re.search(r'last\s+(\d+)\s+weeks?', query_lower)
        days_match = re.search(r'last\s+(\d+)\s+days?', query_lower)
        ru_weeks_match = re.search(r'(\d+)\s+недел', query_lower)
        ru_days_match = re.search(r'(\d+)\s+дн', query_lower)
        
        if weeks_match:
            weeks = int(weeks_match.group(1))
            params["date_range"] = f"last {weeks * 7} days"
        elif days_match:
            params["date_range"] = f"last {days_match.group(1)} days"
        elif ru_weeks_match:
            weeks = int(ru_weeks_match.group(1))
            params["date_range"] = f"last {weeks * 7} days"
        elif ru_days_match:
            params["date_range"] = f"last {ru_days_match.group(1)} days"
        elif "неделя" in query_lower or "week" in query_lower or "за неделю" in query_lower or "последн" in query_lower and "недел" in query_lower:
            params["date_range"] = "last 7 days"
        elif "месяц" in query_lower or "month" in query_lower:
            params["date_range"] = "last 30 days"
        
        # Extract status
        if "открыт" in query_lower or "open" in query_lower or "todo" in query_lower:
            params["status_category"] = "todo"
        elif "в работе" in query_lower or "in progress" in query_lower:
            params["status_category"] = "in_progress"
        elif "закрыт" in query_lower or "done" in query_lower or "завершен" in query_lower:
            params["status_category"] = "done"
        
        # Extract assignee name
        assignee_match = re.search(r'исполнител[ья]?\s+["\']?([A-Za-zА-Яа-яЁё\s]+)["\']?', query, re.I)
        if not assignee_match:
            assignee_match = re.search(r'assignee\s+["\']?([A-Za-z\s]+)["\']?', query, re.I)
        if not assignee_match:
            assignee_match = re.search(r'(?:от|на|у)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', query)  # "от John" or "от John Smith"
        if not assignee_match:
            # Try to find capitalized name after common keywords
            assignee_match = re.search(r'(?:задач[иа]?|issues?)\s+(?:на|от|у|for|by)\s+([A-Z][a-z]+)', query, re.I)
        if assignee_match:
            params["assignee_name"] = assignee_match.group(1).strip()
        
        # Extract is_active for users
        if "неактивн" in query_lower or "inactive" in query_lower:
            params["is_active"] = False
        elif "активн" in query_lower or "active" in query_lower:
            params["is_active"] = True
        
        return params
    
    def resolve_project_id(self, project_key: str) -> Optional[int]:
        """Resolve project key/name to ID"""
        if project_key in self._projects_cache:
            return self._projects_cache[project_key]
        
        try:
            resp = self.client.get(f"{self.vulcan_url}/jira/projects", params={"view": "basic"})
            if resp.status_code == 200:
                data = resp.json()
                for proj in data.get("data", []):
                    self._projects_cache[proj["key"]] = proj["id"]
                    self._projects_cache[proj["name"].lower()] = proj["id"]
                return self._projects_cache.get(project_key) or self._projects_cache.get(project_key.lower())
        except Exception:
            pass
        return None
    
    def resolve_assignee_id(self, assignee_name: str) -> Optional[int]:
        """Resolve assignee name to ID"""
        name_lower = assignee_name.lower()
        if name_lower in self._users_cache:
            return self._users_cache[name_lower]
        
        try:
            resp = self.client.get(f"{self.vulcan_url}/jira/users", params={"limit": 100})
            if resp.status_code == 200:
                data = resp.json()
                for user in data.get("data", []):
                    display_name = user.get("display_name", "").lower()
                    self._users_cache[display_name] = user["id"]
                    # Also cache first name and last name separately
                    parts = display_name.split()
                    if parts:
                        self._users_cache[parts[0]] = user["id"]  # First name
                        if len(parts) > 1:
                            self._users_cache[parts[-1]] = user["id"]  # Last name
                
                # Try to find match
                if name_lower in self._users_cache:
                    return self._users_cache[name_lower]
                # Partial match
                for cached_name, uid in self._users_cache.items():
                    if name_lower in cached_name or cached_name in name_lower:
                        return uid
        except Exception:
            pass
        return None
    
    def select_vulcan_tool(self, query: str, params: Dict) -> Tuple[str, str, Dict]:
        """Select appropriate VulcanSQL tool based on query"""
        query_lower = query.lower()
        
        # If we have issue_id and query is about single issue (not list/search), use get_issue
        list_keywords = ["список", "list", "все", "all", "найди", "search", "find"]
        is_list_query = any(kw in query_lower for kw in list_keywords)
        
        if "issue_id" in params and not is_list_query:
            # Default to get_issue when we have a specific issue
            best_tool = "get_issue"
            # But check if user wants comments, links, worklogs
            if any(kw in query_lower for kw in ["комментар", "comment"]):
                best_tool = "issue_comments"
            elif any(kw in query_lower for kw in ["связ", "link"]):
                best_tool = "issue_links"
            elif any(kw in query_lower for kw in ["worklog", "время"]):
                best_tool = "issue_worklogs"
        else:
            # If we have a search query, use search_issues
            if "search_query" in params:
                best_tool = "search_issues"
            else:
                # Match against tool keywords
                best_tool = "list_issues"
                best_score = 0
                
                for tool_name, tool_config in VULCAN_TOOLS.items():
                    score = sum(1 for kw in tool_config["keywords"] if kw in query_lower)
                    
                    # Skip tools that require issue_id if we don't have it
                    if "{issue_id}" in tool_config["endpoint"] and "issue_id" not in params:
                        continue
                        
                    if score > best_score:
                        best_score = score
                        best_tool = tool_name
        
        tool_config = VULCAN_TOOLS[best_tool]
        endpoint = tool_config["endpoint"]
        
        # Build request params
        req_params = {}
        
        if "issue_id" in params and "{issue_id}" in endpoint:
            endpoint = endpoint.replace("{issue_id}", str(params["issue_id"]))
        elif "issue_id" in params:
            req_params["issue_id"] = params["issue_id"]
        
        if "project_key" in params:
            project_id = self.resolve_project_id(params["project_key"])
            if project_id:
                req_params["project_id"] = project_id
        
        if "search_query" in params:
            req_params["q"] = params["search_query"]
        
        if "status_category" in params:
            req_params["status_category"] = params["status_category"]
        
        if "assignee_name" in params:
            assignee_id = self.resolve_assignee_id(params["assignee_name"])
            if assignee_id:
                req_params["assignee_id"] = assignee_id
        
        if "is_active" in params:
            req_params["is_active"] = "true" if params["is_active"] else "false"
        
        if "limit" in params:
            req_params["limit"] = params["limit"]
        else:
            req_params["limit"] = 10  # Default limit
        
        req_params["view"] = "wide"
        
        return best_tool, endpoint, req_params
    
    def select_cube_query(self, query: str, params: Dict) -> Tuple[str, Dict]:
        """Select appropriate Cube query based on query"""
        query_lower = query.lower()
        
        best_query = "throughput"
        best_score = 0
        
        for query_name, query_config in CUBE_QUERIES.items():
            score = sum(1 for kw in query_config["keywords"] if kw in query_lower)
            if score > best_score:
                best_score = score
                best_query = query_name
        
        query_config = CUBE_QUERIES[best_query].copy()
        
        # Determine cube prefix for this query
        cube_prefix = "fact_issues"
        if "users." in str(query_config.get("measures", [])):
            cube_prefix = "users"
        elif "fact_worklogs" in str(query_config.get("measures", [])):
            cube_prefix = "fact_worklogs"
        elif "fact_sprint_reports" in str(query_config.get("measures", [])):
            cube_prefix = "fact_sprint_reports"
        elif "fact_status_changes" in str(query_config.get("measures", [])):
            cube_prefix = "fact_status_changes"
        
        # Build Cube query
        cube_query = {"query": {}}
        
        if "measures" in query_config:
            cube_query["query"]["measures"] = query_config["measures"]
        
        if "dimensions" in query_config:
            cube_query["query"]["dimensions"] = query_config["dimensions"]
        
        # Add time dimensions with date range
        if "timeDimensions" in query_config:
            cube_query["query"]["timeDimensions"] = query_config["timeDimensions"]
        elif "date_range" in params:
            # Map cube to time dimension
            time_dim_map = {
                "fact_issues": "fact_issues.created_at",
                "fact_worklogs": "fact_worklogs.started_at",
                "fact_sprint_reports": "fact_sprint_reports.start_date",
                "fact_status_changes": "fact_status_changes.changed_at"
            }
            time_dim = time_dim_map.get(cube_prefix, f"{cube_prefix}.created_at")
            cube_query["query"]["timeDimensions"] = [{
                "dimension": time_dim,
                "dateRange": params["date_range"]
            }]
        
        # Add filters
        filters = []
        if "project_key" in params:
            filters.append({
                "member": f"{cube_prefix}.project_key",
                "operator": "equals",
                "values": [params["project_key"]]
            })
        
        if filters:
            cube_query["query"]["filters"] = filters
        
        # Add limit and order
        cube_query["query"]["limit"] = params.get("limit", 10)
        
        # Add order for top N queries
        if "measures" in query_config:
            cube_query["query"]["order"] = {query_config["measures"][0]: "desc"}
        
        return best_query, cube_query
    
    def call_vulcan(self, endpoint: str, params: Dict) -> Dict:
        """Call VulcanSQL endpoint"""
        url = f"{self.vulcan_url}{endpoint}"
        try:
            resp = self.client.get(url, params=params)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}
    
    def call_cube(self, query: Dict) -> Dict:
        """Call Cube API"""
        url = f"{self.cube_url}/load"
        try:
            resp = self.client.post(url, json=query, headers={"Content-Type": "application/json"})
            return resp.json()
        except Exception as e:
            return {"error": str(e)}
    
    def format_result(self, result: Dict, tool_type: str) -> str:
        """Format result for display"""
        if "error" in result:
            return f"❌ Error: {result['error']}"
        
        if tool_type == "vulcan":
            # Check if it's a single issue (has 'key' field directly, not in 'data')
            if "key" in result and "data" not in result:
                # Format single issue details
                lines = [f"📋 Issue: [{result.get('key')}] {result.get('summary', '')}"]
                lines.append(f"")
                lines.append(f"📝 Description: {(result.get('description') or 'No description')[:200]}")
                lines.append(f"")
                lines.append(f"📊 Status: {result.get('status', 'N/A')} ({result.get('status_category', '')})")
                lines.append(f"🏷️  Type: {result.get('issue_type', 'N/A')}")
                lines.append(f"⚡ Priority: {result.get('priority', 'N/A')}")
                lines.append(f"📁 Project: {result.get('project_name', '')} [{result.get('project_key', '')}]")
                lines.append(f"")
                lines.append(f"👤 Assignee: {result.get('assignee') or 'Unassigned'}")
                lines.append(f"👤 Reporter: {result.get('reporter') or 'N/A'}")
                lines.append(f"")
                lines.append(f"📅 Created: {str(result.get('created_at', ''))[:10]}")
                lines.append(f"📅 Due Date: {str(result.get('due_date', '')) or 'Not set'}")
                lines.append(f"✅ Resolved: {str(result.get('resolved_at', ''))[:10] if result.get('resolved_at') else 'Not resolved'}")
                if result.get('sprint_name'):
                    lines.append(f"🏃 Sprint: {result.get('sprint_name')}")
                if result.get('story_points'):
                    lines.append(f"📏 Story Points: {result.get('story_points')}")
                return "\n".join(lines)
            
            data = result.get("data", [])
            if not data:
                return "No results found."
            
            # Format as simple table
            lines = [f"Found {len(data)} results:"]
            for i, item in enumerate(data[:10], 1):
                if "key" in item:
                    assignee = item.get('assignee') or 'Unassigned'
                    status = item.get('status', '')
                    summary = item.get('summary', item.get('name', ''))[:40]
                    lines.append(f"  {i}. [{item.get('key')}] {summary}")
                    lines.append(f"      👤 {assignee} | 📊 {status}")
                elif "display_name" in item:
                    lines.append(f"  {i}. {item.get('display_name')} ({item.get('email', '')})")
                elif "name" in item:
                    lines.append(f"  {i}. {item.get('name')} - {item.get('key', '')}")
                else:
                    lines.append(f"  {i}. {str(item)[:80]}")
            return "\n".join(lines)
        
        elif tool_type == "cube":
            data = result.get("data", [])
            if not data:
                return "No analytics data found."
            
            lines = [f"Analytics results ({len(data)} rows):"]
            for i, item in enumerate(data[:10], 1):
                parts = []
                for k, v in item.items():
                    short_key = k.split(".")[-1]
                    parts.append(f"{short_key}: {v}")
                lines.append(f"  {i}. {', '.join(parts)}")
            return "\n".join(lines)
        
        return json.dumps(result, indent=2, ensure_ascii=False)[:500]
    
    def process(self, query: str, use_semantic_layer: bool = True) -> AgentResponse:
        """Process natural language query
        
        Args:
            query: Natural language query
            use_semantic_layer: If True, use smart routing (Data API + Cube).
                              If False, only use Data API (no analytics).
        """
        response = AgentResponse(query=query, intent=IntentType.OPERATIONAL)
        
        try:
            # Step 1: Detect intent
            if use_semantic_layer:
                response.intent = self.detect_intent(query)
            else:
                # Without semantic layer, always use operational (Data API only)
                response.intent = IntentType.OPERATIONAL
            
            # Step 2: Extract parameters
            params = self.extract_params(query)
            
            # Step 3: Execute based on intent
            if response.intent == IntentType.OPERATIONAL:
                tool_name, endpoint, req_params = self.select_vulcan_tool(query, params)
                
                tool_call = ToolCall(
                    tool_type="vulcan",
                    endpoint=endpoint,
                    params=req_params,
                    description=f"VulcanSQL: {tool_name}"
                )
                response.steps.append(tool_call)
                
                result = self.call_vulcan(endpoint, req_params)
                response.results.append(result)
                response.final_answer = self.format_result(result, "vulcan")
            
            elif response.intent == IntentType.ANALYTICS:
                query_name, cube_query = self.select_cube_query(query, params)
                
                tool_call = ToolCall(
                    tool_type="cube",
                    endpoint="/load",
                    params=cube_query,
                    description=f"Cube: {query_name}"
                )
                response.steps.append(tool_call)
                
                result = self.call_cube(cube_query)
                response.results.append(result)
                response.final_answer = self.format_result(result, "cube")
            
            elif response.intent == IntentType.MIXED:
                # Execute chain: first operational, then analytics
                
                # Step 1: Operational
                tool_name, endpoint, req_params = self.select_vulcan_tool(query, params)
                tool_call1 = ToolCall(
                    tool_type="vulcan",
                    endpoint=endpoint,
                    params=req_params,
                    description=f"Step 1 - VulcanSQL: {tool_name}"
                )
                response.steps.append(tool_call1)
                result1 = self.call_vulcan(endpoint, req_params)
                response.results.append(result1)
                
                # Step 2: Analytics
                query_name, cube_query = self.select_cube_query(query, params)
                tool_call2 = ToolCall(
                    tool_type="cube",
                    endpoint="/load",
                    params=cube_query,
                    description=f"Step 2 - Cube: {query_name}"
                )
                response.steps.append(tool_call2)
                result2 = self.call_cube(cube_query)
                response.results.append(result2)
                
                # Combine results
                answer_parts = [
                    "=== Operational Results ===",
                    self.format_result(result1, "vulcan"),
                    "",
                    "=== Analytics Results ===",
                    self.format_result(result2, "cube")
                ]
                response.final_answer = "\n".join(answer_parts)
        
        except Exception as e:
            response.error = str(e)
            response.final_answer = f"❌ Error: {str(e)}"
        
        return response


# ============================================
# Demo Scenarios
# ============================================

DEMO_SCENARIOS = [
    {
        "id": 1,
        "name": "List issues for project AUTH",
        "query": "Покажи задачи проекта AUTH",
        "query_en": "Show issues for project AUTH"
    },
    {
        "id": 2,
        "name": "Issue details with comments",
        "query": "Покажи задачу #1 с комментариями",
        "query_en": "Show issue #1 with comments"
    },
    {
        "id": 3,
        "name": "Search issues",
        "query": "Найди задачи по слову database",
        "query_en": "Search issues containing database"
    },
    {
        "id": 4,
        "name": "Throughput by project",
        "query": "Сколько задач завершено по проектам за последний месяц?",
        "query_en": "How many issues resolved by project last month?"
    },
    {
        "id": 5,
        "name": "WIP analysis",
        "query": "Покажи WIP (задачи в работе) по исполнителям",
        "query_en": "Show WIP (in progress) by assignee"
    },
    {
        "id": 6,
        "name": "Top authors by worklogs + profiles",
        "query": "Топ авторов по времени за 14 дней и их профили",
        "query_en": "Top authors by worklogs last 14 days and their profiles"
    },
    {
        "id": 7,
        "name": "Sprint velocity",
        "query": "Покажи velocity по спринтам: committed vs completed",
        "query_en": "Show sprint velocity: committed vs completed points"
    }
]


# ============================================
# CLI Interface
# ============================================

def run_cli():
    """Run interactive CLI"""
    agent = JiraRouterAgent()
    
    print("=" * 60)
    print("JIRA Router Agent - Natural Language Interface")
    print("=" * 60)
    print(f"VulcanSQL: {VULCAN_BASE_URL}")
    print(f"Cube API:  {CUBE_BASE_URL}")
    print("-" * 60)
    print("Demo scenarios:")
    for s in DEMO_SCENARIOS:
        print(f"  [{s['id']}] {s['name']}")
    print("-" * 60)
    print("Type a question, number (1-7) for demo, or 'quit' to exit")
    print("=" * 60)
    
    while True:
        try:
            user_input = input("\n🔍 Query: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            # Check for demo scenario
            if user_input.isdigit():
                scenario_id = int(user_input)
                scenario = next((s for s in DEMO_SCENARIOS if s["id"] == scenario_id), None)
                if scenario:
                    user_input = scenario["query_en"]
                    print(f"📋 Demo: {scenario['name']}")
                    print(f"   Query: {user_input}")
            
            # Process query
            response = agent.process(user_input)
            
            print(f"\n📊 Intent: {response.intent.value}")
            print(f"📞 Steps:")
            for i, step in enumerate(response.steps, 1):
                print(f"   {i}. {step.description}")
                print(f"      Endpoint: {step.endpoint}")
                print(f"      Params: {json.dumps(step.params, ensure_ascii=False)[:100]}")
            
            print(f"\n📝 Result:")
            print(response.final_answer)
            
            if response.error:
                print(f"\n⚠️ Error: {response.error}")
        
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    run_cli()
