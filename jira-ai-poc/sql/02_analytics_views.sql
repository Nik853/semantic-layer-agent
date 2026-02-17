-- Analytics Views for Cube Semantic Layer
-- Views created in public schema (no separate analytics schema)

-- ============================================
-- VIEW 1: fact_issues
-- Денормализованная таблица задач со всеми связями
-- ============================================

DROP VIEW IF EXISTS public.fact_issues CASCADE;

CREATE VIEW public.fact_issues AS
SELECT 
    -- Issue identifiers
    i.id AS issue_id,
    i.key AS issue_key,
    i.summary,
    i.description,
    
    -- Project info
    i.project_id,
    p.key AS project_key,
    p.name AS project_name,
    
    -- Type info
    i.issue_type_id,
    it.name AS issue_type_name,
    it.is_subtask,
    
    -- Status info
    i.status_id,
    ist.name AS status_name,
    ist.category AS status_category,
    
    -- Priority info
    i.priority_id,
    ip.name AS priority_name,
    ip.priority_order,
    
    -- Resolution info
    i.resolution_id,
    ir.name AS resolution_name,
    
    -- Sprint info
    i.sprint_id,
    s.name AS sprint_name,
    s.status AS sprint_status,
    
    -- People
    i.reporter_id,
    reporter.display_name AS reporter_name,
    reporter.email AS reporter_email,
    
    i.assignee_id,
    assignee.display_name AS assignee_name,
    assignee.email AS assignee_email,
    
    -- Estimates & Time
    i.story_points,
    i.original_estimate,
    i.remaining_estimate,
    i.time_spent,
    
    -- Calculate estimate accuracy (ratio)
    CASE 
        WHEN i.original_estimate > 0 AND i.time_spent > 0 
        THEN ROUND((i.time_spent::numeric / i.original_estimate::numeric), 2)
        ELSE NULL 
    END AS estimate_accuracy_ratio,
    
    -- Dates
    i.due_date,
    i.created_at,
    i.updated_at,
    i.resolved_at,
    
    -- Derived date fields for analytics
    DATE_TRUNC('week', i.created_at) AS created_week,
    DATE_TRUNC('month', i.created_at) AS created_month,
    DATE_TRUNC('week', i.resolved_at) AS resolved_week,
    DATE_TRUNC('month', i.resolved_at) AS resolved_month,
    
    -- Cycle time (days from created to resolved)
    CASE 
        WHEN i.resolved_at IS NOT NULL 
        THEN EXTRACT(EPOCH FROM (i.resolved_at - i.created_at)) / 86400.0
        ELSE NULL 
    END AS cycle_time_days,
    
    -- Age of open issues (days)
    CASE 
        WHEN i.resolved_at IS NULL 
        THEN EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - i.created_at)) / 86400.0
        ELSE NULL 
    END AS open_age_days,
    
    -- Flags
    i.is_flagged,
    i.resolved_at IS NOT NULL AS is_resolved,
    i.due_date < CURRENT_DATE AND i.resolved_at IS NULL AS is_overdue

FROM issues i
LEFT JOIN projects p ON i.project_id = p.id
LEFT JOIN issue_types it ON i.issue_type_id = it.id
LEFT JOIN issue_statuses ist ON i.status_id = ist.id
LEFT JOIN issue_priorities ip ON i.priority_id = ip.id
LEFT JOIN issue_resolutions ir ON i.resolution_id = ir.id
LEFT JOIN sprints s ON i.sprint_id = s.id
LEFT JOIN users reporter ON i.reporter_id = reporter.id
LEFT JOIN users assignee ON i.assignee_id = assignee.id;

-- ============================================
-- VIEW 2: fact_issue_status_changes
-- История изменений статусов для расчета cycle time, lead time, reopen rate
-- ============================================

DROP VIEW IF EXISTS public.fact_issue_status_changes CASCADE;

