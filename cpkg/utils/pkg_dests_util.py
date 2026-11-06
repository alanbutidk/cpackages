"""
Util to determine the cache and packages that cpkg create/install
Copyright (c) 2026 Alan. All Rights Reserved.
"""

import os
import platform as _platform
from pathlib import Path
from sys import platform


def host_os_name() -> str:
    """OS name in .pkg naming format (`win`, `linux`, `macos`)."""
    if platform == "win32":
        return "win"
    if platform == "darwin":
        return "macos"
    return "linux"


def host_arch_name() -> str:
    """Arch name in .pkg naming format (`x86`, `x86_64`, `arm`, `aarch64`)."""
    m = _platform.machine().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if m in ("x86", "i386", "i686"):
        return "x86"
    if m in ("arm64", "aarch64"):
        return "aarch64"
    if m.startswith("arm"):
        return "arm"
    return m


class PackageDestinations:
    def __init__(
        self, custom_cache_dir: str | None = None, custom_install_dir: str | None = None
    ):
        self.ccd = custom_cache_dir
        self.cid = custom_install_dir

    def _win_base(self) -> Path:
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else Path("~/AppData/Local").expanduser()) / "CPackages"

    def where_cache_dir(self):
        if self.ccd:
            return str(Path(self.ccd).expanduser())
        if platform == "win32":
            return str(self._win_base() / "cache")
        if platform == "darwin":
            return str(Path("~/Library/Caches/CPackages/").expanduser())
        return str(Path("~/.cache/CPackages/").expanduser())

    def where_install_dir(self):
        if self.cid:
            return str(Path(self.cid).expanduser())
        if platform == "win32":
            return str(self._win_base() / "packages")
        if platform == "darwin":
            return str(Path("~/Library/Application Support/CPackages/packages").expanduser())
        return str(Path("~/.local/share/CPackages/packages").expanduser())

    def where_config_dir(self):
        if platform == "win32":
            return str(self._win_base() / "config")
        if platform == "darwin":
            return str(Path("~/Library/Application Support/CPackages/config").expanduser())
        return str(Path("~/.config/CPackages").expanduser())
