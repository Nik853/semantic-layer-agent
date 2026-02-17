const express = require('express');
const { Pool } = require('pg');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(cors());
app.use(express.json());

// Meta configuration file path
const META_FILE = path.join(__dirname, 'api-meta.json');

// Load meta config
const loadMeta = () => {
  try {
    return JSON.parse(fs.readFileSync(META_FILE, 'utf8'));
  } catch (e) {
    return { endpoints: [], param_extractors: {} };
  }
};

// Save meta config
const saveMeta = (meta) => {
  fs.writeFileSync(META_FILE, JSON.stringify(meta, null, 2));
};

// PostgreSQL connection
const pool = new Pool({
  host: process.env.PGHOST || 'localhost',
  port: process.env.PGPORT || 5432,
  database: process.env.PGDATABASE || 'jira_clone',
  user: process.env.PGUSER || 'jira_user',
  password: process.env.PGPASSWORD || '',
  ssl: false
});

// Helper: build WHERE clauses
const buildFilters = (params, mapping) => {
  const conditions = [];
  const values = [];
  let idx = 1;
  
  for (const [param, column] of Object.entries(mapping)) {
    if (params[param] !== undefined && params[param] !== '') {
      conditions.push(`${column} = $${idx}`);
      values.push(params[param]);
      idx++;
    }
  }
  
  return { conditions, values, nextIdx: idx };
};

// Helper: select columns based on view parameter
const getColumns = (view, basicCols, wideCols) => {
  return view === 'wide' ? wideCols : basicCols;
};

