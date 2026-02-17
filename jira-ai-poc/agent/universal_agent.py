"""
Universal Semantic Agent
Config-driven agent that works with any Cube + VulcanSQL setup
"""

import os
import json
import httpx
import time
import re
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

# GigaChat support
try:
    from langchain_gigachat import GigaChat
    GIGACHAT_AVAILABLE = True
except ImportError:
    GIGACHAT_AVAILABLE = False
    print("⚠️ langchain-gigachat not installed. GigaChat will not be available.")

# Local modules
from semantic_config import SemanticConfigLoader, GlossaryTerm
from prompt_builder import PromptBuilder, IntentDetector

load_dotenv()

# ============================================
# Configuration
# ============================================

CUBE_BASE_URL = os.getenv("CUBE_BASE_URL", "http://localhost:4000/cubejs-api/v1")
VULCAN_BASE_URL = os.getenv("VULCAN_BASE_URL", "http://localhost:3001")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS", "")
GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat")


# ============================================
# LLM Provider Factory
# ============================================

class LLMProvider:
    """Factory for creating LLM instances"""
    
    PROVIDERS = ["openai", "gigachat"]
    
    @staticmethod
    def get_available_providers() -> List[str]:
        """Return list of available providers"""
        available = []
        if OPENAI_API_KEY:
            available.append("openai")
        if GIGACHAT_AVAILABLE and GIGACHAT_CREDENTIALS:
            available.append("gigachat")
        return available
    
    @staticmethod
    def create(provider: str = "openai"):
        """Create LLM instance for specified provider"""
        if provider == "openai":
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not configured")
            return ChatOpenAI(
                api_key=OPENAI_API_KEY,
                model=OPENAI_MODEL,
                temperature=0
            )
        elif provider == "gigachat":
            if not GIGACHAT_AVAILABLE:
                raise ValueError("langchain-gigachat not installed")
            if not GIGACHAT_CREDENTIALS:
                raise ValueError("GIGACHAT_CREDENTIALS not configured")
            return GigaChat(
                credentials=GIGACHAT_CREDENTIALS,
                model=GIGACHAT_MODEL,
                verify_ssl_certs=False,
                timeout=60
            )
        else:
            raise ValueError(f"Unknown provider: {provider}. Available: {LLMProvider.PROVIDERS}")
    
    @staticmethod
    def get_model_name(provider: str) -> str:
        """Get model name for provider"""
        if provider == "openai":
            return OPENAI_MODEL
        elif provider == "gigachat":
            return GIGACHAT_MODEL
        return "unknown"

# ============================================
# Data Classes
# ============================================

@dataclass
class LogEntry:
    """Single log entry for pipeline tracking"""
    timestamp: str
    step: str
    type: str
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
    member_type: str
    description: str = ""
    agg_type: str = ""


