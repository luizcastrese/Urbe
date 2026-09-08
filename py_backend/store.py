import json
import os
import threading

try:
    import psycopg
except ImportError:  # Postgres is optional when using the JSON store.
    psycopg = None

from .utils import deep_clone


COLLECTIONS = (
    "users",
    "sessions",
    "movies",
    "shares",
    "listings",
    "accessTokens",
    "paymentOrders",
    "playbackSessions",
    "transactions",
)


DEFAULT_DB = {
    "users": [],
    "sessions": [],
    "movies": [],
    "shares": [],
    "listings": [],
    "accessTokens": [],
    "paymentOrders": [],
    "playbackSessions": [],
    "transactions": [],
    "counters": {
        "user": 0,
        "session": 0,
        "movie": 0,
        "share": 0,
        "listing": 0,
        "token": 0,
        "paymentOrder": 0,
        "playbackSession": 0,
        "transaction": 0,
    },
}


def normalize_db(parsed):
    changed = False
    if not isinstance(parsed, dict):
        parsed = deep_clone(DEFAULT_DB)
        changed = True

    for key, default in DEFAULT_DB.items():
        if key == "counters":
            continue
        if not isinstance(parsed.get(key), list):
            parsed[key] = deep_clone(default)
            changed = True

    if not isinstance(parsed.get("counters"), dict):
        parsed["counters"] = {}
        changed = True

    for counter_key, default_value in DEFAULT_DB["counters"].items():
        value = parsed["counters"].get(counter_key)
        if not isinstance(value, int):
            parsed["counters"][counter_key] = default_value
            changed = True

    return parsed, changed


class JsonStore:
    def __init__(self, file_path):
        self.file_path = file_path
        self._lock = threading.RLock()
        self.ensure()

    def ensure(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

        if not os.path.exists(self.file_path):
            with open(self.file_path, "w", encoding="utf-8") as fh:
                json.dump(DEFAULT_DB, fh, indent=2, ensure_ascii=False)
            return

        try:
            with open(self.file_path, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
        except Exception:
            parsed = deep_clone(DEFAULT_DB)

        parsed, changed = normalize_db(parsed)

        if changed:
            with open(self.file_path, "w", encoding="utf-8") as fh:
                json.dump(parsed, fh, indent=2, ensure_ascii=False)

    def read(self):
        self.ensure()
        with open(self.file_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def write(self, data):
        tmp = f"{self.file_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.file_path)

    def transaction(self, callback):
        with self._lock:
            db = self.read()
            result = callback(db)
            self.write(db)
            return deep_clone(result)

    def snapshot(self):
        with self._lock:
            return deep_clone(self.read())


class PostgresStore:
    def __init__(self, database_url):
        if not psycopg:
            raise ValueError("psycopg is required for DATABASE_URL")
        if not database_url:
            raise ValueError("database_url is required")
        self.database_url = database_url
        self._lock = threading.RLock()
        self.ensure()

    def _connect(self):
        return psycopg.connect(self.database_url)

    def ensure(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS urbe_docs (
                        collection text NOT NULL,
                        id text NOT NULL,
                        doc jsonb NOT NULL,
                        PRIMARY KEY (collection, id)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS urbe_meta (
                        key text PRIMARY KEY,
                        value jsonb NOT NULL
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS urbe_docs_collection_idx ON urbe_docs (collection)")
                self._migrate_blob_if_needed(cur)
                cur.execute("SELECT value FROM urbe_meta WHERE key = 'counters'")
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO urbe_meta (key, value) VALUES ('counters', %s)",
                        (json.dumps(DEFAULT_DB["counters"]),),
                    )
            conn.commit()

    def _migrate_blob_if_needed(self, cur):
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'urbe_state'
            )
            """
        )
        has_blob = bool(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM urbe_docs")
        docs_count = int(cur.fetchone()[0] or 0)
        if not has_blob or docs_count:
            return
        cur.execute("SELECT data FROM urbe_state WHERE id = 1")
        row = cur.fetchone()
        if not row:
            return
        data = row[0]
        if isinstance(data, str):
            data = json.loads(data)
        data, _changed = normalize_db(data)
        self._write_db(cur, data)

    def _write_db(self, cur, data):
        data, _changed = normalize_db(data)
        cur.execute("DELETE FROM urbe_docs")
        for collection in COLLECTIONS:
            for item in data.get(collection) or []:
                item_id = str(item.get("id") or "").strip()
                if not item_id:
                    continue
                cur.execute(
                    "INSERT INTO urbe_docs (collection, id, doc) VALUES (%s, %s, %s)",
                    (collection, item_id, json.dumps(item, ensure_ascii=False)),
                )
        cur.execute(
            """
            INSERT INTO urbe_meta (key, value) VALUES ('counters', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (json.dumps(data["counters"]),),
        )

    def _read_db(self, cur):
        parsed = deep_clone(DEFAULT_DB)
        cur.execute("SELECT collection, doc FROM urbe_docs")
        for collection, doc in cur.fetchall():
            if collection not in parsed:
                continue
            if isinstance(doc, str):
                doc = json.loads(doc)
            parsed[collection].append(doc)
        cur.execute("SELECT value FROM urbe_meta WHERE key = 'counters'")
        row = cur.fetchone()
        if row:
            counters = row[0]
            if isinstance(counters, str):
                counters = json.loads(counters)
            parsed["counters"] = counters
        parsed, _changed = normalize_db(parsed)
        return parsed

    def transaction(self, callback):
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("LOCK TABLE urbe_docs, urbe_meta IN EXCLUSIVE MODE")
                    data = self._read_db(cur)
                    result = callback(data)
                    self._write_db(cur, data)
                conn.commit()
                return deep_clone(result)

    def snapshot(self):
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    return deep_clone(self._read_db(cur))
