#!/bin/bash
# JIRA Data Agents PoC Demo Script
# Demonstrates 10 operational endpoints + 10 KPI scenarios + 3 chain scenarios

set -e

# Configuration
API_HOST="${API_HOST:-localhost}"
DATA_API_PORT="${DATA_API_PORT:-3001}"
CUBE_API_PORT="${CUBE_API_PORT:-4000}"
OUTPUT_DIR="${OUTPUT_DIR:-./demo_out}"

DATA_API="http://${API_HOST}:${DATA_API_PORT}"
CUBE_API="http://${API_HOST}:${CUBE_API_PORT}/cubejs-api/v1"

mkdir -p "$OUTPUT_DIR"

echo "============================================"
echo "JIRA Data Agents PoC Demo"
echo "============================================"
echo "Data API: $DATA_API"
echo "Cube API: $CUBE_API"
echo "Output: $OUTPUT_DIR"
echo ""

# ============================================
# PART 1: Operational Endpoints (10 scenarios)
# ============================================
echo "============================================"
echo "PART 1: Operational Endpoints (Data API)"
echo "============================================"

echo -e "\n1. GET /jira/issues (list with filters)"
curl -s "$DATA_API/jira/issues?limit=5&view=basic" | tee "$OUTPUT_DIR/01_issues_list.json" | python3 -m json.tool | head -20
echo ""

echo -e "\n2. GET /jira/issues/:id (single issue)"
curl -s "$DATA_API/jira/issues/1" | tee "$OUTPUT_DIR/02_issue_detail.json" | python3 -m json.tool | head -25
echo ""

echo -e "\n3. GET /jira/issues/:id/comments"
curl -s "$DATA_API/jira/issues/1/comments?limit=3" | tee "$OUTPUT_DIR/03_issue_comments.json" | python3 -m json.tool | head -20
echo ""

echo -e "\n4. GET /jira/issues/:id/links"
curl -s "$DATA_API/jira/issues/10/links" | tee "$OUTPUT_DIR/04_issue_links.json" | python3 -m json.tool | head -20
echo ""

echo -e "\n5. GET /jira/issues/search?q=database"
curl -s "$DATA_API/jira/issues/search?q=database&limit=5" | tee "$OUTPUT_DIR/05_issues_search.json" | python3 -m json.tool | head -20
echo ""

echo -e "\n6. GET /jira/projects (list projects)"
curl -s "$DATA_API/jira/projects?view=wide&limit=5" | tee "$OUTPUT_DIR/06_projects.json" | python3 -m json.tool | head -25
echo ""

echo -e "\n7. GET /jira/sprints (list sprints)"
curl -s "$DATA_API/jira/sprints?status=active&view=wide" | tee "$OUTPUT_DIR/07_sprints.json" | python3 -m json.tool | head -25
echo ""

echo -e "\n8. GET /jira/users (search users)"
curl -s "$DATA_API/jira/users?q=john&view=wide" | tee "$OUTPUT_DIR/08_users.json" | python3 -m json.tool | head -20
echo ""

echo -e "\n9. GET /jira/issues/:id/worklogs"
curl -s "$DATA_API/jira/issues/1/worklogs" | tee "$OUTPUT_DIR/09_worklogs.json" | python3 -m json.tool | head -20
echo ""

echo -e "\n10. GET /jira/issues/:id/custom-fields"
curl -s "$DATA_API/jira/issues/1/custom-fields" | tee "$OUTPUT_DIR/10_custom_fields.json" | python3 -m json.tool | head -15
echo ""

# ============================================
# PART 2: Analytics KPIs (10 scenarios via Cube)
# ============================================
echo ""
echo "============================================"
echo "PART 2: Analytics KPIs (Cube API)"
echo "============================================"

echo -e "\n1. KPI: Throughput by project (resolved issues)"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_issues.throughput"],"dimensions":["fact_issues.project_name"],"order":{"fact_issues.throughput":"desc"},"limit":5}}' \
  | tee "$OUTPUT_DIR/kpi_01_throughput.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

echo -e "\n2. KPI: Throughput by week"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_issues.throughput","fact_issues.created_count"],"timeDimensions":[{"dimension":"fact_issues.created_at","granularity":"week"}],"order":{"fact_issues.created_at":"desc"},"limit":5}}' \
  | tee "$OUTPUT_DIR/kpi_02_throughput_weekly.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

echo -e "\n3. KPI: Backlog growth (open issues)"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_issues.open_count","fact_issues.created_count"],"dimensions":["fact_issues.project_name"],"order":{"fact_issues.open_count":"desc"},"limit":5}}' \
  | tee "$OUTPUT_DIR/kpi_03_backlog.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

