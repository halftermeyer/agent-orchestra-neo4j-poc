"""LLM provider key: encrypted (Fernet), kept out of the graph and out of the repo. Master key = ORCHESTRA_MASTER_KEY."""
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet


class KeyStore:
    def __init__(self, data_dir: Path, master_key: str, env_key: str | None = None):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(master_key.encode()).digest()))
        self._env_key = env_key
        self.file = self.dir / "llm_key.enc.json"
        self.settings_file = self.dir / "llm_settings.json"

    def set(self, key: str) -> None:
        meta = {"ciphertext": self._fernet.encrypt(key.encode()).decode(), "last4": key[-4:],
                "updatedAt": datetime.now(timezone.utc).isoformat()}
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta))
        os.chmod(tmp, 0o600)
        tmp.replace(self.file)

    def delete(self) -> None:
        self.file.unlink(missing_ok=True)

    def _stored(self) -> dict | None:
        return json.loads(self.file.read_text()) if self.file.exists() else None

    def get(self) -> str | None:
        """Effective key: the one saved in the UI takes precedence over the initial value from the environment."""
        s = self._stored()
        if s:
            return self._fernet.decrypt(s["ciphertext"].encode()).decode()
        return self._env_key

    def status(self) -> dict:
        s = self._stored()
        if s:
            return {"configured": True, "source": "ui", "last4": s["last4"], "updatedAt": s["updatedAt"]}
        if self._env_key:
            return {"configured": True, "source": "env", "last4": self._env_key[-4:], "updatedAt": None}
        return {"configured": False, "source": None, "last4": None, "updatedAt": None}

    def get_model(self) -> str | None:
        return json.loads(self.settings_file.read_text()).get("model") if self.settings_file.exists() else None

    def set_model(self, model: str) -> None:
        self.settings_file.write_text(json.dumps({"model": model}))
