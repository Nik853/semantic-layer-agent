SELECT 
    u.id,
    u.username,
    u.display_name,
    u.email,
    up.job_title,
    up.department,
    up.location,
    (SELECT COUNT(*) FROM issues WHERE assignee_id = u.id) AS assigned_issues,
    (SELECT COUNT(*) FROM issues WHERE reporter_id = u.id) AS reported_issues
FROM users u
LEFT JOIN user_profiles up ON u.id = up.user_id
WHERE u.is_active = true
ORDER BY u.display_name
