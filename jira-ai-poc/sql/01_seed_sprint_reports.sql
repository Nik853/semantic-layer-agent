-- Seed data for sprint_reports
-- Generate reports for existing sprints

INSERT INTO sprint_reports (sprint_id, committed_points, completed_points, added_points, removed_points, issues_completed, issues_not_completed, burndown_data, velocity_data, generated_at)
SELECT 
    s.id as sprint_id,
    -- committed points: sum of story points at sprint start
    COALESCE((SELECT SUM(story_points) FROM issues WHERE sprint_id = s.id), 0) + (random() * 20)::int as committed_points,
    -- completed points: ~70-90% of committed
    (COALESCE((SELECT SUM(story_points) FROM issues WHERE sprint_id = s.id AND resolved_at IS NOT NULL), 0) * (0.7 + random() * 0.2))::int as completed_points,
    -- added points during sprint
    (random() * 15)::int as added_points,
    -- removed points
    (random() * 5)::int as removed_points,
    -- issues completed
    (SELECT COUNT(*) FROM issues WHERE sprint_id = s.id AND resolved_at IS NOT NULL) as issues_completed,
    -- issues not completed
    (SELECT COUNT(*) FROM issues WHERE sprint_id = s.id AND resolved_at IS NULL) as issues_not_completed,
    -- burndown data as JSONB
    jsonb_build_object(
        'days', jsonb_build_array(
            jsonb_build_object('day', 1, 'remaining', 100 + (random() * 20)::int, 'ideal', 100),
            jsonb_build_object('day', 2, 'remaining', 90 + (random() * 15)::int, 'ideal', 90),
            jsonb_build_object('day', 3, 'remaining', 80 + (random() * 15)::int, 'ideal', 80),
            jsonb_build_object('day', 4, 'remaining', 70 + (random() * 15)::int, 'ideal', 70),
            jsonb_build_object('day', 5, 'remaining', 60 + (random() * 15)::int, 'ideal', 60),
            jsonb_build_object('day', 6, 'remaining', 45 + (random() * 15)::int, 'ideal', 50),
            jsonb_build_object('day', 7, 'remaining', 35 + (random() * 15)::int, 'ideal', 40),
            jsonb_build_object('day', 8, 'remaining', 25 + (random() * 10)::int, 'ideal', 30),
            jsonb_build_object('day', 9, 'remaining', 15 + (random() * 10)::int, 'ideal', 20),
            jsonb_build_object('day', 10, 'remaining', 5 + (random() * 10)::int, 'ideal', 10)
        )
    ) as burndown_data,
    -- velocity data
    jsonb_build_object(
        'sprints', jsonb_build_array(
            jsonb_build_object('sprint', s.name, 'velocity', 30 + (random() * 20)::int)
        )
    ) as velocity_data,
    s.end_date as generated_at
FROM sprints s
WHERE s.status IN ('closed', 'active')
ON CONFLICT DO NOTHING;

-- Update issue_history to have more status changes for analytics
INSERT INTO issue_history (issue_id, user_id, field_name, field_type, old_value, new_value, old_string, new_string, created_at)
SELECT 
    i.id,
    i.assignee_id,
    'status',
    'status',
    '1', -- Open
    '3', -- In Progress
    'Open',
    'In Progress',
    i.created_at + interval '1 day' * (random() * 3)::int
FROM issues i
WHERE NOT EXISTS (
    SELECT 1 FROM issue_history h 
    WHERE h.issue_id = i.id AND h.field_name = 'status'
)
LIMIT 200;

-- Add more status transitions (In Progress -> Done)
INSERT INTO issue_history (issue_id, user_id, field_name, field_type, old_value, new_value, old_string, new_string, created_at)
SELECT 
    i.id,
    i.assignee_id,
    'status',
    'status',
    '3', -- In Progress
    '6', -- Done
    'In Progress',
    'Done',
    i.created_at + interval '1 day' * (3 + (random() * 5)::int)
FROM issues i
WHERE i.resolved_at IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM issue_history h 
    WHERE h.issue_id = i.id AND h.field_name = 'status' AND h.new_value = '6'
)
LIMIT 150;
