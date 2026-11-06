"""
Registry access for cpkg. A registry is either an http(s) base url or a local directory that has:

  index.json   -> {"packages": ["win_x86_64_mypkg_v1.0.0.pkg",
                                {"file": "linux_x86_64_other_2.0.pkg", "description": "..."}]}
  <file>.pkg   -> the packages listed in the index

Copyright (c) 2026 Alan. All Rights Reserved.
"""

import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import quote

from ..network_helper import NetworkRel
from .contact_rest import RESTContact
from .pkg_dests_util import host_arch_name, host_os_name
from .pkg_util import parse_pkg_filename


class RegistryError(Exception): ...


def _vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)


def _pad(a: tuple, b: tuple):
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def version_satisfies(have: str, op: str, want: str) -> bool:
    if not op or not want:
        return True
    a, b = _pad(_vkey(have), _vkey(want))
    match op:
        case "==":
            return a == b
        case "!=":
            return a != b
        case "<=":
            return a <= b
        case ">=":
            return a >= b
        case "<":
            return a < b
        case ">":
            return a > b
        case "~=":  # compatible release: >= want, same prefix except last part
            w = _vkey(want)
            prefix = w[:-1] if len(w) > 1 else w
            return a >= b and _pad(_vkey(have)[: len(prefix)], prefix)[0] == _pad(
                _vkey(have)[: len(prefix)], prefix
            )[1]
    return True


class Registry:
    def __init__(self, base: str):
        self.base = base.strip()
        self.is_remote = self.base.lower().startswith(("http://", "https://"))
        self.host_os = host_os_name()
        self.host_arch = host_arch_name()
        self._entries: list[dict] | None = None

    # -- index
    def _raw_index(self):
        if self.is_remote:
            url = f"{self.base.rstrip('/')}/index.json"
            try:
                status, data = RESTContact(url).get_req()
            except Exception as e:
                raise RegistryError(f"Could not reach registry '{self.base}': {e}")
            if status != 200:
                raise RegistryError(f"Registry answered HTTP {status} for {url}.")
            return data
        idx = Path(self.base).expanduser() / "index.json"
        try:
            return json.loads(idx.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise RegistryError(f"Could not read local registry index '{idx}': {e}")

    def entries(self) -> list[dict]:
        if self._entries is not None:
            return self._entries
        raw = self._raw_index()
        items = raw.get("packages") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            raise RegistryError("Registry index.json must contain a 'packages' list.")

        out = []
        for item in items:
            f = item if isinstance(item, str) else (item or {}).get("file")
            desc = "" if isinstance(item, str) else (item or {}).get("description", "")
            if not isinstance(f, str) or "/" in f or "\\" in f:
                continue
            parsed = parse_pkg_filename(f)
            if not parsed:
                continue
            os_, arch, name, ver = parsed
            out.append(
                {
                    "file": f,
                    "os": os_,
                    "arch": arch,
                    "name": name,
                    "version": ver,
                    "description": desc,
                }
            )
        self._entries = out
        return out

    # -- lookup
    def compatible(self) -> list[dict]:
        return [
            e
            for e in self.entries()
            if e["os"] in (self.host_os, "universal") and e["arch"] == self.host_arch
        ]

    def resolve(self, name: str, op: str = "", ver: str = "") -> dict | None:
        found = [
            e
            for e in self.compatible()
            if e["name"] == name and version_satisfies(e["version"], op, ver)
        ]
        if not found:
            return None
        # newest version first; exact OS beats `universal`
        return max(found, key=lambda e: (_vkey(e["version"]), e["os"] == self.host_os))

    def search(self, term: str = "") -> list[dict]:
        term = term.lower()
        best: dict[str, dict] = {}
        for e in self.compatible():
            if term and term not in e["name"].lower() and term not in e["description"].lower():
                continue
            cur = best.get(e["name"])
            if cur is None or _vkey(e["version"]) > _vkey(cur["version"]):
                best[e["name"]] = e
        return sorted(best.values(), key=lambda e: e["name"])

    # -- download
    def fetch(self, entry: dict, cache_dir: Path, force: bool = False) -> Path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / entry["file"]
        if dest.exists() and not force:
            return dest

        part = dest.with_name(dest.name + ".part")
        if self.is_remote:
            url = f"{self.base.rstrip('/')}/{quote(entry['file'])}"
            try:
                ok = NetworkRel(url).execute_method_and_return_custom_msg(
                    method="download", dest=str(part), success=True, failure=False
                )
            except Exception as e:
                part.unlink(missing_ok=True)
                raise RegistryError(f"Download failed for {entry['file']}: {e}")
            if not ok:
                part.unlink(missing_ok=True)
                raise RegistryError(f"Download failed for {entry['file']} ({url}).")
        else:
            src = Path(self.base).expanduser() / entry["file"]
            try:
                shutil.copyfile(src, part)
            except OSError as e:
                raise RegistryError(f"Could not copy '{src}': {e}")

        os.replace(part, dest)
        return dest
