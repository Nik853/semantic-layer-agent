#!/bin/bash
# JIRA Router Agent - Demo Script
# Runs 7 demo scenarios via HTTP API

set -e

AGENT_URL="${AGENT_URL:-http://localhost:8000}"
OUTPUT_DIR="${OUTPUT_DIR:-./demo_output}"

mkdir -p "$OUTPUT_DIR"

echo "============================================"
echo "JIRA Router Agent - 7 Demo Scenarios"
echo "============================================"
echo "Agent URL: $AGENT_URL"
echo "Output: $OUTPUT_DIR"
echo ""

# Function to call agent
call_agent() {
    local scenario_num=$1
    local query=$2
    local description=$3
    
    echo "============================================"
    echo "Scenario $scenario_num: $description"
    echo "Query: $query"
    echo "============================================"
    
    response=$(curl -s -X POST "$AGENT_URL/api/query" \
        -H "Content-Type: application/json" \
        -d "{\"query\": \"$query\"}")
    
    echo "$response" | tee "$OUTPUT_DIR/scenario_${scenario_num}.json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'Intent: {data[\"intent\"]}')
print('Steps:')
for i, step in enumerate(data['steps'], 1):
    print(f'  {i}. {step[\"description\"]}')
    print(f'     Endpoint: {step[\"endpoint\"]}')
print()
print('Result:')
print(data['final_answer'][:500])
if data.get('error'):
    print(f'\\nError: {data[\"error\"]}')
"
    echo ""
}

# Wait for agent to be ready
echo "Checking agent health..."
for i in {1..10}; do
    if curl -s "$AGENT_URL/api/health" > /dev/null 2>&1; then
        echo "Agent is ready!"
        break
    fi
    echo "Waiting for agent... ($i/10)"
    sleep 2
done

# Run 7 demo scenarios
echo ""

call_agent 1 "Show issues for project AUTH" \
    "List issues for project AUTH (VulcanSQL)"

call_agent 2 "Show issue #1 with details" \
    "Get issue details (VulcanSQL)"

call_agent 3 "Search issues containing database" \
    "Search issues by text (VulcanSQL)"

call_agent 4 "How many issues resolved by project last month?" \
    "Throughput by project (Cube Analytics)"

call_agent 5 "Show WIP tasks by assignee" \
    "WIP analysis (Cube Analytics)"

call_agent 6 "Top authors by worklogs last 14 days" \
    "Worklogs analytics + user profiles (Mixed)"

call_agent 7 "Show sprint velocity: committed vs completed points" \
    "Sprint velocity (Cube Analytics)"

echo "============================================"
echo "Demo Complete!"
echo "============================================"
echo "Output files saved to: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
