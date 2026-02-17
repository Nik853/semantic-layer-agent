SELECT 
    i.key AS issue_key,
    i.summary,
    i.description,
    p.name AS project_name,
    it.name AS issue_type,
    ist.name AS status,
    ip.name AS priority,
    reporter.display_name AS reporter,
    assignee.display_name AS assignee,
    i.story_points,
    i.created_at,
    i.due_date,
    i.resolved_at
FROM issues i
JOIN projects p ON i.project_id = p.id
JOIN issue_types it ON i.issue_type_id = it.id
JOIN issue_statuses ist ON i.status_id = ist.id
JOIN issue_priorities ip ON i.priority_id = ip.id
JOIN users reporter ON i.reporter_id = reporter.id
LEFT JOIN users assignee ON i.assignee_id = assignee.id
WHERE i.key = {{ context.params.issue_key | is_required }}
