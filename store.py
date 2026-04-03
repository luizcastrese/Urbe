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
                    CREATE TABLE IF NOT EXISTS urbe_state (
                        id integer PRIMARY KEY,
                        data jsonb NOT NULL,
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    "INSERT INTO urbe_state (id, data) VALUES (1, %s) ON CONFLICT (id) DO NOTHING",
                    (json.dumps(DEFAULT_DB),),
                )
                cur.execute("SELECT data FROM urbe_state WHERE id = 1")
                row = cur.fetchone()
                data = row[0] if row else deep_clone(DEFAULT_DB)
                if isinstance(data, str):
                    data = json.loads(data)
                data, changed = normalize_db(data)
                if changed:
                    cur.execute(
                        "UPDATE urbe_state SET data = %s, updated_at = now() WHERE id = 1",
                        (json.dumps(data),),
                    )
            conn.commit()

    def _load(self, cur, for_update=False):
        query = "SELECT data FROM urbe_state WHERE id = 1"
        if for_update:
            query += " FOR UPDATE"
        cur.execute(query)
        row = cur.fetchone()
        data = row[0] if row else deep_clone(DEFAULT_DB)
        if isinstance(data, str):
            data = json.loads(data)
        data, changed = normalize_db(data)
        return data, changed

    def transaction(self, callback):
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    data, _changed = self._load(cur, for_update=True)
                    result = callback(data)
                    cur.execute(
                        "UPDATE urbe_state SET data = %s, updated_at = now() WHERE id = 1",
                        (json.dumps(data),),
                    )
                conn.commit()
                return deep_clone(result)

    def snapshot(self):
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    data, changed = self._load(cur, for_update=False)
                    if changed:
                        cur.execute(
                            "UPDATE urbe_state SET data = %s, updated_at = now() WHERE id = 1",
                            (json.dumps(data),),
                        )
                        conn.commit()
                    return deep_clone(data)