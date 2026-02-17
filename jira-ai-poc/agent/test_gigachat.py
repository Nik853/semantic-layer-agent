"""
Test script for GigaChat integration with Cube query generation
Validates that GigaChat correctly generates Cube queries from natural language
"""

import os
import sys
import json
import time
from typing import Dict, List, Tuple
from dotenv import load_dotenv

load_dotenv()

# Test questions with expected query structure
TEST_CASES = [
    {
        "question": "Сколько задач по проектам?",
        "expected_measures": ["issues_overview.count"],
        "expected_dimensions": ["issues_overview.projects_key"],
        "description": "Basic count by project"
    },
    {
        "question": "Топ исполнителей по количеству закрытых задач",
        "expected_measures": ["issues_overview.completed_count"],
        "expected_dimensions": ["issues_overview.users_assignee_display_name"],
        "expected_order": True,
        "description": "Top performers by completed issues"
    },
    {
        "question": "Сколько часов затрачено по авторам?",
        "expected_measures_partial": ["total_hours", "hours"],
        "expected_dimensions_partial": ["display_name", "users"],
        "description": "Time tracking by author"
    },
    {
        "question": "Сколько открытых задач в каждом проекте?",
        "expected_measures_partial": ["open_count", "count"],
        "expected_dimensions_partial": ["projects_key", "project"],
        "description": "Open issues by project"
    },
    {
        "question": "Средние story points по проектам",
        "expected_measures_partial": ["avg_story_points", "story_points"],
        "expected_dimensions_partial": ["projects_key", "project"],
        "description": "Average story points by project"
    },
]


def check_query_structure(generated_query: Dict, test_case: Dict) -> Tuple[bool, List[str]]:
    """Validate generated query against expected structure"""
    errors = []
    
    if "error" in generated_query:
        errors.append(f"Query has error: {generated_query['error']}")
        return False, errors
    
    # Check measures
    measures = generated_query.get("measures", [])
    if not measures:
        errors.append("No measures in query")
    
    # Check exact measures if specified
    if "expected_measures" in test_case:
        for expected in test_case["expected_measures"]:
            if expected not in measures:
                errors.append(f"Missing measure: {expected}")
    
    # Check partial measures if specified
    if "expected_measures_partial" in test_case:
        found = False
        for expected in test_case["expected_measures_partial"]:
            if any(expected.lower() in m.lower() for m in measures):
                found = True
                break
        if not found:
            errors.append(f"Expected one of measures containing: {test_case['expected_measures_partial']}")
    
    # Check dimensions
    dimensions = generated_query.get("dimensions", [])
    
    # Check exact dimensions if specified
    if "expected_dimensions" in test_case:
        for expected in test_case["expected_dimensions"]:
            if expected not in dimensions:
                errors.append(f"Missing dimension: {expected}")
    
    # Check partial dimensions if specified
    if "expected_dimensions_partial" in test_case:
        found = False
        for expected in test_case["expected_dimensions_partial"]:
            if any(expected.lower() in d.lower() for d in dimensions):
                found = True
                break
        if not found:
            errors.append(f"Expected one of dimensions containing: {test_case['expected_dimensions_partial']}")
    
    # Check order if specified
    if test_case.get("expected_order") and not generated_query.get("order"):
        errors.append("Expected 'order' in query but not found")
    
    return len(errors) == 0, errors