@dataclass
class ToolCall:
    """Represents a tool call"""
    tool_type: str
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
            
            for measure in cube.get("measures", []):
                if not measure.get("isVisible", True):
                    continue
                # Prefer shortTitle for cleaner display
                title = measure.get("shortTitle") or measure.get("title", measure["name"])
                self._members.append(CubeMember(
                    name=measure["name"],
                    title=title,
                    type=measure.get("type", "number"),
                    cube_name=cube_name,
                    member_type="measure",
                    description=measure.get("description", ""),
                    agg_type=measure.get("aggType", "")
                ))
            
            for dim in cube.get("dimensions", []):
                if not dim.get("isVisible", True):
                    continue
                # Prefer shortTitle for cleaner display
                title = dim.get("shortTitle") or dim.get("title", dim["name"])
                self._members.append(CubeMember(
                    name=dim["name"],
                    title=title,
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


# ============================================
# Vector Store
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
        """Build FAISS index from members with rich descriptions for better semantic search"""
        documents = []
        for m in self.members:
            # Build rich text for embedding - include description prominently
            parts = [m.title]
            if m.description:
                parts.append(m.description)
            parts.append(f"Куб: {m.cube_name}")
            parts.append(f"Тип: {m.member_type}, {m.type}")
            if m.agg_type:
                parts.append(f"Агрегация: {m.agg_type}")
            text = ". ".join(parts)
            
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

class CubeQueryGenerator:
    """Generate Cube queries using LLM with dynamic prompts"""
    
    def __init__(self, prompt_builder: PromptBuilder, provider: str = "openai"):
        self.prompt_builder = prompt_builder
        self.provider = provider
        self.llm = LLMProvider.create(provider)
        self.last_prompt: str = ""
        self.last_response: str = ""
    
    def set_provider(self, provider: str):
        """Switch LLM provider"""
        if provider != self.provider:
            self.provider = provider
            self.llm = LLMProvider.create(provider)
    
    def generate(self, question: str, relevant_members: List[Dict]) -> Dict:
        """Generate Cube query from question"""
        
        # Build dynamic prompt
        prompt_text = self.prompt_builder.build_prompt(question, relevant_members)
        self.last_prompt = prompt_text
        
        # Call LLM
        response = self.llm.invoke(prompt_text)
        self.last_response = response.content
        
        # Parse JSON from response with improved handling for GigaChat
        return self._parse_json_response(response.content)
    
    def _parse_json_response(self, content: str) -> Dict:
        """Parse JSON from LLM response with robust error handling"""
        original_content = content
        try:
            content = content.strip()
            
            # Replace typographic quotes with ASCII quotes (GigaChat uses Unicode quotes)
            # Handle both direct Unicode and UTF-8 encoded versions
            quote_replacements = [
                ('"', '"'), ('"', '"'),  # U+201C, U+201D (smart double quotes)
                (''', "'"), (''', "'"),  # U+2018, U+2019 (smart single quotes)
                ('«', '"'), ('»', '"'),  # Guillemets
                ('\u201c', '"'), ('\u201d', '"'),  # Explicit Unicode escapes
                ('\u2018', "'"), ('\u2019', "'"),
            ]
            for old, new in quote_replacements:
                content = content.replace(old, new)
            
            # Also handle if content was read as raw bytes (UTF-8 sequences)
            try:
                # Try to decode if content contains raw UTF-8 byte sequences
                if any(ord(c) > 127 for c in content):
                    # Re-encode and decode to normalize Unicode
                    content = content.encode('utf-8').decode('utf-8')
                    for old, new in quote_replacements:
                        content = content.replace(old, new)
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass
            
            # Remove markdown code blocks (handle both ``` and ```json)
            if "```" in content:
                # Find content between ``` markers
                parts = content.split("```")
                for part in parts:
                    part = part.strip()
                    # Skip empty parts
                    if not part:
                        continue
                    # Remove language identifier if present
                    if part.startswith("json"):
                        part = part[4:].strip()
                    elif part.startswith("JSON"):
                        part = part[4:].strip()
                    # Check if this looks like JSON
                    if part.startswith("{"):
                        content = part
                        break
            
            content = content.strip()
            
            # Remove control characters (except newlines and tabs)
            cleaned = ''.join(c if ord(c) >= 32 or c in '\n\r\t' else '' for c in content)
            
            # Try parsing cleaned content
            try:
                result = json.loads(cleaned)
                # Convert GigaChat's orderBy format to Cube's order format if needed
                return self._normalize_cube_query(result)
            except json.JSONDecodeError:
                pass
            
            # Try to extract JSON object using regex (handles nested objects)
            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    return self._normalize_cube_query(result)
                except json.JSONDecodeError:
                    pass
            
            # Last resort: try to fix common issues
            fixed = cleaned.replace('\n', ' ').replace('\r', ' ')
            fixed = re.sub(r',\s*}', '}', fixed)  # Remove trailing commas
            fixed = re.sub(r',\s*]', ']', fixed)  # Remove trailing commas in arrays
            
            result = json.loads(fixed)
            return self._normalize_cube_query(result)
            
        except json.JSONDecodeError as e:
            return {"error": f"Failed to parse LLM response: {str(e)}", "raw": original_content}
    
    def _normalize_cube_query(self, query: Dict) -> Dict:
        """Normalize query format to match Cube.js expected format"""
        # Convert GigaChat's orderBy format to Cube's order format
        if "orderBy" in query and "order" not in query:
            order_by = query.pop("orderBy")
            if isinstance(order_by, list) and len(order_by) > 0:
                # Convert from [{measure: "x", direction: "desc"}] to {"x": "desc"}
                query["order"] = {}
                for item in order_by:
                    if isinstance(item, dict):
                        member = item.get("measure") or item.get("dimension") or item.get("member")
                        direction = item.get("direction", "asc")
                        if member:
                            query["order"][member] = direction
            elif isinstance(order_by, dict):
                query["order"] = order_by
        
        return query


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
        
        for measure in query.get("measures", []):
            if measure not in self.valid_members:
                return False, f"Invalid measure: {measure}"
        
        for dim in query.get("dimensions", []):
            if dim not in self.valid_members:
                return False, f"Invalid dimension: {dim}"
        
        limit = query.get("limit", 100)
        if limit > 10000:
            query["limit"] = 10000
        
        if not query.get("measures"):
            return False, "Query must have at least one measure"
        
        return True, ""


# ============================================
# Universal Semantic Agent
# ============================================

class UniversalSemanticAgent:
    """
    Universal agent using config-driven semantic layer
    Supports multiple LLM providers (OpenAI, GigaChat)
    """
    
    def __init__(self, config_dir: str = None, llm_provider: str = "openai"):
        print("🔄 Loading semantic configuration...")
        self.config_loader = SemanticConfigLoader(config_dir)
        self.config_loader.load()
        
        print("🔄 Loading Cube metadata...")
        self.metadata_loader = CubeMetadataLoader()
        self.metadata_loader.load()
        
        print("🔄 Building vector index...")
        self.vector_store = CubeVectorStore(self.metadata_loader.members)
        
        print("🔄 Initializing components...")
        self.prompt_builder = PromptBuilder(self.config_loader)
        self.intent_detector = IntentDetector(self.config_loader)
        
        # Use specified LLM provider
        self.llm_provider = llm_provider
        available = LLMProvider.get_available_providers()
        if llm_provider not in available:
            print(f"⚠️ Provider {llm_provider} not available, falling back to {available[0] if available else 'none'}")
            llm_provider = available[0] if available else "openai"
        
        self.query_generator = CubeQueryGenerator(self.prompt_builder, provider=llm_provider)
        
        valid_members = [m.name for m in self.metadata_loader.members]
        self.validator = CubeQueryValidator(valid_members)
        
        self.client = httpx.Client(timeout=30.0)
        
        print("✅ Universal Semantic Agent ready!")
        print(f"   - LLM Provider: {llm_provider} ({LLMProvider.get_model_name(llm_provider)})")
        print(f"   - Available providers: {available}")
        print(f"   - Glossary terms: {len(self.config_loader.config.glossary)}")
        print(f"   - Examples: {len(self.config_loader.config.examples)}")
        print(f"   - Cube members: {len(self.metadata_loader.members)}")
    
    def set_llm_provider(self, provider: str):
        """Switch LLM provider at runtime"""
        available = LLMProvider.get_available_providers()
        if provider not in available:
            raise ValueError(f"Provider {provider} not available. Available: {available}")
        self.llm_provider = provider
        self.query_generator.set_provider(provider)
        print(f"🔄 Switched to {provider} ({LLMProvider.get_model_name(provider)})")
    
    def get_current_provider(self) -> Dict[str, Any]:
        """Get current LLM provider info"""
        return {
            "provider": self.llm_provider,
            "model": LLMProvider.get_model_name(self.llm_provider),
            "available_providers": LLMProvider.get_available_providers()
        }
    
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
        """Process natural language question
        
        All queries now go through Cube semantic layer.
        DataAPI (VulcanSQL) code is kept but not used for routing.
        """
        start_time = time.time()
        response = AgentResponse(query=question, intent="")
        
        self._log(response, "start", "info", f"Processing query: {question}")
        
        try:
            # All queries go through Cube analytics
            response.intent = "analytics"
            self._log(response, "intent", "info", 
                     "All queries routed to Cube semantic layer")
            
            # Find glossary terms
            terms = self.config_loader.find_all_terms(question)
            if terms:
                term_names = [t.key for t in terms]
                self._log(response, "glossary", "info", f"Found terms: {term_names}")
            
            # All queries go through Cube
            result = self._handle_analytics_query(question, response, terms)
            
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
    
    def _check_confidence(self, question: str, relevant: List[Dict], terms: List) -> Optional[str]:
        """
        Check if the model is confident enough to answer.
        Returns a clarifying question string if uncertain, or None if confident.
        
        Confidence is based on:
        1. FAISS similarity scores (lower = better in L2 distance)
        2. Whether any measures were found
        3. How many cubes are involved (ambiguity)
        """
        if not relevant:
            return ("Не удалось найти подходящие данные для вашего вопроса. "
                    "Уточните, пожалуйста:\n"
                    "- Вас интересуют задачи, проекты, спринты или пользователи?\n"
                    "- Какую метрику хотите получить (количество, время, story points)?")
        
        # Check FAISS scores - L2 distance, lower is better
        # Calibrated thresholds (paraphrase-multilingual-MiniLM-L12-v2):
        #   Good match: ~5-9, Decent: ~9-14, Weak: ~14-18, Unrelated: ~18+
        top_score = relevant[0]["score"]
        has_measures = any(m["member_type"] == "measure" for m in relevant[:5])
        has_dimensions = any(m["member_type"] == "dimension" for m in relevant[:5])
        
        # Count distinct cubes in top 5 results
        top_cubes = set(m["cube_name"] for m in relevant[:5])
        
        # Confidence checks
        # 1. Completely unrelated query (score > 18)
        if top_score > 18.0:
            available_cubes_info = self._get_available_cubes_summary()
            return (f"Я не уверен, какие данные вам нужны. Ваш вопрос слабо соотносится с имеющимися метриками.\n\n"
                    f"Доступные области данных:\n{available_cubes_info}\n\n"
                    f"Уточните, пожалуйста, что именно вас интересует.")
        
        # 2. No measures in top results AND weak match - can't build a valid query
        if not has_measures and top_score > 14.0:
            return ("Не удалось определить, какую метрику вы хотите получить.\n\n"
                    "Примеры вопросов:\n"
                    "• «Сколько задач по проектам?» — количество задач\n"
                    "• «Story points по исполнителям» — оценка сложности\n"
                    "• «Затраченное время по авторам» — часы из worklogs\n"
                    "• «Velocity по спринтам» — скорость команды\n"
                    "• «Среднее время выполнения» — lead time\n\n"
                    "Какую метрику вам нужно?")
        
        # 3. Ambiguous query - many cubes, no clear terms, mediocre scores (>12)
        if len(top_cubes) >= 4 and top_score > 12.0 and not terms:
            cube_options = []
            for cube_name in sorted(top_cubes):
                cube_measures = [m["title"] for m in relevant[:10] 
                               if m["cube_name"] == cube_name and m["member_type"] == "measure"]
                if cube_measures:
                    cube_options.append(f"• {cube_name}: {', '.join(cube_measures[:2])}")
            
            if cube_options:
                return (f"Ваш вопрос может относиться к разным областям данных:\n\n"
                        + "\n".join(cube_options) + "\n\n"
                        "Уточните, пожалуйста, какая область вас интересует.")
        
        return None  # Confident enough to proceed
    
    def _get_available_cubes_summary(self) -> str:
        """Get a brief summary of available cubes for clarifying messages"""
        summaries = [
            "• Задачи (issues) — количество, story points, lead time, просроченные",
            "• Worklogs — затраченное время по авторам и задачам",
            "• Спринты (sprints) — velocity, статус спринтов",
            "• Проекты (projects) — список, количество проектов",
            "• Комментарии (issue_comments) — активность обсуждений",
            "• История (issue_history) — изменения статусов, переоткрытия",
        ]
        return "\n".join(summaries)
    
    # Essential members that should always be available to LLM when querying issues
    ESSENTIAL_ISSUE_MEMBERS = {
        "issues.key", "issues.summary", "users_assignee.display_name",
        "issue_statuses.name", "issue_priorities.name", "projects.key",
        "issues.count", "issues.open_count", "issues.completed_count",
        "issues.distinct_projects_count", "issues.resolved_at"
    }
    
    def _enrich_with_essential_members(self, relevant: List[Dict]) -> List[Dict]:
        """
        Ensure essential issue-related dimensions/measures are always available
        when any issue-related member is in the FAISS results.
        """
        existing_names = {m["name"] for m in relevant}
        
        # Check if query involves issues
        has_issue_members = any(
            m["cube_name"] in ("issues", "projects", "users_assignee", "issue_statuses", "issue_priorities", "issue_types")
            for m in relevant[:5]
        )
        
        if not has_issue_members:
            return relevant
        
        # Add missing essential members from metadata
        members_to_add = self.ESSENTIAL_ISSUE_MEMBERS - existing_names
        if not members_to_add:
            return relevant
        
        for member in self.metadata_loader.members:
            if member.name in members_to_add:
                relevant.append({
                    "name": member.name,
                    "title": member.title,
                    "type": member.type,
                    "cube_name": member.cube_name,
                    "member_type": member.member_type,
                    "agg_type": member.agg_type or "",
                    "description": member.description or "",
                    "score": 99.0  # Low priority / artificial
                })
        
        return relevant
    
    def _handle_analytics_query(self, question: str, response: AgentResponse, 
                                 terms: List[GlossaryTerm]) -> AgentResponse:
        """Handle analytics query using Cube"""
        
        # Step 1: Semantic search
        search_start = time.time()
        relevant = self.vector_store.search(question, k=20)
        
        # Enrich with essential members so LLM always has key fields available
        relevant = self._enrich_with_essential_members(relevant)
        
        response.relevant_members = [m["name"] for m in relevant]
        search_ms = int((time.time() - search_start) * 1000)
        
        self._log(response, "semantic_search", "info", 
                 f"Found {len(relevant)} relevant members (top score: {relevant[0]['score']:.2f})" if relevant else "No relevant members found",
                 data={"members": response.relevant_members[:5], 
                       "top_score": round(relevant[0]["score"], 3) if relevant else None},
                 duration_ms=search_ms)
        
        # Step 2: Check confidence - ask clarifying question if uncertain
        clarification = self._check_confidence(question, relevant, terms)
        if clarification:
            response.intent = "clarification"
            response.final_answer = f"🤔 {clarification}"
            self._log(response, "confidence_check", "info", 
                     "Low confidence - asking clarifying question",
                     data={"top_score": round(relevant[0]["score"], 3) if relevant else None,
                           "terms_found": len(terms)})
            return response
        
        self._log(response, "confidence_check", "info", "Confidence OK, proceeding with query generation")
        
        # Step 3: Generate Cube query using LLM with dynamic prompt
        llm_start = time.time()
        cube_query = self.query_generator.generate(question, relevant)
        llm_ms = int((time.time() - llm_start) * 1000)
        
        response.generated_cube_query = cube_query
        response.llm_prompt = self.query_generator.last_prompt
        response.llm_response = self.query_generator.last_response
        
        self._log(response, "llm_generate", "llm", 
                 f"LLM generated Cube query",
                 data={"query": cube_query, "provider": self.llm_provider, "model": LLMProvider.get_model_name(self.llm_provider)},
                 duration_ms=llm_ms)
        
        # Step 4: Validate query
        is_valid, error = self.validator.validate(cube_query)
        if not is_valid:
            # If validation failed, try to give a helpful suggestion
            response.error = error
            response.intent = "clarification"
            response.final_answer = (
                f"🤔 Не удалось построить запрос: {error}\n\n"
                "Попробуйте переформулировать вопрос. Примеры:\n"
                "• «Сколько задач по проектам?»\n"
                "• «Топ исполнителей по закрытым задачам»\n"
                "• «Story points по проектам»\n"
                "• «Затраченное время по авторам»"
            )
            self._log(response, "validation", "error", f"Validation failed: {error}")
            return response
        
        self._log(response, "validation", "info", "Query validated successfully")
        
        # Step 5: Get SQL
        sql_start = time.time()
        sql_result = self._get_cube_sql(cube_query)
        sql_ms = int((time.time() - sql_start) * 1000)
        
        if sql_result and "sql" in sql_result:
            response.cube_sql = sql_result["sql"].get("sql", [""])[0] if isinstance(sql_result["sql"], dict) else str(sql_result["sql"])
            self._log(response, "cube_sql", "sql", "Generated SQL query",
                     data={"sql": response.cube_sql}, duration_ms=sql_ms)
        
        # Step 6: Execute query
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
                 data={"row_count": row_count},
                 duration_ms=exec_ms)
        
        # Step 7: If Cube returned an error, give a helpful message
        if "error" in result:
            response.intent = "clarification"
            response.final_answer = (
                f"🤔 Запрос выполнен, но Cube вернул ошибку.\n\n"
                "Попробуйте переформулировать вопрос или уточните:\n"
                "• Какой именно показатель вас интересует?\n"
                "• По какому измерению группировать (проект, исполнитель, статус)?"
            )
            self._log(response, "cube_error", "error", f"Cube error: {result.get('error')}")
            return response
        
        response.final_answer = self._format_cube_result(result)
        
        return response
    
    def _handle_list_query(self, question: str, response: AgentResponse,
                           terms: List[GlossaryTerm]) -> AgentResponse:
        """Handle list query using VulcanSQL"""
        
        # Extract filters from glossary terms
        params = {"view": "wide", "limit": "50"}
        
        # Check for project filter
        project_term = next((t for t in terms if t.semantic_type == "project"), None)
        if project_term:
            project_key = self._extract_value_for_term(question, project_term)
            if project_key:
                project_id = self._resolve_project_id(project_key)
                if project_id:
                    params["project_id"] = str(project_id)
                    self._log(response, "filter", "info", f"Filter by project: {project_key} -> {project_id}")
        
        endpoint = "/jira/issues"
        
        tool_call = ToolCall(
            tool_type="vulcan",
            endpoint=endpoint,
            params=params,
            description=f"List issues: {params}"
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
    
    def _handle_detail_query(self, question: str, response: AgentResponse) -> AgentResponse:
        """Handle detail query using VulcanSQL"""
        
        issue_match = re.search(r'([A-Z]+-\d+)', question)
        if not issue_match:
            response.error = "Could not extract issue ID"
            response.final_answer = "❌ Не удалось определить ID задачи"
            return response
        
        issue_id = issue_match.group(1)
        self._log(response, "extract_id", "info", f"Extracted issue ID: {issue_id}")
        
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
    
    def _extract_value_for_term(self, question: str, term: GlossaryTerm) -> Optional[str]:
        """Extract value for a glossary term from question"""
        question_upper = question.upper()
        
        # For projects, look for uppercase words
        if term.semantic_type == "project":
            # Get valid project keys
            projects_result = self._call_vulcan("/jira/projects", {"view": "basic"})
            valid_keys = set()
            if isinstance(projects_result, dict) and "data" in projects_result:
                for p in projects_result["data"]:
                    valid_keys.add(p.get("key", "").upper())
            
            # Find project key in question
            potential_keys = re.findall(r'\b([A-Z]{2,10})\b', question)
            for pk in potential_keys:
                if pk in valid_keys:
                    return pk
        
        return None
    
    def _resolve_project_id(self, project_key: str) -> Optional[int]:
        """Resolve project key to ID"""
        projects_result = self._call_vulcan("/jira/projects", {"view": "wide"})
        
        if isinstance(projects_result, dict) and "data" in projects_result:
            for p in projects_result["data"]:
                if p.get("key", "").upper() == project_key.upper():
                    return p.get("id")
        
        return None
    
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
    
    def _get_member_title_map(self) -> Dict[str, str]:
        """Build mapping from member name to Russian title"""
        title_map = {}
        for m in self.metadata_loader.members:
            title_map[m.name] = m.title
            # Also map the short key (after the dot)
            short = m.name.split(".")[-1] if "." in m.name else m.name
            # Don't overwrite if already set (prefer more specific)
            if short not in title_map:
                title_map[short] = m.title
        return title_map
    
    def _format_cube_result(self, result: Dict) -> str:
        """Format Cube result for display with Russian column names"""
        if "error" in result:
            return f"❌ Ошибка: {result['error']}"
        
        data = result.get("data", [])
        if not data:
            return "📊 Данные не найдены"
        
        # Build title map for Russian names
        title_map = self._get_member_title_map()
        
        lines = [f"📊 Результаты ({len(data)} строк):"]
        for i, row in enumerate(data[:15], 1):
            parts = []
            for k, v in row.items():
                # Get Russian title for the column
                russian_name = title_map.get(k)
                if not russian_name:
                    # Try short key
                    short_key = k.split(".")[-1]
                    russian_name = title_map.get(short_key, short_key)
                
                if isinstance(v, float):
                    v = round(v, 2)
                if v is None:
                    v = "—"
                parts.append(f"{russian_name}: {v}")
            lines.append(f"  {i}. {', '.join(parts)}")
        
        if len(data) > 15:
            lines.append(f"  ... и ещё {len(data) - 15} строк")
        
        return "\n".join(lines)
    
    def _format_issues_list(self, result) -> str:
        """Format list of issues"""
        if isinstance(result, dict) and "error" in result:
            return f"❌ Error: {result['error']}"
        
        data = result
        total_count = None
        if isinstance(result, dict):
            if "data" in result:
                data = result["data"]
                total_count = result.get("count")
        
        if not data:
            return "📋 No issues found"
        
        count_str = f"{total_count}" if total_count else f"{len(data)}"
        lines = [f"📋 Found {count_str} issues:"]
        
        for i, issue in enumerate(data[:20], 1):
            key = issue.get("key", "?")
            summary = issue.get("summary", "")[:55]
            status = issue.get("status_name") or issue.get("status", "")
            assignee = issue.get("assignee_name") or issue.get("assignee_display_name") or "Unassigned"
            
            lines.append(f"  {i}. [{key}] {summary}")
            lines.append(f"      Status: {status} | Assignee: {assignee}")
        
        if len(data) > 20:
            lines.append(f"  ... and {len(data) - 20} more issues")
        
        return "\n".join(lines)
    
    def _format_vulcan_result(self, result: Dict) -> str:
        """Format VulcanSQL result"""
        if "error" in result:
            return f"❌ Error: {result['error']}"
        
        if "key" in result and "data" not in result:
            lines = [f"📋 [{result.get('key')}] {result.get('summary', '')}"]
            lines.append(f"📊 Status: {result.get('status', 'N/A')}")
            lines.append(f"👤 Assignee: {result.get('assignee') or 'Unassigned'}")
            lines.append(f"📁 Project: {result.get('project_name', '')}")
            if result.get('description'):
                lines.append(f"📝 {result.get('description', '')[:200]}")
            return "\n".join(lines)
        
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
    agent = UniversalSemanticAgent()
    
    print("\n" + "=" * 60)
    print("Universal Semantic Agent")
    print("=" * 60)
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
            print(f"\n📝 Result:")
            print(response.final_answer)
            print(f"\n⏱️ Total time: {response.total_duration_ms}ms")
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    run_cli()
