"""
Dynamic Prompt Builder
Builds LLM prompts from semantic configuration and Cube metadata
"""

import json
from typing import List, Dict, Optional, Any
from semantic_config import SemanticConfigLoader, GlossaryTerm, QueryExample


class PromptBuilder:
    """
    Dynamically builds prompts for LLM query generation
    using glossary terms and few-shot examples
    """
    
    SYSTEM_TEMPLATE = """Ты генератор запросов к Cube.js. Преобразуй вопрос на естественном языке в валидный JSON-запрос для Cube REST API.

## Доступные меры (measures):
{measures}

## Доступные измерения (dimensions):
{dimensions}

## Бизнес-термины (используй для фильтров):
{business_terms}

## Формат запроса:
{{
  "measures": ["cube.measure_name"],
  "dimensions": ["cube.dimension_name"],
  "filters": [
    {{"member": "cube.field", "operator": "equals|contains|gt|lt|set|notSet", "values": ["value"]}}
  ],
  "order": {{"cube.measure": "desc"}},
  "limit": 100
}}

### Операторы фильтров:
- "equals" — точное совпадение (проект, статус, приоритет)
- "contains" — частичное совпадение (имя человека)
- "gt", "lt", "gte", "lte" — сравнение чисел/дат
- "set" — поле НЕ пустое (IS NOT NULL). НЕ нужен "values"!
- "notSet" — поле пустое (IS NULL). НЕ нужен "values"!

## Примеры:
{examples}

## ВАЖНЫЕ ПРАВИЛА:
1. Используй ТОЧНЫЕ имена полей из списка мер и измерений выше
2. Для фильтрации по имени человека используй оператор "contains"
3. Для фильтрации по точным значениям (проект, статус, приоритет) используй "equals"
4. Всегда включай хотя бы одну меру (measure)
5. Верни ТОЛЬКО валидный JSON, без пояснений

### Правила выбора dimensions:
6. Если пользователь просит "покажи/список/выведи задачи" — включай детальные измерения: issues.key, issues.summary, users_assignee.display_name, issue_statuses.name, issue_priorities.name
7. Если пользователь просит "подробности/детали проекта" — включай максимум измерений этой сущности
8. Если пользователь просит "сколько/количество" — используй только меру count и группировочное измерение
9. ВСЕГДА включай измерения по которым фильтруешь в dimensions, чтобы они были видны в результате. Например, если фильтруешь по users_assignee.display_name, добавь его в dimensions
10. Если пользователь спрашивает "сколько проектов с условием" (по исполнителю, статусу и т.д.) — используй measures: ["issues.distinct_projects_count"] с нужными фильтрами. Это посчитает уникальные проекты из таблицы задач

### Правила выбора measures:
11. "сколько задач" / "всего задач" → issues.count (ОБЩЕЕ количество, включая закрытые)
12. "открытые задачи" / "нерешённые" → issues.open_count (ТОЛЬКО нерешённые)
13. "закрытые/завершённые задачи" (простой подсчёт) → issues.completed_count
14. "просроченные задачи" → issues.overdue_count
15. НЕ путай issues.count (ВСЕ задачи) и issues.open_count (только открытые)! "Сколько всего задач" = issues.count

### Фильтрация по статусу закрытости задач:
16. Для ФИЛЬТРАЦИИ "закрытые/завершённые" в комбинации с другими условиями — используй фильтр по dimension: {{"member": "issues.resolved_at", "operator": "set"}} (resolved_at IS NOT NULL)
17. Для ФИЛЬТРАЦИИ "открытые/нерешённые" в комбинации с другими условиями — используй: {{"member": "issues.resolved_at", "operator": "notSet"}} (resolved_at IS NULL)
18. ВАЖНО: issues.completed_count и issues.open_count — это МЕРЫ для подсчёта, НЕ используй их в фильтрах! Для фильтрации используй issues.resolved_at с операторами set/notSet

### Стандартные dimensions для списка задач:
19. При запросе "покажи/список задач" ВСЕГДА включай: issues.key, issues.summary, users_assignee.display_name, issue_statuses.name, issue_priorities.name

## Вопрос:
{question}

## JSON Query:"""

    def __init__(self, config_loader: SemanticConfigLoader):
        self.config_loader = config_loader
    
    def build_prompt(
        self,
        question: str,
        relevant_members: List[Dict],
        few_shot_count: int = 5
    ) -> str:
        """Build complete prompt for LLM"""
        
        # Format measures and dimensions
        measures_str = self._format_members(relevant_members, "measure")
        dimensions_str = self._format_members(relevant_members, "dimension")
        
        # Get relevant business terms
        terms = self.config_loader.find_all_terms(question)
        business_terms_str = self._format_business_terms(terms, relevant_members)
        
        # Get relevant examples
        examples = self.config_loader.get_relevant_examples(
            question, intent="analytics", limit=few_shot_count
        )
        examples_str = self._format_examples(examples)
        
        # Build final prompt
        return self.SYSTEM_TEMPLATE.format(
            measures=measures_str,
            dimensions=dimensions_str,
            business_terms=business_terms_str,
            examples=examples_str,
            question=question
        )
    
    def _format_members(self, members: List[Dict], member_type: str) -> str:
        """Format measures or dimensions for prompt with descriptions"""
        lines = []
        for m in members:
            if m.get("member_type") == member_type:
                name = m["name"]
                title = m.get("title", "")
                agg = m.get("agg_type", "")
                desc = m.get("description", "")
                
                # Build line with description for better LLM understanding
                if member_type == "measure" and agg:
                    line = f"- {name}: {title} ({agg})"
                else:
                    line = f"- {name}: {title}"
                
                # Add short description if available
                if desc:
                    # Truncate description to keep prompt manageable
                    short_desc = desc.strip().replace('\n', ' ')[:120]
                    line += f" — {short_desc}"
                
                lines.append(line)
        
        return "\n".join(lines) if lines else f"Нет доступных {member_type}s"
    
    def _format_business_terms(
        self, 
        terms: List[GlossaryTerm], 
        available_members: List[Dict]
    ) -> str:
        """Format business terms with mapped fields"""
        if not terms:
            return "No specific terms detected"
        
        available_fields = [m["name"] for m in available_members]
        lines = []
        
        for term in terms:
            # Find best matching field
            field = self.config_loader.get_filter_field(term, available_fields)
            
            if field:
                operator = term.filter_operator
                lines.append(
                    f"- {term.key} ({', '.join(term.aliases[:3])}): "
                    f"filter by \"{field}\" with operator \"{operator}\""
                )
        
        return "\n".join(lines) if lines else "No specific terms detected"
    
    def _format_examples(self, examples: List[QueryExample]) -> str:
        """Format few-shot examples"""
        if not examples:
            return "No examples available"
        
        lines = []
        for i, ex in enumerate(examples, 1):
            if ex.query:
                query_str = json.dumps(ex.query, ensure_ascii=False)
                lines.append(f"Q{i}: {ex.question}")
                lines.append(f"A{i}: {query_str}")
                lines.append("")
        
        return "\n".join(lines) if lines else "No examples available"
    
    def extract_filter_hints(self, question: str, available_members: List[Dict]) -> List[Dict]:
        """
        Extract filter hints from question based on glossary
        Returns list of suggested filters
        """
        terms = self.config_loader.find_all_terms(question)
        available_fields = [m["name"] for m in available_members]
        
        hints = []
        for term in terms:
            field = self.config_loader.get_filter_field(term, available_fields)
            if field and term.semantic_type == "person":
                # Try to extract the person's name from question
                name = self._extract_name_after_term(question, term)
                if name:
                    hints.append({
                        "member": field,
                        "operator": term.filter_operator,
                        "value_hint": name,
                        "term": term.key
                    })
        
        return hints
    
    def _extract_name_after_term(self, question: str, term: GlossaryTerm) -> Optional[str]:
        """Extract value after a term mention"""
        import re
        question_lower = question.lower()
        
        for alias in term.aliases:
            alias_lower = alias.lower()
            if alias_lower in question_lower:
                # Find position after the alias
                idx = question_lower.find(alias_lower)
                after = question[idx + len(alias):].strip()
                
                # Extract first word/name (could be capitalized name)
                match = re.match(r'[\s:]*([A-ZА-Яa-zа-я][a-zа-я]*(?:\s+[A-ZА-Яa-zа-я][a-zа-я]*)?)', after)
                if match:
                    return match.group(1).strip()
        
        return None


class IntentDetector:
    """
    Detect query intent using configuration
    """
    
    def __init__(self, config_loader: SemanticConfigLoader):
        self.config_loader = config_loader
    
    def detect(self, question: str) -> str:
        """Detect intent from question"""
        import re
        question_lower = question.lower()
        config = self.config_loader.config.intents_config
        
        # Get intents sorted by priority
        intents = []
        for intent_name, intent_config in config.items():
            priority = intent_config.get("priority", 99)
            intents.append((priority, intent_name, intent_config))
        
        intents.sort(key=lambda x: x[0])
        
        # Check each intent
        for priority, intent_name, intent_config in intents:
            # Check keywords
            keywords = intent_config.get("keywords", [])
            for kw in keywords:
                if kw.lower() in question_lower:
                    return intent_name
            
            # Check patterns
            patterns = intent_config.get("patterns", [])
            for pattern in patterns:
                if re.search(pattern, question_lower, re.IGNORECASE):
                    return intent_name
        
        # Default to analytics
        return "analytics"
    
    def get_intent_description(self, intent: str) -> str:
        """Get human-readable intent description"""
        config = self.config_loader.config.intents_config
        intent_config = config.get(intent, {})
        return intent_config.get("description", intent)
