"""Persistent cursor per database. A file, not the graph: writing the cursor into the watched database
would produce a CDC event, hence a new cursor, hence an infinite loop."""
import json
import os
import threading
from pathlib import Path


class CursorStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _load(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, db: str) -> str | None:
        with self._lock:
            return self._load().get(db)

    def set(self, db: str, cursor: str) -> None:
        with self._lock:
            data = self._load()
            data[db] = cursor
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, self.path)