CREATE VIEW public.fact_issue_status_changes AS
SELECT 
    h.id AS change_id,
    h.issue_id,
    i.key AS issue_key,
    i.project_id,
    p.key AS project_key,
    p.name AS project_name,
    
    h.user_id AS changed_by_id,
    u.display_name AS changed_by_name,
    
    -- Status transition
    h.old_value AS old_status_id,
    old_status.name AS old_status_name,
    old_status.category AS old_status_category,
    
    h.new_value AS new_status_id,
    new_status.name AS new_status_name,
    new_status.category AS new_status_category,
    
    -- Transition flags
    old_status.category = 'done' AND new_status.category != 'done' AS is_reopen,
    new_status.category = 'done' AS is_to_done,
    new_status.category = 'in_progress' AND old_status.category = 'todo' AS is_start_work,
    
    h.created_at AS changed_at,
    DATE_TRUNC('week', h.created_at) AS changed_week,
    DATE_TRUNC('month', h.created_at) AS changed_month

FROM issue_history h
JOIN issues i ON h.issue_id = i.id
JOIN projects p ON i.project_id = p.id
LEFT JOIN users u ON h.user_id = u.id
LEFT JOIN issue_statuses old_status ON h.old_value::int = old_status.id
LEFT JOIN issue_statuses new_status ON h.new_value::int = new_status.id
WHERE h.field_name = 'status'
  AND h.old_value ~ '^\d+$'  -- Ensure old_value is numeric
  AND h.new_value ~ '^\d+$'; -- Ensure new_value is numeric

-- ============================================
-- VIEW 3: fact_sprint_reports
-- Отчеты по спринтам с velocity и burndown
-- ============================================

DROP VIEW IF EXISTS public.fact_sprint_reports CASCADE;

CREATE VIEW public.fact_sprint_reports AS
SELECT 
    sr.id AS report_id,
    sr.sprint_id,
    s.name AS sprint_name,
    s.goal AS sprint_goal,
    s.status AS sprint_status,
    s.start_date,
    s.end_date,
    
    -- Board & Project info
    b.id AS board_id,
    b.name AS board_name,
    b.board_type,
    b.project_id,
    p.key AS project_key,
    p.name AS project_name,
    
    -- Points metrics
    sr.committed_points,
    sr.completed_points,
    sr.added_points,
    sr.removed_points,
    
    -- Velocity calculation
    CASE 
        WHEN sr.committed_points > 0 
        THEN ROUND((sr.completed_points::numeric / sr.committed_points::numeric) * 100, 1)
        ELSE 0 
    END AS completion_rate_pct,
    
    -- Issue counts
    sr.issues_completed,
    sr.issues_not_completed,
    sr.issues_completed + sr.issues_not_completed AS total_issues,
    
    -- JSONB data
    sr.burndown_data,
    sr.velocity_data,
    
    sr.generated_at

FROM sprint_reports sr
JOIN sprints s ON sr.sprint_id = s.id
JOIN boards b ON s.board_id = b.id
JOIN projects p ON b.project_id = p.id;

-- ============================================
-- VIEW 4: fact_worklogs (bonus)
-- Логи времени для анализа трудозатрат
-- ============================================

DROP VIEW IF EXISTS public.fact_worklogs CASCADE;

CREATE VIEW public.fact_worklogs AS
SELECT 
    w.id AS worklog_id,
    w.issue_id,
    i.key AS issue_key,
    i.summary AS issue_summary,
    
    i.project_id,
    p.key AS project_key,
    p.name AS project_name,
    
    w.author_id,
    u.display_name AS author_name,
    u.email AS author_email,
    
    w.time_spent AS time_spent_seconds,
    ROUND(w.time_spent / 3600.0, 2) AS time_spent_hours,
    ROUND(w.time_spent / 28800.0, 2) AS time_spent_days, -- 8h day
    
    w.work_description,
    w.started_at,
    w.created_at,
    
    DATE_TRUNC('week', w.started_at) AS work_week,
    DATE_TRUNC('month', w.started_at) AS work_month

FROM worklogs w
JOIN issues i ON w.issue_id = i.id
JOIN projects p ON i.project_id = p.id
LEFT JOIN users u ON w.author_id = u.id;

-- ============================================
-- Verify views
-- ============================================

-- Check row counts
SELECT 'fact_issues' as view_name, COUNT(*) as row_count FROM public.fact_issues
UNION ALL
SELECT 'fact_issue_status_changes', COUNT(*) FROM public.fact_issue_status_changes
UNION ALL
SELECT 'fact_sprint_reports', COUNT(*) FROM public.fact_sprint_reports
UNION ALL
SELECT 'fact_worklogs', COUNT(*) FROM public.fact_worklogs;
