SELECT 
    s.name AS sprint_name,
    s.status AS sprint_status,
    s.start_date,
    s.end_date,
    i.key AS issue_key,
    i.summary,
    ist.name AS status,
    ip.name AS priority,
    u.display_name AS assignee,
    i.story_points
FROM sprints s
JOIN issues i ON i.sprint_id = s.id
JOIN issue_statuses ist ON i.status_id = ist.id
JOIN issue_priorities ip ON i.priority_id = ip.id
LEFT JOIN users u ON i.assignee_id = u.id
{% if context.params.sprint_status %}
WHERE s.status = {{ context.params.sprint_status }}
{% endif %}
ORDER BY s.start_date DESC, i.priority_id
