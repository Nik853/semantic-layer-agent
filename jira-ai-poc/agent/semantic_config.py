"""
Semantic Configuration Loader
Loads glossary, examples, and semantic layer config dynamically
"""

import os
import yaml
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GlossaryTerm:
    """Single term from business glossary"""
    key: str
    aliases: List[str]
    semantic_type: str
    fields: List[str]
    filter_operator: str = "equals"
    group_field: Optional[str] = None
    measures: List[str] = field(default_factory=list)
    description: str = ""


@dataclass  
class QueryExample:
    """Few-shot example for query generation"""
    question: str
    intent: str
    query: Optional[Dict] = None
    endpoint: Optional[str] = None
    params: Optional[Dict] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class SemanticConfig:
    """Full semantic layer configuration"""
    glossary: Dict[str, GlossaryTerm]
    examples: List[QueryExample]
    cube_config: Dict[str, Any]
    vulcan_config: Dict[str, Any]
    intents_config: Dict[str, Any]
    query_config: Dict[str, Any]


class SemanticConfigLoader:
    """Load and manage semantic layer configuration"""
    
    def __init__(self, config_dir: str = None):
        if config_dir is None:
            # Read from environment variable or use default
            config_dir = os.getenv("SEMANTIC_CONFIG_PATH")
            
            if not config_dir:
                # Fallback to config/ directory relative to this file
                config_dir = os.path.join(os.path.dirname(__file__), "config")
        
        self.config_dir = Path(config_dir)
        self._config: Optional[SemanticConfig] = None
        self._alias_index: Dict[str, str] = {}  # alias -> term_key
        
        print(f"📂 Semantic config path: {self.config_dir}")
    
    def load(self) -> SemanticConfig:
        """Load all configuration files"""
        glossary = self._load_glossary()
        examples = self._load_examples()
        layer_config = self._load_layer_config()
        
        self._config = SemanticConfig(
            glossary=glossary,
            examples=examples,
            cube_config=layer_config.get("cube", {}),
            vulcan_config=layer_config.get("vulcan", {}),
            intents_config=layer_config.get("intents", {}),
            query_config=layer_config.get("query_generation", {})
        )
        
        # Build alias index for fast lookup
        self._build_alias_index()
        
        return self._config
    
    def _load_glossary(self) -> Dict[str, GlossaryTerm]:
        """Load business glossary"""
        glossary_path = self.config_dir / "glossary.yml"
        
        if not glossary_path.exists():
            return {}
        
        with open(glossary_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        
        glossary = {}
        for key, value in data.items():
            if isinstance(value, dict):
                glossary[key] = GlossaryTerm(
                    key=key,
                    aliases=value.get("aliases", []),
                    semantic_type=value.get("semantic_type", ""),
                    fields=value.get("fields", []),
                    filter_operator=value.get("filter_operator", "equals"),
                    group_field=value.get("group_field"),
                    measures=value.get("measures", []),
                    description=value.get("description", "")
                )
        
        return glossary
    
    def _load_examples(self) -> List[QueryExample]:
        """Load few-shot examples"""
        examples_path = self.config_dir / "examples.yml"
        
        if not examples_path.exists():
            return []
        
        with open(examples_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or []
        
        examples = []
        for item in data:
            if isinstance(item, dict):
                examples.append(QueryExample(
                    question=item.get("question", ""),
                    intent=item.get("intent", "analytics"),
                    query=item.get("query"),
                    endpoint=item.get("endpoint"),
                    params=item.get("params"),
                    tags=item.get("tags", [])
                ))
        
        return examples
    
    def _load_layer_config(self) -> Dict:
        """Load main semantic layer config"""
        config_path = self.config_dir / "semantic_layer.yml"
        
        if not config_path.exists():
            return {}
        
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        
        # Expand environment variables
        return self._expand_env_vars(data)
    
    def _expand_env_vars(self, obj: Any) -> Any:
        """Recursively expand ${VAR} in config values"""
        if isinstance(obj, str):
            # Replace ${VAR} with environment variable
            pattern = r'\$\{(\w+)\}'
            def replacer(match):
                var_name = match.group(1)
                return os.getenv(var_name, match.group(0))
            return re.sub(pattern, replacer, obj)
        elif isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(item) for item in obj]
        return obj
    
    def _build_alias_index(self):
        """Build index for fast alias lookup"""
        self._alias_index = {}
        for key, term in self._config.glossary.items():
            self._alias_index[key.lower()] = key
            for alias in term.aliases:
                self._alias_index[alias.lower()] = key
    
    @property
    def config(self) -> SemanticConfig:
        if self._config is None:
            self.load()
        return self._config
    
    def find_term(self, text: str) -> Optional[GlossaryTerm]:
        """Find glossary term by alias in text"""
        text_lower = text.lower()
        
        # Check each alias
        for alias, term_key in self._alias_index.items():
            if alias in text_lower:
                return self._config.glossary.get(term_key)
        
        return None
    
    def find_all_terms(self, text: str) -> List[GlossaryTerm]:
        """Find all glossary terms mentioned in text"""
        text_lower = text.lower()
        found = {}
        
        for alias, term_key in self._alias_index.items():
            if alias in text_lower and term_key not in found:
                term = self._config.glossary.get(term_key)
                if term:
                    found[term_key] = term
        
        return list(found.values())
    
    def get_relevant_examples(self, question: str, intent: str = None, limit: int = 3) -> List[QueryExample]:
        """Get most relevant few-shot examples for a question"""
        question_lower = question.lower()
        
        # Find terms in question
        terms = self.find_all_terms(question)
        term_keys = {t.key for t in terms}
        
        # Score examples by relevance
        scored = []
        for example in self._config.examples:
            if intent and example.intent != intent:
                continue
            
            score = 0
            
            # Score by tag overlap with found terms
            for tag in example.tags:
                if tag in term_keys:
                    score += 2
            
            # Score by word overlap
            example_words = set(example.question.lower().split())
            question_words = set(question_lower.split())
            overlap = len(example_words & question_words)
            score += overlap * 0.5
            
            if score > 0:
                scored.append((score, example))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        
        return [ex for _, ex in scored[:limit]]
    
    def get_filter_field(self, term: GlossaryTerm, available_fields: List[str]) -> Optional[str]:
        """Get the best matching field for filtering"""
        for pattern in term.fields:
            if pattern.startswith("*."):
                # Wildcard pattern - match any cube
                suffix = pattern[2:]
                for field in available_fields:
                    if field.endswith(suffix):
                        return field
            else:
                # Exact match
                if pattern in available_fields:
                    return pattern
        
        return term.group_field
    
    def get_measure_field(self, term: GlossaryTerm, available_measures: List[str]) -> Optional[str]:
        """Get the best matching measure for a term"""
        for pattern in term.measures:
            if pattern.startswith("*."):
                suffix = pattern[2:]
                for measure in available_measures:
                    if measure.endswith(suffix):
                        return measure
            else:
                if pattern in available_measures:
                    return pattern
        
        return None
