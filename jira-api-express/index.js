const express = require('express');
const { Pool } = require('pg');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(express.json());

// PostgreSQL connection — configure via environment variables
const pool = new Pool({
  host: process.env.DB_HOST || 'localhost',
  port: parseInt(process.env.DB_PORT || '5432'),
  database: process.env.DB_NAME || 'jira_clone',
  user: process.env.DB_USER || 'jira_user',
  password: process.env.DB_PASS || '',
  ssl: process.env.DB_SSL === 'true' ? { rejectUnauthorized: false } : false
});

// GET /api/issues - List issues with project, reporter and dates
app.get('/api/issues', async (req, res) => {
  try {
    const { project_key, limit = 100 } = req.query;
    
    let query = `
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
    `;
    
    const params = [];
    if (project_key) {
      query += ` WHERE p.key = $1`;
      params.push(project_key);
    }
    
    query += ` ORDER BY i.created_at DESC LIMIT $${params.length + 1}`;
    params.push(parseInt(limit));
    
    const result = await pool.query(query, params);
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/issue/:id - Get issue by numeric ID
app.get('/api/issue/:id', async (req, res) => {
  try {
    const { id } = req.params;
    
    if (!id || isNaN(id)) {
      return res.status(400).json({ error: 'Valid numeric ID is required' });
    }
    
    const query = `
      SELECT 
        i.id,
        i.key AS issue_key,
        i.summary,
        i.description,
        p.name AS project_name,
        p.key AS project_key,
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
      WHERE i.id = $1
    `;
    
    const result = await pool.query(query, [parseInt(id)]);
    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Issue not found' });
    }
    res.json(result.rows[0]);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/issue - Get single issue details by key
app.get('/api/issue', async (req, res) => {
  try {
    const { issue_key } = req.query;
    if (!issue_key) {
      return res.status(400).json({ error: 'issue_key is required' });
    }
    
    const query = `
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
      WHERE i.key = $1
    `;
    
    const result = await pool.query(query, [issue_key]);
    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Issue not found' });
    }
    res.json(result.rows[0]);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/projects - List all projects
app.get('/api/projects', async (req, res) => {
  try {
    const query = `
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
    `;
    
    const result = await pool.query(query);
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/users - List all users
app.get('/api/users', async (req, res) => {
  try {
    const query = `
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
    `;
    
    const result = await pool.query(query);
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/sprint-issues - Issues by sprint
app.get('/api/sprint-issues', async (req, res) => {
  try {
    const { sprint_status } = req.query;
    
    let query = `
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
    `;
    
    const params = [];
    if (sprint_status) {
      query += ` WHERE s.status = $1`;
      params.push(sprint_status);
    }
    
    query += ` ORDER BY s.start_date DESC, i.priority_id`;
    
    const result = await pool.query(query, params);
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/comments - Get comments for an issue
app.get('/api/comments', async (req, res) => {
  try {
    const { issue_key } = req.query;
    if (!issue_key) {
      return res.status(400).json({ error: 'issue_key is required' });
    }
    
    const query = `
      SELECT 
        c.id,
        c.body,
        u.display_name AS author,
        c.created_at,
        c.updated_at
      FROM issue_comments c
      JOIN issues i ON c.issue_id = i.id
      JOIN users u ON c.author_id = u.id
      WHERE i.key = $1
      ORDER BY c.created_at DESC
    `;
    
    const result = await pool.query(query, [issue_key]);
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// API documentation
app.get('/', (req, res) => {
  res.json({
    name: 'JIRA Clone API',
    version: '1.0.0',
    endpoints: [
      { method: 'GET', path: '/api/issues', params: ['project_key?', 'limit?'], description: 'List issues' },
      { method: 'GET', path: '/api/issue/:id', params: ['id'], description: 'Get issue by numeric ID' },
      { method: 'GET', path: '/api/issue', params: ['issue_key'], description: 'Get issue details by key' },
      { method: 'GET', path: '/api/projects', params: [], description: 'List all projects' },
      { method: 'GET', path: '/api/users', params: [], description: 'List all users' },
      { method: 'GET', path: '/api/sprint-issues', params: ['sprint_status?'], description: 'Issues by sprint' },
      { method: 'GET', path: '/api/comments', params: ['issue_key'], description: 'Get issue comments' },
      { method: 'GET', path: '/health', params: [], description: 'Health check' }
    ]
  });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`JIRA API server running on http://localhost:${PORT}`);
});