echo -e "\n4. KPI: WIP (In Progress issues)"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_issues.wip_count"],"dimensions":["fact_issues.project_name","fact_issues.assignee_name"],"order":{"fact_issues.wip_count":"desc"},"limit":10}}' \
  | tee "$OUTPUT_DIR/kpi_04_wip.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

echo -e "\n5. KPI: Lead Time (avg days to resolve)"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_issues.avg_lead_time","fact_issues.avg_open_age"],"dimensions":["fact_issues.project_name"],"order":{"fact_issues.avg_lead_time":"desc"},"limit":5}}' \
  | tee "$OUTPUT_DIR/kpi_05_lead_time.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

echo -e "\n6. KPI: Reopen rate (status changes)"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_status_changes.reopen_count","fact_status_changes.issues_completed"],"dimensions":["fact_status_changes.project_name"]}}' \
  | tee "$OUTPUT_DIR/kpi_06_reopen_rate.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

echo -e "\n7. KPI: Worklogs by author (time spent)"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_worklogs.total_time_spent_hours"],"dimensions":["fact_worklogs.author_name"],"order":{"fact_worklogs.total_time_spent_hours":"desc"},"limit":10}}' \
  | tee "$OUTPUT_DIR/kpi_07_worklogs.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

echo -e "\n8. KPI: Estimate accuracy"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_issues.avg_estimate_accuracy","fact_issues.total_time_spent_hours","fact_issues.total_original_estimate_hours"],"dimensions":["fact_issues.project_name"],"limit":5}}' \
  | tee "$OUTPUT_DIR/kpi_08_estimate_accuracy.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

echo -e "\n9. KPI: Sprint velocity (committed vs completed)"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_sprint_reports.avg_committed_points","fact_sprint_reports.avg_completed_points","fact_sprint_reports.avg_completion_rate"],"dimensions":["fact_sprint_reports.project_name"],"limit":5}}' \
  | tee "$OUTPUT_DIR/kpi_09_sprint_velocity.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

echo -e "\n10. KPI: Burndown data (sprint reports)"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"dimensions":["fact_sprint_reports.sprint_name","fact_sprint_reports.burndown_data"],"filters":[{"member":"fact_sprint_reports.sprint_status","operator":"equals","values":["closed"]}],"limit":3}}' \
  | tee "$OUTPUT_DIR/kpi_10_burndown.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

# ============================================
# PART 3: Chain Scenarios (AI Agent workflows)
# ============================================
echo ""
echo "============================================"
echo "PART 3: Chain Scenarios (Multi-step)"
echo "============================================"

echo -e "\nChain A: Find high-priority bugs in AUTH project -> Get throughput"
echo "Step 1: Find issues"
AUTH_ISSUES=$(curl -s "$DATA_API/jira/issues?project_id=1&status_category=todo&limit=5")
echo "$AUTH_ISSUES" | python3 -m json.tool | head -15
echo "Step 2: Get throughput for AUTH project"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_issues.throughput","fact_issues.created_count"],"timeDimensions":[{"dimension":"fact_issues.created_at","granularity":"week"}],"filters":[{"member":"fact_issues.project_name","operator":"equals","values":["User Authentication Service"]}],"limit":4}}' \
  | tee "$OUTPUT_DIR/chain_a.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

echo -e "\nChain B: Top users by time logged -> Get user profiles"
echo "Step 1: Get top users by worklogs"
TOP_USERS=$(curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_worklogs.total_time_spent_hours"],"dimensions":["fact_worklogs.author_name"],"order":{"fact_worklogs.total_time_spent_hours":"desc"},"limit":3}}')
echo "$TOP_USERS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo "Step 2: Get user details"
curl -s "$DATA_API/jira/users?q=Christopher&view=wide" | tee "$OUTPUT_DIR/chain_b.json" | python3 -m json.tool | head -15
echo ""

echo -e "\nChain C: Sprint issues -> Velocity metrics"
echo "Step 1: Get active sprint issues"
curl -s "$DATA_API/jira/issues?sprint_id=2&status_category=in_progress&limit=3" | python3 -m json.tool | head -15
echo "Step 2: Get sprint velocity"
curl -s "$CUBE_API/load" -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_sprint_reports.total_committed_points","fact_sprint_reports.total_completed_points"],"dimensions":["fact_sprint_reports.sprint_name","fact_sprint_reports.project_name"],"limit":5}}' \
  | tee "$OUTPUT_DIR/chain_c.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('data',[]), indent=2))"
echo ""

# ============================================
# Summary
# ============================================
echo ""
echo "============================================"
echo "Demo Complete!"
echo "============================================"
echo "Output files saved to: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
echo ""
echo "Services:"
echo "  - Data API: $DATA_API"
echo "  - Cube API: $CUBE_API"
echo "  - Cube Playground: http://${API_HOST}:${CUBE_API_PORT}"