// ============================================
// ENDPOINT 1: GET /jira/issues
// List issues with filters
// ============================================
app.get('/jira/issues', async (req, res) => {
  try {
    const { project_id, sprint_id, assignee_id, status_id, status_category,
            updated_from, updated_to, limit = 100, offset = 0, view = 'basic' } = req.query;
    
    const basicCols = `i.id, i.key, i.summary, p.key as project_key, 
                       ist.name as status, ip.name as priority, 
                       assignee.display_name as assignee`;
    const wideCols = `i.id, i.key, i.summary, i.description, 
                      p.id as project_id, p.key as project_key, p.name as project_name,
                      i.issue_type_id, it.name as issue_type,
                      i.status_id, ist.name as status, ist.category as status_category,
                      i.priority_id, ip.name as priority,
                      i.sprint_id, s.name as sprint_name,
                      i.reporter_id, reporter.display_name as reporter,
                      i.assignee_id, assignee.display_name as assignee,
                      i.story_points, i.original_estimate, i.time_spent,
                      i.due_date, i.created_at, i.updated_at, i.resolved_at`;
    
    const columns = getColumns(view, basicCols, wideCols);
    
    let query = `
      SELECT ${columns}
      FROM issues i
      JOIN projects p ON i.project_id = p.id
      JOIN issue_types it ON i.issue_type_id = it.id
      JOIN issue_statuses ist ON i.status_id = ist.id
      JOIN issue_priorities ip ON i.priority_id = ip.id
      LEFT JOIN sprints s ON i.sprint_id = s.id
      LEFT JOIN users reporter ON i.reporter_id = reporter.id
      LEFT JOIN users assignee ON i.assignee_id = assignee.id
      WHERE 1=1
    `;
    
    const values = [];
    let idx = 1;
    
    if (project_id) { query += ` AND i.project_id = $${idx++}`; values.push(project_id); }
    if (sprint_id) { query += ` AND i.sprint_id = $${idx++}`; values.push(sprint_id); }
    if (assignee_id) { query += ` AND i.assignee_id = $${idx++}`; values.push(assignee_id); }
    if (status_id) { query += ` AND i.status_id = $${idx++}`; values.push(status_id); }
    if (status_category) { query += ` AND ist.category = $${idx++}`; values.push(status_category); }
    if (updated_from) { query += ` AND i.updated_at >= $${idx++}`; values.push(updated_from); }
    if (updated_to) { query += ` AND i.updated_at <= $${idx++}`; values.push(updated_to); }
    
    query += ` ORDER BY i.updated_at DESC LIMIT $${idx++} OFFSET $${idx++}`;
    values.push(Math.min(parseInt(limit), 1000), parseInt(offset));
    
    const result = await pool.query(query, values);
    res.json({ count: result.rows.length, data: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================
// ENDPOINT 5: GET /jira/issues/search
// Full-text search (ILIKE) - MUST be before :issue_id route
// ============================================
app.get('/jira/issues/search', async (req, res) => {
  try {
    const { q, project_id, status_category, limit = 50, offset = 0, view = 'basic' } = req.query;
    
    if (!q || q.length < 2) {
      return res.status(400).json({ error: 'Search query (q) must be at least 2 characters' });
    }
    
    const basicCols = `i.id, i.key, i.summary, p.key as project_key, 
                       ist.name as status, ip.name as priority`;
    const wideCols = `i.id, i.key, i.summary, i.description,
                      p.key as project_key, p.name as project_name,
                      it.name as issue_type, ist.name as status, ist.category as status_category,
                      ip.name as priority, assignee.display_name as assignee,
                      i.created_at, i.updated_at`;
    
    const columns = getColumns(view, basicCols, wideCols);
    const searchPattern = `%${q}%`;
    
    let query = `
      SELECT ${columns}
      FROM issues i
      JOIN projects p ON i.project_id = p.id
      JOIN issue_types it ON i.issue_type_id = it.id
      JOIN issue_statuses ist ON i.status_id = ist.id
      JOIN issue_priorities ip ON i.priority_id = ip.id
      LEFT JOIN users assignee ON i.assignee_id = assignee.id
      WHERE (i.summary ILIKE $1 OR i.description ILIKE $1 OR i.key ILIKE $1)
    `;
    
    const values = [searchPattern];
    let idx = 2;
    
    if (project_id) { query += ` AND i.project_id = $${idx++}`; values.push(project_id); }
    if (status_category) { query += ` AND ist.category = $${idx++}`; values.push(status_category); }
    
    query += ` ORDER BY i.updated_at DESC LIMIT $${idx++} OFFSET $${idx++}`;
    values.push(Math.min(parseInt(limit), 200), parseInt(offset));
    
    const result = await pool.query(query, values);
    res.json({ query: q, count: result.rows.length, data: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================
// ENDPOINT 2: GET /jira/issues/:issue_id
// Single issue details - supports both numeric ID and issue key (e.g., AUTH-1)
// ============================================
app.get('/jira/issues/:issue_id', async (req, res) => {
  try {
    const { issue_id } = req.params;
    const { view = 'wide' } = req.query;
    
    // Determine if issue_id is numeric or a key (e.g., AUTH-1)
    const isNumeric = /^\d+$/.test(issue_id);
    const whereClause = isNumeric ? 'i.id = $1' : 'i.key = $1';
    
    const query = `
      SELECT i.id, i.key, i.summary, i.description,
             p.id as project_id, p.key as project_key, p.name as project_name,
             it.name as issue_type, ist.name as status, ist.category as status_category,
             ip.name as priority, ir.name as resolution,
             s.id as sprint_id, s.name as sprint_name,
             reporter.id as reporter_id, reporter.display_name as reporter,
             assignee.id as assignee_id, assignee.display_name as assignee,
             i.story_points, i.original_estimate, i.remaining_estimate, i.time_spent,
             i.due_date, i.created_at, i.updated_at, i.resolved_at, i.is_flagged
      FROM issues i
      JOIN projects p ON i.project_id = p.id
      JOIN issue_types it ON i.issue_type_id = it.id
      JOIN issue_statuses ist ON i.status_id = ist.id
      JOIN issue_priorities ip ON i.priority_id = ip.id
      LEFT JOIN issue_resolutions ir ON i.resolution_id = ir.id
      LEFT JOIN sprints s ON i.sprint_id = s.id
      LEFT JOIN users reporter ON i.reporter_id = reporter.id
      LEFT JOIN users assignee ON i.assignee_id = assignee.id
      WHERE ${whereClause}
    `;
    
    const result = await pool.query(query, [issue_id]);
    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Issue not found' });
    }
    res.json(result.rows[0]);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================
// ENDPOINT 3: GET /jira/issues/:issue_id/comments
// Comments for an issue - supports both numeric ID and issue key
// ============================================
app.get('/jira/issues/:issue_id/comments', async (req, res) => {
  try {
    const { issue_id } = req.params;
    const { limit = 50, offset = 0 } = req.query;
    
    // Determine if issue_id is numeric or a key
    const isNumeric = /^\d+$/.test(issue_id);
    const issueFilter = isNumeric ? 'c.issue_id = $1' : 'c.issue_id = (SELECT id FROM issues WHERE key = $1)';
    
    const query = `
      SELECT c.id, c.body, c.is_internal,
             u.id as author_id, u.display_name as author, u.email as author_email,
             c.created_at, c.updated_at
      FROM issue_comments c
      JOIN users u ON c.author_id = u.id
      WHERE ${issueFilter}
      ORDER BY c.created_at DESC
      LIMIT $2 OFFSET $3
    `;
    
    const result = await pool.query(query, [issue_id, Math.min(parseInt(limit), 500), parseInt(offset)]);
    res.json({ issue_id: issue_id, count: result.rows.length, data: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================
// ENDPOINT 4: GET /jira/issues/:issue_id/links
// Links for an issue - supports both numeric ID and issue key
// ============================================
app.get('/jira/issues/:issue_id/links', async (req, res) => {
  try {
    const { issue_id } = req.params;
    
    // Determine if issue_id is numeric or a key
    const isNumeric = /^\d+$/.test(issue_id);
    const issueIdExpr = isNumeric ? '$1::integer' : '(SELECT id FROM issues WHERE key = $1)';
    
    const query = `
      SELECT il.id, 
             lt.name as link_type, lt.inward_description, lt.outward_description,
             source.id as source_issue_id, source.key as source_issue_key, source.summary as source_summary,
             target.id as target_issue_id, target.key as target_issue_key, target.summary as target_summary,
             il.created_at
      FROM issue_links il
      JOIN issue_link_types lt ON il.link_type_id = lt.id
      JOIN issues source ON il.source_issue_id = source.id
      JOIN issues target ON il.target_issue_id = target.id
      WHERE il.source_issue_id = ${issueIdExpr} OR il.target_issue_id = ${issueIdExpr}
      ORDER BY il.created_at DESC
    `;
    
    const result = await pool.query(query, [issue_id]);
    res.json({ issue_id: issue_id, count: result.rows.length, data: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================
// ENDPOINT 6: GET /jira/projects
// List projects
// ============================================
app.get('/jira/projects', async (req, res) => {
  try {
    const { organization_id, is_archived, limit = 100, view = 'basic' } = req.query;
    
    const basicCols = `p.id, p.key, p.name, p.project_type, lead.display_name as lead`;
    const wideCols = `p.id, p.key, p.name, p.description, p.project_type, p.is_private, p.is_archived,
                      o.id as organization_id, o.name as organization_name,
                      lead.id as lead_id, lead.display_name as lead, lead.email as lead_email,
                      p.created_at, p.updated_at,
                      (SELECT COUNT(*) FROM issues WHERE project_id = p.id) as issues_count`;
    
    const columns = getColumns(view, basicCols, wideCols);
    
    let query = `
      SELECT ${columns}
      FROM projects p
      LEFT JOIN organizations o ON p.organization_id = o.id
      LEFT JOIN users lead ON p.lead_id = lead.id
      WHERE 1=1
    `;
    
    const values = [];
    let idx = 1;
    
    if (organization_id) { query += ` AND p.organization_id = $${idx++}`; values.push(organization_id); }
    if (is_archived !== undefined) { query += ` AND p.is_archived = $${idx++}`; values.push(is_archived === 'true'); }
    
    query += ` ORDER BY p.name LIMIT $${idx++}`;
    values.push(Math.min(parseInt(limit), 500));
    
    const result = await pool.query(query, values);
    res.json({ count: result.rows.length, data: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================
// ENDPOINT 7: GET /jira/sprints
// List sprints
// ============================================
app.get('/jira/sprints', async (req, res) => {
  try {
    const { board_id, project_id, status, limit = 100, view = 'basic' } = req.query;
    
    const basicCols = `s.id, s.name, s.status, s.start_date, s.end_date, b.name as board_name`;
    const wideCols = `s.id, s.name, s.goal, s.status, s.start_date, s.end_date, s.completed_date, s.velocity,
                      b.id as board_id, b.name as board_name, b.board_type,
                      p.id as project_id, p.key as project_key, p.name as project_name,
                      s.created_at, s.updated_at,
                      (SELECT COUNT(*) FROM issues WHERE sprint_id = s.id) as issues_count`;
    
    const columns = getColumns(view, basicCols, wideCols);
    
    let query = `
      SELECT ${columns}
      FROM sprints s
      JOIN boards b ON s.board_id = b.id
      JOIN projects p ON b.project_id = p.id
      WHERE 1=1
    `;
    
    const values = [];
    let idx = 1;
    
    if (board_id) { query += ` AND s.board_id = $${idx++}`; values.push(board_id); }
    if (project_id) { query += ` AND b.project_id = $${idx++}`; values.push(project_id); }
    if (status) { query += ` AND s.status = $${idx++}`; values.push(status); }
    
    query += ` ORDER BY s.start_date DESC LIMIT $${idx++}`;
    values.push(Math.min(parseInt(limit), 500));
    
    const result = await pool.query(query, values);
    res.json({ count: result.rows.length, data: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================
// ENDPOINT 8: GET /jira/users
// List/search users
// ============================================
app.get('/jira/users', async (req, res) => {
  try {
    const { q, is_active, limit = 100, view = 'basic' } = req.query;
    
    const basicCols = `u.id, u.username, u.display_name, u.email`;
    const wideCols = `u.id, u.username, u.display_name, u.email, u.is_active, u.is_admin,
                      u.timezone, u.locale, u.created_at, u.last_login_at,
                      up.job_title, up.department, up.location`;
    
    const columns = getColumns(view, basicCols, wideCols);
    
    let query = `
      SELECT ${columns}
      FROM users u
      LEFT JOIN user_profiles up ON u.id = up.user_id
      WHERE 1=1
    `;
    
    const values = [];
    let idx = 1;
    
    if (q) { 
      query += ` AND (u.display_name ILIKE $${idx} OR u.email ILIKE $${idx} OR u.username ILIKE $${idx})`;
      values.push(`%${q}%`);
      idx++;
    }
    if (is_active !== undefined) { query += ` AND u.is_active = $${idx++}`; values.push(is_active === 'true'); }
    
    query += ` ORDER BY u.display_name LIMIT $${idx++}`;
    values.push(Math.min(parseInt(limit), 500));
    
    const result = await pool.query(query, values);
    res.json({ count: result.rows.length, data: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================
// ENDPOINT 9: GET /jira/issues/:issue_id/worklogs
// Worklogs for an issue - supports both numeric ID and issue key
// ============================================
app.get('/jira/issues/:issue_id/worklogs', async (req, res) => {
  try {
    const { issue_id } = req.params;
    const { limit = 50, offset = 0 } = req.query;
    
    // Determine if issue_id is numeric or a key
    const isNumeric = /^\d+$/.test(issue_id);
    const issueFilter = isNumeric ? 'w.issue_id = $1' : 'w.issue_id = (SELECT id FROM issues WHERE key = $1)';
    const totalFilter = isNumeric ? 'issue_id = $1' : 'issue_id = (SELECT id FROM issues WHERE key = $1)';
    
    const query = `
      SELECT w.id, w.time_spent, 
             ROUND(w.time_spent / 3600.0, 2) as time_spent_hours,
             w.work_description, w.started_at,
             u.id as author_id, u.display_name as author,
             w.created_at, w.updated_at
      FROM worklogs w
      JOIN users u ON w.author_id = u.id
      WHERE ${issueFilter}
      ORDER BY w.started_at DESC
      LIMIT $2 OFFSET $3
    `;
    
    const result = await pool.query(query, [issue_id, Math.min(parseInt(limit), 500), parseInt(offset)]);
    
    // Calculate totals
    const totalQuery = `SELECT SUM(time_spent) as total_seconds FROM worklogs WHERE ${totalFilter}`;
    const totalResult = await pool.query(totalQuery, [issue_id]);
    const totalSeconds = totalResult.rows[0]?.total_seconds || 0;
    
    res.json({ 
      issue_id: issue_id, 
      count: result.rows.length,
      total_time_spent_seconds: parseInt(totalSeconds),
      total_time_spent_hours: Math.round(totalSeconds / 3600 * 100) / 100,
      data: result.rows 
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================
// ENDPOINT 10: GET /jira/issues/:issue_id/custom-fields
// Custom fields for an issue
// ============================================
app.get('/jira/issues/:issue_id/custom-fields', async (req, res) => {
  try {
    const { issue_id } = req.params;
    
    const query = `
      SELECT cf.id as field_id, cf.name as field_name, cft.name as field_type,
             cfv.text_value, cfv.number_value, cfv.date_value,
             cfo.value as option_value,
             u.display_name as user_value
      FROM issue_custom_field_values cfv
      JOIN custom_fields cf ON cfv.custom_field_id = cf.id
      JOIN custom_field_types cft ON cf.field_type_id = cft.id
      LEFT JOIN custom_field_options cfo ON cfv.option_value = cfo.id
      LEFT JOIN users u ON cfv.user_value = u.id
      WHERE cfv.issue_id = $1
      ORDER BY cf.name
    `;
    
    const result = await pool.query(query, [issue_id]);
    res.json({ issue_id: parseInt(issue_id), count: result.rows.length, data: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================
// Health check & API docs
// ============================================
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.get('/', (req, res) => {
  res.json({
    name: 'JIRA Data API (VulcanSQL-style)',
    version: '2.0.0',
    endpoints: [
      { method: 'GET', path: '/jira/issues', params: ['project_id?', 'sprint_id?', 'assignee_id?', 'status_id?', 'status_category?', 'updated_from?', 'updated_to?', 'limit?', 'offset?', 'view?'], description: '1. List issues with filters' },
      { method: 'GET', path: '/jira/issues/:issue_id', params: ['view?'], description: '2. Single issue details' },
      { method: 'GET', path: '/jira/issues/:issue_id/comments', params: ['limit?', 'offset?'], description: '3. Issue comments' },
      { method: 'GET', path: '/jira/issues/:issue_id/links', params: [], description: '4. Issue links' },
      { method: 'GET', path: '/jira/issues/search', params: ['q (required)', 'project_id?', 'status_category?', 'limit?', 'view?'], description: '5. Search issues (ILIKE)' },
      { method: 'GET', path: '/jira/projects', params: ['organization_id?', 'is_archived?', 'limit?', 'view?'], description: '6. List projects' },
      { method: 'GET', path: '/jira/sprints', params: ['board_id?', 'project_id?', 'status?', 'limit?', 'view?'], description: '7. List sprints' },
      { method: 'GET', path: '/jira/users', params: ['q?', 'is_active?', 'limit?', 'view?'], description: '8. List/search users' },
      { method: 'GET', path: '/jira/issues/:issue_id/worklogs', params: ['limit?', 'offset?'], description: '9. Issue worklogs' },
      { method: 'GET', path: '/jira/issues/:issue_id/custom-fields', params: [], description: '10. Issue custom fields' }
    ],
    notes: {
      view_param: 'view=basic (default) returns fewer columns, view=wide returns full data',
      limits: 'Default limit varies by endpoint, max is capped for safety'
    }
  });
});

// ============================================
// META API - Dynamic Configuration
// ============================================

// GET /meta - Get all metadata for Router Agent
app.get('/meta', (req, res) => {
  const meta = loadMeta();
  res.json(meta);
});

// GET /meta/endpoints - Get all endpoint configs
app.get('/meta/endpoints', (req, res) => {
  const meta = loadMeta();
  res.json({ endpoints: meta.endpoints || [] });
});

// GET /meta/endpoints/:id - Get single endpoint config
app.get('/meta/endpoints/:id', (req, res) => {
  const meta = loadMeta();
  const endpoint = (meta.endpoints || []).find(e => e.id === req.params.id);
  if (!endpoint) {
    return res.status(404).json({ error: 'Endpoint not found' });
  }
  res.json(endpoint);
});

// PUT /meta/endpoints/:id - Update endpoint keywords
app.put('/meta/endpoints/:id', (req, res) => {
  const meta = loadMeta();
  const idx = (meta.endpoints || []).findIndex(e => e.id === req.params.id);
  if (idx === -1) {
    return res.status(404).json({ error: 'Endpoint not found' });
  }
  
  // Update only allowed fields (keywords, description)
  const { keywords, description } = req.body;
  if (keywords) meta.endpoints[idx].keywords = keywords;
  if (description) meta.endpoints[idx].description = description;
  
  saveMeta(meta);
  res.json({ success: true, endpoint: meta.endpoints[idx] });
});

// POST /meta/endpoints/:id/keywords - Add keywords to endpoint
app.post('/meta/endpoints/:id/keywords', (req, res) => {
  const meta = loadMeta();
  const endpoint = (meta.endpoints || []).find(e => e.id === req.params.id);
  if (!endpoint) {
    return res.status(404).json({ error: 'Endpoint not found' });
  }
  
  const { lang = 'ru', keywords: newKeywords } = req.body;
  if (!newKeywords || !Array.isArray(newKeywords)) {
    return res.status(400).json({ error: 'keywords must be an array' });
  }
  
  endpoint.keywords = endpoint.keywords || { ru: [], en: [] };
  endpoint.keywords[lang] = [...new Set([...(endpoint.keywords[lang] || []), ...newKeywords])];
  
  saveMeta(meta);
  res.json({ success: true, keywords: endpoint.keywords });
});

// DELETE /meta/endpoints/:id/keywords - Remove keywords from endpoint
app.delete('/meta/endpoints/:id/keywords', (req, res) => {
  const meta = loadMeta();
  const endpoint = (meta.endpoints || []).find(e => e.id === req.params.id);
  if (!endpoint) {
    return res.status(404).json({ error: 'Endpoint not found' });
  }
  
  const { lang = 'ru', keywords: removeKeywords } = req.body;
  if (!removeKeywords || !Array.isArray(removeKeywords)) {
    return res.status(400).json({ error: 'keywords must be an array' });
  }
  
  endpoint.keywords = endpoint.keywords || { ru: [], en: [] };
  endpoint.keywords[lang] = (endpoint.keywords[lang] || []).filter(k => !removeKeywords.includes(k));
  
  saveMeta(meta);
  res.json({ success: true, keywords: endpoint.keywords });
});

// GET /meta/extractors - Get parameter extractors
app.get('/meta/extractors', (req, res) => {
  const meta = loadMeta();
  res.json({ extractors: meta.param_extractors || {} });
});

// PUT /meta/extractors/:name - Update extractor patterns
app.put('/meta/extractors/:name', (req, res) => {
  const meta = loadMeta();
  meta.param_extractors = meta.param_extractors || {};
  meta.param_extractors[req.params.name] = req.body;
  saveMeta(meta);
  res.json({ success: true, extractor: meta.param_extractors[req.params.name] });
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
  console.log(`JIRA Data API running on http://localhost:${PORT}`);
  console.log(`Meta API available at http://localhost:${PORT}/meta`);
});
