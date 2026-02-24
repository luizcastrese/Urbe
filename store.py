import json
import os
import threading

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

        changed = False
        try:
            with open(self.file_path, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
            if not isinstance(parsed, dict):
                raise ValueError("Invalid db")
        except Exception:
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

