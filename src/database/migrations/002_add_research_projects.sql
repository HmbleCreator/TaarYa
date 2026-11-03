CREATE TABLE IF NOT EXISTS research_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS project_id UUID
    REFERENCES research_projects(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_chat_sessions_project_updated
    ON chat_sessions(project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS project_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    item_type VARCHAR(16) NOT NULL CHECK (item_type IN ('search', 'star', 'paper', 'region')),
    title VARCHAR(240) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_project_items_project_created
    ON project_items(project_id, created_at DESC);

INSERT INTO research_projects (name, description)
SELECT 'My research', 'Workspace for existing TaarYa conversations.'
WHERE EXISTS (SELECT 1 FROM chat_sessions)
  AND NOT EXISTS (SELECT 1 FROM research_projects);

UPDATE chat_sessions
SET project_id = (SELECT id FROM research_projects ORDER BY created_at, id LIMIT 1)
WHERE project_id IS NULL AND EXISTS (SELECT 1 FROM research_projects);
