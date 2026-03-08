CREATE TABLE IF NOT EXISTS orchestration_runs (
  id TEXT PRIMARY KEY,
  trigger_source TEXT NOT NULL,
  user_id TEXT,
  report_date TEXT,
  report_type TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
  error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_orchestration_runs_started_at
  ON orchestration_runs (started_at);

CREATE INDEX IF NOT EXISTS idx_orchestration_runs_status_started
  ON orchestration_runs (status, started_at);

CREATE TABLE IF NOT EXISTS orchestration_stage_runs (
  id TEXT PRIMARY KEY,
  orchestration_run_id TEXT NOT NULL,
  stage_name TEXT NOT NULL,
  attempt_no INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
  metrics_json TEXT NOT NULL,
  error_message TEXT,
  FOREIGN KEY (orchestration_run_id) REFERENCES orchestration_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_orchestration_stage_runs_run_stage
  ON orchestration_stage_runs (orchestration_run_id, stage_name, attempt_no);

CREATE INDEX IF NOT EXISTS idx_orchestration_stage_runs_status_started
  ON orchestration_stage_runs (status, started_at);

CREATE TABLE IF NOT EXISTS alert_dispatch_log (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  signal_id TEXT NOT NULL,
  urgency TEXT NOT NULL,
  channel TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('sent', 'failed')),
  dispatched_at TEXT NOT NULL,
  response_meta_json TEXT,
  UNIQUE (signal_id, channel),
  FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE INDEX IF NOT EXISTS idx_alert_dispatch_log_user_time
  ON alert_dispatch_log (user_id, dispatched_at);

