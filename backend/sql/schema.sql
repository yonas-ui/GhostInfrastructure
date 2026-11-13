-- Ghost Infrastructure: PostgreSQL schema (generated from app/models.py).
-- The API creates these tables automatically on startup; this file is for reference / manual setup.

CREATE TABLE users (
	id SERIAL NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE projects (
	id SERIAL NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	description TEXT NOT NULL, 
	owner_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_projects_owner_id ON projects (owner_id);

CREATE TABLE services (
	id SERIAL NOT NULL, 
	project_id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	type VARCHAR(30) NOT NULL, 
	description TEXT NOT NULL, 
	owner VARCHAR(120) NOT NULL, 
	environment VARCHAR(30) NOT NULL, 
	criticality INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	health_url VARCHAR(500), 
	tags JSONB NOT NULL, 
	last_checked_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_service_project_name UNIQUE (project_id, name), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);
CREATE INDEX ix_services_project_id ON services (project_id);
CREATE INDEX ix_services_status ON services (status);

CREATE TABLE simulations (
	id SERIAL NOT NULL, 
	project_id INTEGER NOT NULL, 
	created_by INTEGER, 
	name VARCHAR(160) NOT NULL, 
	failed_service_ids JSONB NOT NULL, 
	result JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_simulations_project_id ON simulations (project_id);

CREATE TABLE dependencies (
	id SERIAL NOT NULL, 
	project_id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	target_id INTEGER NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	description TEXT NOT NULL, 
	documented BOOLEAN NOT NULL, 
	discovered_by VARCHAR(30) NOT NULL, 
	observed_count INTEGER NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_dependency_pair UNIQUE (source_id, target_id), 
	CONSTRAINT ck_dependency_no_self_loop CHECK (source_id <> target_id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_id) REFERENCES services (id) ON DELETE CASCADE, 
	FOREIGN KEY(target_id) REFERENCES services (id) ON DELETE CASCADE
);
CREATE INDEX ix_dependencies_project_id ON dependencies (project_id);
CREATE INDEX ix_dependencies_source_id ON dependencies (source_id);
CREATE INDEX ix_dependencies_target_id ON dependencies (target_id);

CREATE TABLE deployments (
	id SERIAL NOT NULL, 
	project_id INTEGER NOT NULL, 
	service_id INTEGER NOT NULL, 
	version VARCHAR(80) NOT NULL, 
	deployed_by VARCHAR(120) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	notes TEXT NOT NULL, 
	deployed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE
);
CREATE INDEX ix_deployments_deployed_at ON deployments (deployed_at);
CREATE INDEX ix_deployments_project_id ON deployments (project_id);
CREATE INDEX ix_deployments_service_id ON deployments (service_id);

CREATE TABLE health_checks (
	id SERIAL NOT NULL, 
	service_id INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	latency_ms FLOAT, 
	status_code INTEGER, 
	error TEXT, 
	source VARCHAR(20) NOT NULL, 
	checked_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE
);
CREATE INDEX ix_health_checks_checked_at ON health_checks (checked_at);
CREATE INDEX ix_health_checks_service_id ON health_checks (service_id);

CREATE TABLE incidents (
	id SERIAL NOT NULL, 
	project_id INTEGER NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	root_cause_service_id INTEGER, 
	auto_detected BOOLEAN NOT NULL, 
	summary TEXT NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(root_cause_service_id) REFERENCES services (id) ON DELETE SET NULL
);
CREATE INDEX ix_incidents_project_id ON incidents (project_id);
CREATE INDEX ix_incidents_root_cause_service_id ON incidents (root_cause_service_id);

CREATE TABLE alerts (
	id SERIAL NOT NULL, 
	project_id INTEGER NOT NULL, 
	service_id INTEGER, 
	incident_id INTEGER, 
	kind VARCHAR(40) NOT NULL, 
	level VARCHAR(20) NOT NULL, 
	message TEXT NOT NULL, 
	dedupe_key VARCHAR(200), 
	acknowledged BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE SET NULL, 
	FOREIGN KEY(incident_id) REFERENCES incidents (id) ON DELETE SET NULL
);
CREATE INDEX ix_alerts_created_at ON alerts (created_at);
CREATE INDEX ix_alerts_dedupe_key ON alerts (dedupe_key);
CREATE INDEX ix_alerts_project_id ON alerts (project_id);

CREATE TABLE incident_events (
	id SERIAL NOT NULL, 
	incident_id INTEGER NOT NULL, 
	service_id INTEGER, 
	event_type VARCHAR(30) NOT NULL, 
	message TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(incident_id) REFERENCES incidents (id) ON DELETE CASCADE, 
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE SET NULL
);
CREATE INDEX ix_incident_events_incident_id ON incident_events (incident_id);

-- Example: blast radius of service 42 as a recursive query (cycle-safe, depth-limited).
-- WITH RECURSIVE walk(service_id, depth, path) AS (
--     SELECT d.source_id, 1, ',' || 42 || ',' || d.source_id || ','
--     FROM dependencies d WHERE d.target_id = 42
--   UNION ALL
--     SELECT d.source_id, w.depth + 1, w.path || d.source_id || ','
--     FROM dependencies d JOIN walk w ON d.target_id = w.service_id
--     WHERE w.depth < 25 AND w.path NOT LIKE '%,' || d.source_id || ',%'
-- )
-- SELECT s.name, MIN(w.depth) AS depth FROM walk w JOIN services s ON s.id = w.service_id GROUP BY s.name ORDER BY depth;
