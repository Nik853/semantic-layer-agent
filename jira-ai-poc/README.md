# JIRA Data Agents PoC

Демонстрационный проект Semantic Layer для JIRA-подобных данных с использованием **Cube** (analytics) и **Express API** (operational queries).

## Архитектура

```
┌─────────────────┐     ┌─────────────────┐
│   AI Agent      │     │   AI Agent      │
│  (Operational)  │     │   (Analytics)   │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│   Data API      │     │    Cube API     │
│   (Express)     │     │  (Semantic)     │
│   Port 3001     │     │   Port 4000     │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────┐
│           PostgreSQL (jira_clone)        │
│   ┌─────────────────────────────────┐   │
│   │   public.*                       │   │
│   │   (tables + fact_* views)        │   │
│   └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

## Компоненты

### 1. PostgreSQL Views (`sql/`)

| View | Описание | Rows |
|------|----------|------|
| `public.fact_issues` | Денормализованная таблица задач | ~500 |
| `public.fact_issue_status_changes` | История изменений статусов | ~280 |
| `public.fact_sprint_reports` | Отчеты по спринтам | ~22 |
| `public.fact_worklogs` | Логи времени | ~300 |

### 2. Cube Models (`cube/`)

| Cube | KPI Scenarios |
|------|--------------|
| `fact_issues` | Throughput, Lead Time, WIP, Backlog, Estimate Accuracy |
| `fact_status_changes` | Reopen Rate, Status Flow |
| `fact_sprint_reports` | Sprint Velocity, Burndown |
| `fact_worklogs` | Time Tracking by Author/Project |

### 3. Data API (`vulcansql/`)

10 operational endpoints с фильтрацией и параметром `view=basic|wide`.

## Endpoints

### Data API (Port 3001)

| # | Endpoint | Описание |
|---|----------|----------|
| 1 | `GET /jira/issues` | Список задач с фильтрами |
| 2 | `GET /jira/issues/:id` | Детали задачи |
| 3 | `GET /jira/issues/:id/comments` | Комментарии |
| 4 | `GET /jira/issues/:id/links` | Связи задачи |
| 5 | `GET /jira/issues/search?q=` | Поиск по тексту |
| 6 | `GET /jira/projects` | Список проектов |
| 7 | `GET /jira/sprints` | Список спринтов |
| 8 | `GET /jira/users` | Список пользователей |
| 9 | `GET /jira/issues/:id/worklogs` | Логи времени |
| 10 | `GET /jira/issues/:id/custom-fields` | Кастомные поля |

### Cube API (Port 4000)

| # | KPI | Query |
|---|-----|-------|
| 1 | Throughput by week/project | `fact_issues.throughput` |
| 2 | Throughput weekly trend | `timeDimensions: created_at` |
| 3 | Backlog growth | `fact_issues.open_count` |
| 4 | WIP by assignee | `fact_issues.wip_count` |
| 5 | Lead Time | `fact_issues.avg_lead_time` |
| 6 | Reopen Rate | `fact_status_changes.reopen_count` |
| 7 | Worklogs by author | `fact_worklogs.total_time_spent_hours` |
| 8 | Estimate Accuracy | `fact_issues.avg_estimate_accuracy` |
| 9 | Sprint Velocity | `fact_sprint_reports.avg_velocity` |
| 10 | Burndown | `fact_sprint_reports.burndown_data` |

## Быстрый старт

### Запуск демо

```bash
cd jira-ai-poc
chmod +x demo.sh
./demo.sh
```

### Примеры curl

```bash
# Operational: список задач
curl "http://your-server-ip:3001/jira/issues?project_id=1&limit=10"

# Operational: поиск
curl "http://your-server-ip:3001/jira/issues/search?q=database"

# Analytics: throughput по проектам
curl -s 'http://your-server-ip:4000/cubejs-api/v1/load' \
  -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_issues.throughput"],"dimensions":["fact_issues.project_name"]}}'

# Analytics: время по авторам
curl -s 'http://your-server-ip:4000/cubejs-api/v1/load' \
  -H 'Content-Type: application/json' \
  -d '{"query":{"measures":["fact_worklogs.total_time_spent_hours"],"dimensions":["fact_worklogs.author_name"],"order":{"fact_worklogs.total_time_spent_hours":"desc"}}}'
```

## Chain Scenarios

### Chain A: Issues → Throughput
1. `GET /jira/issues?project_id=1` → получить задачи проекта
2. Cube: throughput по этому проекту за 4 недели

### Chain B: Top Users → Profiles
1. Cube: top users по `total_time_spent_hours`
2. `GET /jira/users?q={name}` → профили пользователей

### Chain C: Sprint Issues → Velocity
1. `GET /jira/issues?sprint_id=2&status_category=in_progress`
2. Cube: velocity committed vs completed

## Структура проекта

```
jira-ai-poc/
├── README.md
├── demo.sh                    # Demo script
├── demo_out/                  # Output JSON files
├── sql/
│   ├── 01_seed_sprint_reports.sql
│   └── 02_analytics_views.sql
├── cube/
│   ├── fact_issues.yml
│   ├── fact_status_changes.yml
│   ├── fact_sprint_reports.yml
│   └── fact_worklogs.yml
└── vulcansql/
    ├── jira-api.js
    └── package.json
```

## Сервисы на сервере

| Service | Port | URL |
|---------|------|-----|
| Data API | 3001 | http://your-server-ip:3001 |
| Cube API | 4000 | http://your-server-ip:4000/cubejs-api/v1 |
| Cube Playground | 4000 | http://your-server-ip:4000 |
| PostgreSQL | 5432 | your-server-ip:5432 |

## Подключение к БД

```
Host: your-server-ip
Port: 5432
Database: jira_clone
User: jira_user
Password: your-password
```
