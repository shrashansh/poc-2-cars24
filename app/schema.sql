-- Complaint Command Center (POC). SQLite for the demo; the same model maps 1:1 to PostgreSQL.

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- Mock "platform servers": what Trustpilot / X / Google / app stores / complaint sites / email would return
CREATE TABLE IF NOT EXISTS mock_feed (
  platform TEXT NOT NULL, external_post_id TEXT NOT NULL,
  user_id TEXT NOT NULL, handle TEXT, display_name TEXT,
  title TEXT, body TEXT NOT NULL, rating INTEGER,
  release_at TEXT NOT NULL,                 -- when the post "appears" on the platform
  edit_body TEXT, edit_rating INTEGER, edit_at TEXT,
  PRIMARY KEY (platform, external_post_id));

-- Mock Cars24 records (read-only lookups in production)
CREATE TABLE IF NOT EXISTS crm_booking (
  booking_ref TEXT PRIMARY KEY, crm_ref TEXT NOT NULL, phone TEXT NOT NULL, name TEXT,
  kind TEXT, model TEXT, reg_no TEXT, city TEXT, hub TEXT, booking_date TEXT,
  facts TEXT NOT NULL DEFAULT '{}');      -- JSON: refund / rc / warranty / plan / holdback / challans

CREATE TABLE IF NOT EXISTS customer (
  customer_id TEXT PRIMARY KEY, crm_ref TEXT UNIQUE, phone_hash TEXT UNIQUE, created_at TEXT);

CREATE TABLE IF NOT EXISTS platform_identity (
  identity_id TEXT PRIMARY KEY, platform TEXT NOT NULL, platform_user_id TEXT NOT NULL,
  handle TEXT, display_name TEXT, customer_id TEXT, status TEXT NOT NULL DEFAULT 'unlinked',
  first_seen_at TEXT, last_seen_at TEXT,
  UNIQUE (platform, platform_user_id));

CREATE TABLE IF NOT EXISTS complaint_case (
  case_id TEXT PRIMARY KEY, case_ref TEXT UNIQUE NOT NULL,
  customer_id TEXT, crm_ref TEXT, theme TEXT NOT NULL, role TEXT,
  priority INTEGER NOT NULL DEFAULT 3, owner_team TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',      -- new, routed, in_progress, resolved, merged
  identity_status TEXT NOT NULL DEFAULT 'unlinked',
  vehicle_reg_no TEXT, booking_ref TEXT, amount_at_risk REAL, legal_risk INTEGER NOT NULL DEFAULT 0,
  summary TEXT, facts TEXT NOT NULL DEFAULT '{}',
  first_action_due TEXT, resolve_due TEXT, first_action_at TEXT,
  escalation_level INTEGER NOT NULL DEFAULT 1,
  opened_at TEXT NOT NULL, resolved_at TEXT, resolution_proof TEXT, merged_into TEXT);

CREATE TABLE IF NOT EXISTS complaint_post (
  post_id TEXT PRIMARY KEY, platform TEXT NOT NULL, external_post_id TEXT NOT NULL,
  identity_id TEXT NOT NULL, case_id TEXT,
  title TEXT, body TEXT NOT NULL, body_masked TEXT, rating INTEGER, language TEXT,
  posted_at TEXT NOT NULL, edited_at TEXT, content_hash TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
  theme TEXT, role TEXT, amount_inr REAL, extracted_ids TEXT NOT NULL DEFAULT '{}',
  legal_risk INTEGER NOT NULL DEFAULT 0, sentiment TEXT, classifier TEXT, classifier_conf REAL,
  fetched_at TEXT, processed_at TEXT,
  UNIQUE (platform, external_post_id));

CREATE TABLE IF NOT EXISTS post_version (
  post_id TEXT, version INTEGER, body TEXT, rating INTEGER, seen_at TEXT, PRIMARY KEY (post_id, version));

CREATE TABLE IF NOT EXISTS identity_match (
  match_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, crm_ref TEXT, booking_ref TEXT,
  other_case_id TEXT, method TEXT NOT NULL, confidence REAL NOT NULL, evidence TEXT,
  confirmed_by TEXT, confirmed_at TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS tracked_link (
  token TEXT PRIMARY KEY, case_id TEXT NOT NULL, post_id TEXT NOT NULL, identity_id TEXT NOT NULL,
  platform TEXT NOT NULL, channel TEXT NOT NULL DEFAULT 'public_reply',
  status TEXT NOT NULL DEFAULT 'issued', issued_at TEXT, expires_at TEXT,
  first_click_at TEXT, click_count INTEGER NOT NULL DEFAULT 0, submitted_at TEXT, verified_at TEXT);

CREATE TABLE IF NOT EXISTS otp_challenge (
  token TEXT PRIMARY KEY, phone TEXT NOT NULL, code TEXT NOT NULL, expires_at TEXT, attempts INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS reply (
  reply_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, post_id TEXT, token TEXT,
  platform TEXT, body TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
  drafted_by TEXT, approved_by TEXT, created_at TEXT, posted_at TEXT);

CREATE TABLE IF NOT EXISTS case_event (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, event_type TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}', actor TEXT NOT NULL DEFAULT 'system', created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS source_watermark (
  platform TEXT PRIMARY KEY, last_seen TEXT, last_run_at TEXT, fetched_total INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS ignored_post (               -- positive or off-topic posts, counted but not cased
  platform TEXT, external_post_id TEXT, reason TEXT, seen_at TEXT, PRIMARY KEY (platform, external_post_id));

CREATE INDEX IF NOT EXISTS ix_post_identity ON complaint_post (identity_id, posted_at);
CREATE INDEX IF NOT EXISTS ix_post_case ON complaint_post (case_id);
CREATE INDEX IF NOT EXISTS ix_case_status ON complaint_case (status, first_action_due);
CREATE INDEX IF NOT EXISTS ix_event_case ON case_event (case_id, event_id);
