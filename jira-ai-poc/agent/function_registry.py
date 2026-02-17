"""
Function Registry - Catalog of available tools for the Semantic Agent

Each tool is described with:
- name: machine-readable identifier
- description: human-readable description (for LLM context)
- tool_type: "cube" or "vulcan"
- parameters: list of parameters with types and descriptions
- examples: NL queries that map to this tool
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class ToolType(Enum):
    CUBE = "cube"
    VULCAN = "vulcan"


@dataclass
class ToolParameter:
    """Parameter definition for a tool"""
    name: str
    type: str  # "string", "number", "boolean", "date"
    description: str
    required: bool = False
    default: Any = None
    enum_values: List[str] = field(default_factory=list)  # For enum parameters


@dataclass
class ToolDefinition:
    """Definition of a single tool"""
    name: str
    description: str
    tool_type: ToolType
    endpoint: str  # API endpoint or Cube measures/dimensions
    parameters: List[ToolParameter] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)  # Example NL queries
    keywords: List[str] = field(default_factory=list)  # Keywords for matching
    
    # For Cube tools: predefined query structure
    cube_measures: List[str] = field(default_factory=list)
    cube_dimensions: List[str] = field(default_factory=list)
    cube_filters: List[Dict] = field(default_factory=list)


# ============================================
# DataAPI (VulcanSQL) Tools
# ============================================

VULCAN_TOOLS = [
    ToolDefinition(
        name="list_issues",
        description="Get list of JIRA issues with optional filters",
        tool_type=ToolType.VULCAN,
        endpoint="/jira/issues",
        parameters=[
            ToolParameter("project_id", "number", "Filter by project ID"),
            ToolParameter("sprint_id", "number", "Filter by sprint ID"),
            ToolParameter("assignee_id", "number", "Filter by assignee user ID"),
            ToolParameter("status_category", "string", "Filter by status category", 
                         enum_values=["todo", "in_progress", "done"]),
            ToolParameter("limit", "number", "Max results to return", default=50),
            ToolParameter("view", "string", "Response detail level", default="wide",
                         enum_values=["basic", "wide"]),
        ],
        examples=[
            "покажи задачи проекта AUTH",
            "список задач в спринте",
            "задачи исполнителя John",
            "открытые задачи",
            "show issues for project PORTAL",
            "list all issues in sprint 2",
        ],
        keywords=["список", "задачи", "покажи задачи", "все задачи", "issues", "list issues", "show issues"]
    ),
    
    ToolDefinition(
        name="get_issue_details",
        description="Get detailed information about a single issue by ID or key",
        tool_type=ToolType.VULCAN,
        endpoint="/jira/issues/{id}",
        parameters=[
            ToolParameter("id", "string", "Issue ID or key (e.g., AUTH-1)", required=True),
            ToolParameter("view", "string", "Response detail level", default="wide",
                         enum_values=["basic", "wide"]),
        ],
        examples=[
            "покажи задачу AUTH-1",
            "детали задачи PORTAL-15",
            "информация по задаче #123",
            "show issue AUTH-1",
            "get issue details for PORTAL-5",
        ],
        keywords=["задача", "детали", "информация", "issue", "details", "show issue"]
    ),
    
    ToolDefinition(
        name="search_issues",
        description="Search issues by text query",
        tool_type=ToolType.VULCAN,
        endpoint="/jira/issues/search",
        parameters=[
            ToolParameter("q", "string", "Search query text", required=True),
            ToolParameter("limit", "number", "Max results", default=20),
        ],
        examples=[
            "найди задачи про database",
            "поиск задач по слову authentication",
            "search issues about login",
            "find issues containing error",
        ],
        keywords=["найди", "поиск", "search", "find", "containing"]
    ),
    
    ToolDefinition(
        name="get_issue_comments",
        description="Get comments for a specific issue",
        tool_type=ToolType.VULCAN,
        endpoint="/jira/issues/{id}/comments",
        parameters=[
            ToolParameter("id", "string", "Issue ID or key", required=True),
        ],
        examples=[
            "комментарии к задаче AUTH-1",
            "comments for issue PORTAL-5",
            "покажи комментарии AUTH-10",
        ],
        keywords=["комментарии", "comments"]
    ),
    
    ToolDefinition(
        name="get_issue_links",
        description="Get linked issues for a specific issue",
        tool_type=ToolType.VULCAN,
        endpoint="/jira/issues/{id}/links",
        parameters=[
            ToolParameter("id", "string", "Issue ID or key", required=True),
        ],
        examples=[
            "связи задачи AUTH-1",
            "links for issue PORTAL-5",
            "связанные задачи",
        ],
        keywords=["связи", "links", "linked", "связанные"]
    ),
    
    ToolDefinition(
        name="list_projects",
        description="Get list of all projects",
        tool_type=ToolType.VULCAN,
        endpoint="/jira/projects",
        parameters=[
            ToolParameter("view", "string", "Response detail level", default="basic",
                         enum_values=["basic", "wide"]),
        ],
        examples=[
            "список проектов",
            "все проекты",
            "show all projects",
            "list projects",
        ],
        keywords=["проекты", "projects"]
    ),
    
    ToolDefinition(
        name="list_sprints",
        description="Get list of sprints",
        tool_type=ToolType.VULCAN,
        endpoint="/jira/sprints",
        parameters=[
            ToolParameter("board_id", "number", "Filter by board ID"),
            ToolParameter("status", "string", "Filter by sprint status",
                         enum_values=["active", "closed", "future"]),
        ],
        examples=[
            "список спринтов",
            "активные спринты",
            "show sprints",
            "list active sprints",
        ],
        keywords=["спринты", "sprints", "итерации"]
    ),
    
    ToolDefinition(
        name="list_users",
        description="Get list of users",
        tool_type=ToolType.VULCAN,
        endpoint="/jira/users",
        parameters=[
            ToolParameter("q", "string", "Search by name"),
            ToolParameter("limit", "number", "Max results", default=100),
        ],
        examples=[
            "список пользователей",
            "найди пользователя John",
            "show users",
            "list all users",
        ],
        keywords=["пользователи", "users", "исполнители"]
    ),
    
    ToolDefinition(
        name="get_issue_worklogs",
        description="Get worklogs (time tracking) for a specific issue",
        tool_type=ToolType.VULCAN,
        endpoint="/jira/issues/{id}/worklogs",
        parameters=[
            ToolParameter("id", "string", "Issue ID or key", required=True),
        ],
        examples=[
            "время по задаче AUTH-1",
            "worklogs for issue PORTAL-5",
            "сколько времени потрачено на задачу",
        ],
        keywords=["worklogs", "время", "time spent", "затраченное"]
    ),
]


# ============================================
# Cube Analytics Tools
# ============================================

CUBE_TOOLS = [
    ToolDefinition(
        name="get_issues_count_by_project",
        description="Get count of issues grouped by project",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_issues.created_count"],
        cube_dimensions=["fact_issues.project_name"],
        parameters=[
            ToolParameter("limit", "number", "Max projects to return", default=10),
        ],
        examples=[
            "сколько задач по проектам",
            "количество задач в каждом проекте",
            "issues count by project",
            "how many issues per project",
        ],
        keywords=["сколько", "количество", "по проектам", "count", "how many", "per project"]
    ),
    
    ToolDefinition(
        name="get_throughput_by_project",
        description="Get count of resolved/completed issues by project (throughput)",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_issues.throughput"],
        cube_dimensions=["fact_issues.project_name"],
        parameters=[
            ToolParameter("limit", "number", "Max projects to return", default=10),
        ],
        examples=[
            "throughput по проектам",
            "сколько задач завершено по проектам",
            "completed issues by project",
            "resolved issues per project",
        ],
        keywords=["throughput", "завершено", "resolved", "completed", "закрыто"]
    ),
    
    ToolDefinition(
        name="get_wip_by_assignee",
        description="Get count of in-progress issues (WIP) by assignee",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_issues.wip_count"],
        cube_dimensions=["fact_issues.assignee_name"],
        parameters=[
            ToolParameter("limit", "number", "Max assignees to return", default=10),
        ],
        examples=[
            "WIP по исполнителям",
            "задачи в работе по исполнителям",
            "work in progress by assignee",
            "in progress issues per person",
        ],
        keywords=["wip", "в работе", "in progress", "по исполнителям", "by assignee"]
    ),
    
    ToolDefinition(
        name="get_backlog_by_project",
        description="Get count of open/unresolved issues (backlog) by project",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_issues.open_count"],
        cube_dimensions=["fact_issues.project_name"],
        parameters=[
            ToolParameter("limit", "number", "Max projects to return", default=10),
        ],
        examples=[
            "бэклог по проектам",
            "открытые задачи по проектам",
            "backlog by project",
            "open issues per project",
        ],
        keywords=["backlog", "бэклог", "открытые", "open", "не закрытые"]
    ),
    
    ToolDefinition(
        name="get_lead_time_by_project",
        description="Get average lead time (cycle time) in days by project",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_issues.avg_lead_time"],
        cube_dimensions=["fact_issues.project_name"],
        parameters=[
            ToolParameter("limit", "number", "Max projects to return", default=10),
        ],
        examples=[
            "lead time по проектам",
            "среднее время выполнения задач",
            "cycle time by project",
            "average time to resolve",
        ],
        keywords=["lead time", "cycle time", "время выполнения", "среднее время"]
    ),
    
    ToolDefinition(
        name="get_worklogs_by_author",
        description="Get total time spent (hours) grouped by author",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_worklogs.total_time_spent_hours"],
        cube_dimensions=["fact_worklogs.author_name"],
        parameters=[
            ToolParameter("limit", "number", "Max authors to return", default=10),
        ],
        examples=[
            "время по авторам",
            "топ по залогированному времени",
            "time spent by author",
            "who logged most hours",
            "worklogs by user",
        ],
        keywords=["время", "часов", "worklogs", "time spent", "топ авторов", "by author"]
    ),
    
    ToolDefinition(
        name="get_sprint_velocity",
        description="Get sprint velocity metrics (committed vs completed points)",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=[
            "fact_sprint_reports.avg_committed_points",
            "fact_sprint_reports.avg_completed_points",
            "fact_sprint_reports.avg_completion_rate"
        ],
        cube_dimensions=["fact_sprint_reports.project_name"],
        parameters=[
            ToolParameter("limit", "number", "Max projects to return", default=10),
        ],
        examples=[
            "velocity спринтов",
            "скорость команды",
            "committed vs completed",
            "sprint velocity",
            "team velocity",
        ],
        keywords=["velocity", "скорость", "спринт", "sprint", "committed", "completed"]
    ),
    
    ToolDefinition(
        name="get_reopen_rate",
        description="Get reopen rate - count of reopened issues by project",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_status_changes.reopen_count", "fact_status_changes.issues_completed"],
        cube_dimensions=["fact_status_changes.project_name"],
        parameters=[
            ToolParameter("limit", "number", "Max projects to return", default=10),
        ],
        examples=[
            "reopen rate",
            "сколько задач переоткрыто",
            "reopened issues",
            "reopen statistics",
        ],
        keywords=["reopen", "переоткрыто", "reopened", "вернули"]
    ),
    
    ToolDefinition(
        name="get_estimate_accuracy",
        description="Get estimate accuracy ratio by project",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_issues.avg_estimate_accuracy"],
        cube_dimensions=["fact_issues.project_name"],
        parameters=[
            ToolParameter("limit", "number", "Max projects to return", default=10),
        ],
        examples=[
            "точность оценок",
            "estimate accuracy",
            "оценка vs факт",
            "estimation accuracy",
        ],
        keywords=["accuracy", "точность", "оценка", "estimate"]
    ),
    
    ToolDefinition(
        name="get_issues_by_status",
        description="Get count of issues grouped by status",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_issues.created_count"],
        cube_dimensions=["fact_issues.status_name"],
        parameters=[
            ToolParameter("project_name", "string", "Filter by project name"),
            ToolParameter("limit", "number", "Max statuses to return", default=20),
        ],
        examples=[
            "задачи по статусам",
            "распределение по статусам",
            "issues by status",
            "status distribution",
        ],
        keywords=["статусам", "статус", "status", "distribution"]
    ),
    
    ToolDefinition(
        name="get_issues_by_priority",
        description="Get count of issues grouped by priority",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_issues.created_count"],
        cube_dimensions=["fact_issues.priority_name"],
        parameters=[
            ToolParameter("limit", "number", "Max priorities to return", default=10),
        ],
        examples=[
            "задачи по приоритетам",
            "issues by priority",
            "priority distribution",
        ],
        keywords=["приоритет", "priority"]
    ),
    
    ToolDefinition(
        name="get_issues_by_type",
        description="Get count of issues grouped by issue type",
        tool_type=ToolType.CUBE,
        endpoint="/load",
        cube_measures=["fact_issues.created_count"],
        cube_dimensions=["fact_issues.issue_type_name"],
        parameters=[
            ToolParameter("limit", "number", "Max types to return", default=10),
        ],
        examples=[
            "задачи по типам",
            "сколько багов",
            "issues by type",
            "bugs vs stories",
        ],
        keywords=["тип", "type", "баг", "bug", "story"]
    ),
]


# ============================================
# Function Registry Class
# ============================================

class FunctionRegistry:
    """Registry of all available tools"""
    
    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self._register_all()
    
    def _register_all(self):
        """Register all tools"""
        for tool in VULCAN_TOOLS + CUBE_TOOLS:
            self.tools[tool.name] = tool
    
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get tool by name"""
        return self.tools.get(name)
    
    def get_tools_by_type(self, tool_type: ToolType) -> List[ToolDefinition]:
        """Get all tools of a specific type"""
        return [t for t in self.tools.values() if t.tool_type == tool_type]
    
    def get_all_tools(self) -> List[ToolDefinition]:
        """Get all registered tools"""
        return list(self.tools.values())
    
    def find_matching_tools(self, query: str, max_results: int = 5) -> List[ToolDefinition]:
        """Find tools that match the query based on keywords and examples"""
        query_lower = query.lower()
        scored_tools = []
        
        for tool in self.tools.values():
            score = 0
            
            # Check keywords
            for kw in tool.keywords:
                if kw.lower() in query_lower:
                    score += 10
            
            # Check examples (partial match)
            for example in tool.examples:
                if any(word in query_lower for word in example.lower().split() if len(word) > 3):
                    score += 2
            
            # Check description
            for word in tool.description.lower().split():
                if len(word) > 4 and word in query_lower:
                    score += 1
            
            if score > 0:
                scored_tools.append((tool, score))
        
        # Sort by score descending
        scored_tools.sort(key=lambda x: x[1], reverse=True)
        
        return [t[0] for t in scored_tools[:max_results]]
    
    def get_tools_description_for_llm(self) -> str:
        """Generate tools description for LLM prompt"""
        lines = ["## Available Tools\n"]
        
        lines.append("### Operational Tools (DataAPI)")
        for tool in self.get_tools_by_type(ToolType.VULCAN):
            lines.append(f"\n**{tool.name}**: {tool.description}")
            if tool.parameters:
                params = ", ".join([f"{p.name}({p.type})" for p in tool.parameters])
                lines.append(f"  Parameters: {params}")
            lines.append(f"  Examples: {'; '.join(tool.examples[:2])}")
        
        lines.append("\n### Analytics Tools (Cube)")
        for tool in self.get_tools_by_type(ToolType.CUBE):
            lines.append(f"\n**{tool.name}**: {tool.description}")
            if tool.parameters:
                params = ", ".join([f"{p.name}({p.type})" for p in tool.parameters])
                lines.append(f"  Parameters: {params}")
            lines.append(f"  Examples: {'; '.join(tool.examples[:2])}")
        
        return "\n".join(lines)


# Singleton instance
_registry: Optional[FunctionRegistry] = None

def get_registry() -> FunctionRegistry:
    """Get singleton registry instance"""
    global _registry
    if _registry is None:
        _registry = FunctionRegistry()
    return _registry
