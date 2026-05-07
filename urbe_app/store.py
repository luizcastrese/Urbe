import json
import os
import threading

import psycopg

from .utils import deep_clone


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

ENTITY_TABLES = {
    "users": "urbe_users",
    "sessions": "urbe_sessions",
    "movies": "urbe_movies",
    "shares": "urbe_shares",
    "listings": "urbe_listings",
    "accessTokens": "urbe_access_tokens",
    "paymentOrders": "urbe_payment_orders",
    "playbackSessions": "urbe_playback_sessions",
    "transactions": "urbe_transactions",
}


def normalize_db(parsed):
    if not isinstance(parsed, dict):
        parsed = deep_clone(DEFAULT_DB)
    for key, default in DEFAULT_DB.items():
        if key == "counters":
            continue
        if not isinstance(parsed.get(key), list):
            parsed[key] = deep_clone(default)
    if not isinstance(parsed.get("counters"), dict):
        parsed["counters"] = {}
    for counter_key, default_value in DEFAULT_DB["counters"].items():
        if not isinstance(parsed["counters"].get(counter_key), int):
            parsed["counters"][counter_key] = default_value
    return parsed, False


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
        parsed, _changed = normalize_db(parsed)
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
    """PostgreSQL store backed by one table per entity.

    The service layer still works with an in-memory dict during each transaction,
    but persistence is normalized across real database tables instead of a single
    `urbe_state` JSONB document. This is a production-readiness step that keeps
    the current business logic compatible while making future SQL queries,
    indexing, auditing and migrations possible.
    """

    def __init__(self, database_url):
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
                for _key, table_name in ENTITY_TABLES.items():
                    cur.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            id text PRIMARY KEY,
                            data jsonb NOT NULL,
                            created_at timestamptz NOT NULL DEFAULT now(),
                            updated_at timestamptz NOT NULL DEFAULT now()
                        )
                        """
                    )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS urbe_counters (
                        name text PRIMARY KEY,
                        value integer NOT NULL DEFAULT 0,
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                for counter_name, value in DEFAULT_DB["counters"].items():
                    cur.execute(
                        "INSERT INTO urbe_counters (name, value) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                        (counter_name, value),
                    )
                self._migrate_legacy_state(cur)
            conn.commit()

    def _migrate_legacy_state(self, cur):
        cur.execute("SELECT to_regclass('public.urbe_state')")
        exists = cur.fetchone()[0]
        if not exists:
            return
        cur.execute("SELECT data FROM urbe_state WHERE id = 1")
        row = cur.fetchone()
        if not row:
            return
        state = row[0]
        if isinstance(state, str):
            state = json.loads(state)
        state, _changed = normalize_db(state)
        for key, table_name in ENTITY_TABLES.items():
            for item in state.get(key, []):
                item_id = str(item.get("id") or "")
                if not item_id:
                    continue
                cur.execute(
                    f"""
                    INSERT INTO {table_name} (id, data)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (item_id, json.dumps(item)),
                )
        for name, value in state.get("counters", {}).items():
            cur.execute(
                """
                INSERT INTO urbe_counters (name, value)
                VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET value = GREATEST(urbe_counters.value, EXCLUDED.value), updated_at = now()
                """,
                (name, int(value or 0)),
            )

    def _load_db(self, cur, for_update=False):
        suffix = " FOR UPDATE" if for_update else ""
        db = {key: [] for key in ENTITY_TABLES.keys()}
        for key, table_name in ENTITY_TABLES.items():
            cur.execute(f"SELECT data FROM {table_name} ORDER BY created_at, id{suffix}")
            db[key] = [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in cur.fetchall()]
        cur.execute(f"SELECT name, value FROM urbe_counters{suffix}")
        counters = {name: int(value) for name, value in cur.fetchall()}
        db["counters"] = {**DEFAULT_DB["counters"], **counters}
        db, _changed = normalize_db(db)
        return db

    def _persist_db(self, cur, db):
        db, _changed = normalize_db(db)
        for key, table_name in ENTITY_TABLES.items():
            items = db.get(key, [])
            seen_ids = set()
            for item in items:
                item_id = str(item.get("id") or "")
                if not item_id:
                    continue
                seen_ids.add(item_id)
                cur.execute(
                    f"""
                    INSERT INTO {table_name} (id, data)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()
                    """,
                    (item_id, json.dumps(item)),
                )
            cur.execute(f"SELECT id FROM {table_name}")
            current_ids = {row[0] for row in cur.fetchall()}
            stale_ids = current_ids - seen_ids
            for stale_id in stale_ids:
                cur.execute(f"DELETE FROM {table_name} WHERE id = %s", (stale_id,))
        for name, value in db.get("counters", {}).items():
            cur.execute(
                """
                INSERT INTO urbe_counters (name, value)
                VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """,
                (name, int(value or 0)),
            )

    def transaction(self, callback):
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    db = self._load_db(cur, for_update=True)
                    result = callback(db)
                    self._persist_db(cur, db)
                conn.commit()
                return deep_clone(result)

    def snapshot(self):
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    return deep_clone(self._load_db(cur, for_update=False))