def run_tests(provider: str = "gigachat"):
    """Run all test cases with specified provider"""
    
    print(f"\n{'='*60}")
    print(f"Testing Cube Query Generation with {provider.upper()}")
    print(f"{'='*60}\n")
    
    # Import after setting up environment
    from universal_agent import UniversalSemanticAgent, LLMProvider
    
    # Check if provider is available
    available = LLMProvider.get_available_providers()
    print(f"Available providers: {available}")
    
    if provider not in available:
        print(f"\n❌ Provider '{provider}' is not available!")
        print(f"   Please check your .env configuration")
        return False
    
    # Initialize agent with specified provider
    print(f"\n🔄 Initializing agent with {provider}...")
    agent = UniversalSemanticAgent(llm_provider=provider)
    
    print(f"\n✅ Agent initialized")
    print(f"   Provider: {agent.get_current_provider()}")
    print(f"\n{'='*60}")
    print(f"Running {len(TEST_CASES)} test cases...")
    print(f"{'='*60}\n")
    
    passed = 0
    failed = 0
    results = []
    
    for i, test_case in enumerate(TEST_CASES, 1):
        question = test_case["question"]
        description = test_case["description"]
        
        print(f"\n📋 Test {i}: {description}")
        print(f"   Question: {question}")
        
        start_time = time.time()
        
        try:
            response = agent.process(question)
            duration = (time.time() - start_time) * 1000
            
            generated_query = response.generated_cube_query
            
            if generated_query:
                is_valid, errors = check_query_structure(generated_query, test_case)
                
                print(f"   Generated query: {json.dumps(generated_query, ensure_ascii=False)[:200]}...")
                print(f"   Duration: {duration:.0f}ms")
                
                if is_valid:
                    print(f"   ✅ PASSED")
                    passed += 1
                else:
                    print(f"   ❌ FAILED")
                    for error in errors:
                        print(f"      - {error}")
                    failed += 1
                
                results.append({
                    "test": description,
                    "question": question,
                    "passed": is_valid,
                    "errors": errors,
                    "query": generated_query,
                    "duration_ms": duration
                })
            else:
                print(f"   ❌ FAILED - No query generated")
                print(f"   Response: {response.final_answer}")
                failed += 1
                results.append({
                    "test": description,
                    "question": question,
                    "passed": False,
                    "errors": ["No query generated"],
                    "query": None,
                    "duration_ms": duration
                })
                
        except Exception as e:
            print(f"   ❌ ERROR: {str(e)}")
            failed += 1
            results.append({
                "test": description,
                "question": question,
                "passed": False,
                "errors": [str(e)],
                "query": None,
                "duration_ms": 0
            })
    
    # Summary
    print(f"\n{'='*60}")
    print(f"TEST SUMMARY")
    print(f"{'='*60}")
    print(f"Provider: {provider}")
    print(f"Total:    {len(TEST_CASES)}")
    print(f"Passed:   {passed} ✅")
    print(f"Failed:   {failed} ❌")
    print(f"Success:  {(passed/len(TEST_CASES))*100:.1f}%")
    print(f"{'='*60}\n")
    
    # Save results
    results_file = f"test_results_{provider}_{int(time.time())}.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump({
            "provider": provider,
            "total": len(TEST_CASES),
            "passed": passed,
            "failed": failed,
            "results": results
        }, f, ensure_ascii=False, indent=2)
    print(f"Results saved to: {results_file}")
    
    return failed == 0


def compare_providers():
    """Compare OpenAI and GigaChat on the same questions"""
    
    print("\n" + "="*70)
    print("COMPARING OPENAI vs GIGACHAT")
    print("="*70 + "\n")
    
    from universal_agent import UniversalSemanticAgent, LLMProvider
    
    available = LLMProvider.get_available_providers()
    
    if "openai" not in available or "gigachat" not in available:
        print("❌ Both providers must be available for comparison")
        print(f"   Available: {available}")
        return
    
    # Initialize agent
    agent = UniversalSemanticAgent(llm_provider="openai")
    
    questions = [
        "Сколько задач по проектам?",
        "Топ исполнителей по закрытым задачам",
        "Средние story points по проектам",
    ]
    
    for question in questions:
        print(f"\n{'='*60}")
        print(f"Question: {question}")
        print(f"{'='*60}")
        
        for provider in ["openai", "gigachat"]:
            agent.set_llm_provider(provider)
            
            start = time.time()
            response = agent.process(question)
            duration = (time.time() - start) * 1000
            
            print(f"\n{provider.upper()} ({duration:.0f}ms):")
            if response.generated_cube_query:
                print(f"  Query: {json.dumps(response.generated_cube_query, ensure_ascii=False)}")
            else:
                print(f"  Error: {response.error}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test GigaChat Cube query generation")
    parser.add_argument("--provider", "-p", default="gigachat", 
                       choices=["openai", "gigachat"],
                       help="LLM provider to test")
    parser.add_argument("--compare", "-c", action="store_true",
                       help="Compare both providers")
    parser.add_argument("--all", "-a", action="store_true",
                       help="Test all available providers")
    
    args = parser.parse_args()
    
    if args.compare:
        compare_providers()
    elif args.all:
        from universal_agent import LLMProvider
        available = LLMProvider.get_available_providers()
        for provider in available:
            run_tests(provider)
    else:
        success = run_tests(args.provider)
        sys.exit(0 if success else 1)
