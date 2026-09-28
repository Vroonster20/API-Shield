CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at_ms INTEGER NOT NULL);
CREATE TABLE config_revisions (version INTEGER PRIMARY KEY, document_json TEXT NOT NULL, checksum TEXT NOT NULL, actor_admin_id TEXT NOT NULL, created_at_ms INTEGER NOT NULL);
CREATE TABLE runtime_config (
 singleton INTEGER PRIMARY KEY CHECK (singleton = 1), desired_version INTEGER REFERENCES config_revisions(version),
 applied_version INTEGER REFERENCES config_revisions(version), applied_at_ms INTEGER,
 apply_error_code TEXT, apply_error_version INTEGER, heartbeat_ms INTEGER,
 gateway_instance_id TEXT, started_at_ms INTEGER, dropped_events_since_start INTEGER
);
INSERT INTO runtime_config(singleton) VALUES (1);
CREATE TABLE security_clock (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), last_seen_ms INTEGER NOT NULL);
INSERT INTO security_clock(singleton,last_seen_ms) VALUES (1,0);
CREATE TABLE rate_counters (
 service_id TEXT NOT NULL, route_id TEXT NOT NULL, settings_hash TEXT NOT NULL, client_digest TEXT NOT NULL,
 window_start_ms INTEGER NOT NULL, count INTEGER NOT NULL CHECK(count >= 0), expires_at_ms INTEGER NOT NULL,
 PRIMARY KEY(service_id,route_id,settings_hash,client_digest,window_start_ms)
);
CREATE INDEX rate_counters_expiry ON rate_counters(expires_at_ms);
CREATE TABLE abuse_counters (
 service_id TEXT NOT NULL, client_digest TEXT NOT NULL, settings_hash TEXT NOT NULL, window_start_ms INTEGER NOT NULL,
 count INTEGER NOT NULL CHECK(count >= 0), threshold_recorded INTEGER NOT NULL CHECK(threshold_recorded IN (0,1)),
 expires_at_ms INTEGER NOT NULL, PRIMARY KEY(service_id,client_digest,settings_hash,window_start_ms)
);
CREATE INDEX abuse_counters_expiry ON abuse_counters(expires_at_ms);
CREATE TABLE bans (
 service_id TEXT NOT NULL, client_digest TEXT NOT NULL, ban_id TEXT NOT NULL UNIQUE,
 source TEXT NOT NULL CHECK(source IN ('manual','automatic')), created_at_ms INTEGER NOT NULL,
 expires_at_ms INTEGER NOT NULL, revoked_at_ms INTEGER, reason_code TEXT NOT NULL,
 PRIMARY KEY(service_id,client_digest)
);
CREATE INDEX bans_expiry ON bans(expires_at_ms);
CREATE TABLE admins (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at_ms INTEGER NOT NULL);
CREATE TABLE admin_sessions (
 token_hash TEXT PRIMARY KEY, admin_id TEXT NOT NULL REFERENCES admins(id), csrf_token TEXT NOT NULL,
 created_at_ms INTEGER NOT NULL, last_seen_ms INTEGER NOT NULL, expires_at_ms INTEGER NOT NULL, revoked_at_ms INTEGER
);
CREATE INDEX admin_sessions_expiry ON admin_sessions(expires_at_ms);
CREATE TABLE admin_login_counters (
 scope TEXT NOT NULL, client_digest_or_global TEXT NOT NULL, window_start_ms INTEGER NOT NULL,
 count INTEGER NOT NULL CHECK(count >= 0), expires_at_ms INTEGER NOT NULL,
 PRIMARY KEY(scope,client_digest_or_global,window_start_ms)
);
CREATE INDEX admin_login_counters_expiry ON admin_login_counters(expires_at_ms);
CREATE TABLE request_events (
 id INTEGER PRIMARY KEY, request_id TEXT NOT NULL, at_ms INTEGER NOT NULL, config_version INTEGER,
 route_id TEXT, method TEXT NOT NULL, decision TEXT NOT NULL, reason_code TEXT NOT NULL,
 status_code INTEGER, upstream_status INTEGER, client_digest TEXT, duration_ms INTEGER NOT NULL,
 request_bytes INTEGER NOT NULL, response_bytes INTEGER NOT NULL, origin_attempted INTEGER NOT NULL,
 truncated INTEGER NOT NULL
);
CREATE INDEX request_events_time ON request_events(at_ms,id);
CREATE INDEX request_events_route_time ON request_events(route_id,at_ms,id);
CREATE TABLE security_events (
 id INTEGER PRIMARY KEY, at_ms INTEGER NOT NULL, actor_type TEXT NOT NULL CHECK(actor_type IN ('system','admin')),
 actor_id TEXT, event_type TEXT NOT NULL, service_id TEXT, client_digest TEXT,
 entity_id TEXT, request_id TEXT, safe_details_json TEXT NOT NULL
);
CREATE INDEX security_events_time ON security_events(at_ms,id);
CREATE TABLE fuzz_runs (
 run_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, seed INTEGER NOT NULL, requested_by TEXT NOT NULL,
 state TEXT NOT NULL, created_at_ms INTEGER NOT NULL, started_at_ms INTEGER, finished_at_ms INTEGER,
 passed_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0,
 error_count INTEGER NOT NULL DEFAULT 0, report_json TEXT
);
CREATE INDEX fuzz_runs_time ON fuzz_runs(created_at_ms,run_id);
