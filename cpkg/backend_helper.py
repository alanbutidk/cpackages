"""
Backend wiring for cpkg: *where* things live (registry server + local store/database).
No CLI code in here, cli.py only calls make_store() and get_registry().

Registry resolution order (first one that is set wins):
  1. --registry                      (the `override` argument)
  2. CPKG_REG_URL                    (see below)
  3. CPKG_REGISTRY                   (legacy env var, url or local folder)
  4. the registry saved by `cpkg registry <url-or-folder>`

CPKG_REG_URL:
  - a normal url (https://reg.example.com)  -> used as is
  - a loopback address (127.0.0.1, localhost, ::1, optionally with scheme/path)
        -> the port comes from the url if it has one (http://127.0.0.1:8000),
           otherwise from CPKG_REG_LOCAL_PORT_NUMBER (required, 1-65535).
           A missing scheme defaults to http://.

Copyright (c) 2026 Alan. All Rights Reserved.
"""

import ipaddress
from os import environ
from urllib.parse import urlsplit

from .utils.pkg_dests_util import PackageDestinations
from .utils.registry_util import Registry, RegistryError
from .utils.store_util import Store

ENV_REG_URL = "CPKG_REG_URL"
ENV_REG_LOCAL_PORT = "CPKG_REG_LOCAL_PORT_NUMBER"
ENV_REG_LEGACY = "CPKG_REGISTRY"
ENV_CACHE_DIR = "CPKG_CACHE_DIR"
ENV_INSTALL_DIR = "CPKG_INSTALL_DIR"


def _env(name: str) -> str:
    return (environ.get(name) or "").strip()


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback  # 127.0.0.0/8 and ::1
    except ValueError:
        return False


def _local_port_from_env(shown: str) -> int:
    raw = _env(ENV_REG_LOCAL_PORT)
    if not raw:
        raise RegistryError(
            f"{ENV_REG_URL} is '{shown}' (a local address) but {ENV_REG_LOCAL_PORT} is not set"
        )
    if not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise RegistryError(
            f"{ENV_REG_LOCAL_PORT} must be a port number (1-65535), got '{raw}'"
        )
    return int(raw)


def registry_url_from_env() -> str | None:
    """Value of CPKG_REG_URL with the local-port rule applied (None if unset)."""
    raw = _env(ENV_REG_URL)
    if not raw:
        return None

    has_scheme = "://" in raw
    parts = urlsplit(raw if has_scheme else f"//{raw}")
    host = parts.hostname
    if not _is_loopback(host):
        return raw

    try:
        port = parts.port
    except ValueError:
        raise RegistryError(f"{ENV_REG_URL} '{raw}' has an invalid port")
    if port is None:
        port = _local_port_from_env(raw)

    scheme = parts.scheme if has_scheme else "http"
    host_part = f"[{host}]" if host and ":" in host else host
    return f"{scheme}://{host_part}:{port}{parts.path}"


def make_store() -> Store:
    return Store(
        PackageDestinations(
            custom_cache_dir=environ.get(ENV_CACHE_DIR),
            custom_install_dir=environ.get(ENV_INSTALL_DIR),
        )
    )


def get_registry(store: Store, override: str | None = None) -> Registry:
    url = (
        override
        or registry_url_from_env()
        or _env(ENV_REG_LEGACY)
        or store.get_registry()
    )
    if not url:
        raise RegistryError(
            "No registry set. Use `cpkg registry <url-or-folder>`, "
            f"the {ENV_REG_URL} env var or --registry"
        )
    return Registry(url)
