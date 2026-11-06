"""
Local state for cpkg: which packages are installed + user config (registry url).
Copyright (c) 2026 Alan. All Rights Reserved.

Files:
  <config_dir>/config.json     -> {"registry": "<url or local dir>"}
  <config_dir>/installed.json  -> {"<name>": {"version", "os", "arch", "file", "deps": [...]}}
Packages themselves live in <install_dir>/<name>/
"""

import json
import re
import shutil
from pathlib import Path

from .pkg_dests_util import PackageDestinations

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StoreError(Exception): ...


class Store:
    def __init__(self, dests: PackageDestinations | None = None):
        dests = dests or PackageDestinations()
        self.cache_dir = Path(dests.where_cache_dir())
        self.install_dir = Path(dests.where_install_dir())
        self.config_dir = Path(dests.where_config_dir())
        self._config_f = self.config_dir / "config.json"
        self._installed_f = self.config_dir / "installed.json"

    # -- json helpers
    def _read(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as e:
            raise StoreError(f"'{path}' is corrupted ({e}). Delete it to reset.")

    def _write(self, path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # -- config
    def get_registry(self) -> str | None:
        return self._read(self._config_f).get("registry")

    def set_registry(self, url: str):
        cfg = self._read(self._config_f)
        cfg["registry"] = url
        self._write(self._config_f, cfg)

    # -- installed db
    def installed(self) -> dict:
        return self._read(self._installed_f)

    def get(self, name: str) -> dict | None:
        return self.installed().get(name)

    def record(self, name: str, info: dict):
        db = self.installed()
        db[name] = info
        self._write(self._installed_f, db)

    def forget(self, name: str):
        db = self.installed()
        db.pop(name, None)
        self._write(self._installed_f, db)

    def dependents_of(self, name: str) -> list[str]:
        return [n for n, i in self.installed().items() if name in i.get("deps", [])]

    # -- paths
    def pkg_dir(self, name: str) -> Path:
        if not NAME_RE.match(name):
            raise StoreError(f"'{name}' is not a valid package name.")
        return self.install_dir / name

    def wipe_pkg_dir(self, name: str):
        target = self.pkg_dir(name).resolve()
        if self.install_dir.resolve() not in target.parents:
            raise StoreError(f"Refusing to delete '{target}' (outside install dir).")
        shutil.rmtree(target, ignore_errors=True)
