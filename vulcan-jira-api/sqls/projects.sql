SELECT 
    p.id,
    p.key,
    p.name,
    p.description,
    u.display_name AS lead_name,
    p.project_type,
    p.created_at,
    (SELECT COUNT(*) FROM issues WHERE project_id = p.id) AS issues_count
FROM projects p
LEFT JOIN users u ON p.lead_id = u.id
ORDER BY p.name
