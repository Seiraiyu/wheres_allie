CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS home (version INTEGER PRIMARY KEY AUTOINCREMENT, saved_at REAL NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY,            -- ESPresense room id, e.g. 'master_bedroom'
  name TEXT, online INTEGER NOT NULL DEFAULT 0, last_seen REAL, ip TEXT,
  wifi_rssi INTEGER, uptime_s INTEGER, version TEXT, calib_json TEXT);
CREATE TABLE IF NOT EXISTS pets (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, species TEXT NOT NULL DEFAULT 'dog');
CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY, pet_id INTEGER NOT NULL REFERENCES pets(id),
  ibeacon_id TEXT NOT NULL UNIQUE,         -- ESPresense id, e.g. 'iBeacon:426c…-3838-4949'
  motion_ibeacon_id TEXT UNIQUE);          -- id broadcast while moving (NULL if not configured)
CREATE TABLE IF NOT EXISTS readings (ts REAL NOT NULL, tag_id INTEGER NOT NULL, node_id TEXT NOT NULL,
  rssi REAL NOT NULL, distance REAL, rssi_var REAL);
CREATE INDEX IF NOT EXISTS readings_tag_ts ON readings(tag_id, ts);
CREATE TABLE IF NOT EXISTS motion (ts REAL NOT NULL, tag_id INTEGER NOT NULL, moving INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS motion_tag_ts ON motion(tag_id, ts);
CREATE TABLE IF NOT EXISTS positions (ts REAL NOT NULL, tag_id INTEGER NOT NULL, vertex_id TEXT NOT NULL,
  room_id TEXT, floor_id TEXT, confidence REAL NOT NULL, moving INTEGER);
CREATE INDEX IF NOT EXISTS positions_tag_ts ON positions(tag_id, ts);
CREATE TABLE IF NOT EXISTS visits (id INTEGER PRIMARY KEY, tag_id INTEGER NOT NULL, place_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('room','landmark','transit','away')), start REAL NOT NULL, "end" REAL);
CREATE INDEX IF NOT EXISTS visits_tag_start ON visits(tag_id, start);
CREATE TABLE IF NOT EXISTS labels (id INTEGER PRIMARY KEY, tag_id INTEGER NOT NULL, vertex_id TEXT NOT NULL,
  ts_start REAL NOT NULL, ts_end REAL NOT NULL, source TEXT NOT NULL CHECK (source IN ('walk','tap','voice','import')));
CREATE TABLE IF NOT EXISTS gaps (ts_start REAL NOT NULL, ts_end REAL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rollups (tag_id INTEGER NOT NULL, date TEXT NOT NULL, json TEXT NOT NULL,
  PRIMARY KEY (tag_id, date));
