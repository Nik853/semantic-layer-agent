SELECT 
    p.name AS project_name,
    i.key AS issue_key,
    i.summary AS issue_title,
    u.display_name AS reporter_name,
    i.created_at AS start_date,
    i.due_date AS end_date
FROM issues i
JOIN projects p ON i.project_id = p.id
JOIN users u ON i.reporter_id = u.id
{% if context.params.project_key %}
WHERE p.key = {{ context.params.project_key }}
{% endif %}
ORDER BY i.created_at DESC
LIMIT {{ context.params.limit | default(100) }}
