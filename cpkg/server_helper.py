"""
Registry server scaffolding for `cpkg create-server`.

Modes:
  local         127.0.0.1:<port>, saved as the active registry, optionally started
  professional  0.0.0.0:<port>, ships Dockerfile + systemd unit + serve.py for hosting
  ghost         throwaway: temp dir, free port, no config written, removed on exit

Interactive when stdin is a TTY; non-interactive with --yes, CI=1,
CPKG_NONINTERACTIVE=1, or when stdin is not a TTY.

Copyright (c) 2026 Alan. All Rights Reserved.
"""

import json
import re
import shutil
import socket
import sys
import tempfile
from dataclasses import dataclass, field
from os import environ
from pathlib import Path

MODES = ("local", "professional", "ghost")
DEFAULT_PORTS = {"local": 8000, "professional": 8080, "ghost": 0}
DEFAULT_HOSTS = {"local": "127.0.0.1", "professional": "0.0.0.0", "ghost": "127.0.0.1"}
ENV_NONINTERACTIVE = "CPKG_NONINTERACTIVE"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PKG_RE = re.compile(
    r"^(win|universal|linux|macos)_(x86_64|x86|arm|aarch64)_.+_[^_]+\.pkg$",
    re.IGNORECASE,
)


class ServerSetupError(Exception): ...


@dataclass
class ServerConfig:
    mode: str = "local"
    dir: Path | None = None
    name: str = "cpkg-registry"
    host: str = ""
    port: int = -1
    url: str = ""
    seed: Path | None = None
    start: bool = False
    set_registry: bool | None = None
    force: bool = False
    notes: list[str] = field(default_factory=list)


def is_noninteractive(yes_flag: bool) -> bool:
    if yes_flag:
        return True
    if (environ.get(ENV_NONINTERACTIVE) or "").strip().lower() in ("1", "true", "yes"):
        return True
    if (environ.get("CI") or "").strip().lower() in ("1", "true", "yes"):
        return True
    try:
        return not sys.stdin.isatty()
    except (AttributeError, ValueError):
        return True


def parse_port(raw: str | int, allow_zero: bool = False) -> int:
    try:
        port = int(str(raw).strip())
    except ValueError:
        raise ServerSetupError(f"'{raw}' is not a port number")
    low = 0 if allow_zero else 1
    if not low <= port <= 65535:
        raise ServerSetupError(f"port must be {low}-65535, got {port}")
    return port


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def port_in_use(host: str, port: int) -> bool:
    probe = "127.0.0.1" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((probe, port)) == 0


def _validate_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ServerSetupError(f"'{name}' is not a valid server name")
    return name


def _validate_url(url: str) -> str:
    if url and not url.lower().startswith(("http://", "https://")):
        raise ServerSetupError(f"--url must start with http:// or https://, got '{url}'")
    return url.rstrip("/")


# ----------------------------------------------------------------------------- prompts
def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        raw = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default
    return raw or default


def _ask_yn(prompt: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = _ask(f"{prompt} ({hint})", "").lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("Please answer y or n.")


def _ask_choice(prompt: str, options: tuple[str, ...], default: str) -> str:
    while True:
        raw = _ask(f"{prompt} ({'/'.join(options)})", default).lower()
        if raw in options:
            return raw
        print(f"Pick one of: {', '.join(options)}")


def _ask_valid(prompt: str, default: str, check):
    while True:
        raw = _ask(prompt, default)
        try:
            return check(raw)
        except ServerSetupError as e:
            print(f"  {e}")


def fill_interactively(cfg: ServerConfig, given: set[str]) -> None:
    """Prompt only for values that were not passed as flags."""
    if "mode" not in given:
        cfg.mode = _ask_choice("Server type", MODES, cfg.mode)

    if "name" not in given:
        cfg.name = _ask_valid("Server name", cfg.name, _validate_name)

    if "dir" not in given:
        base = "ghost" if cfg.mode == "ghost" else cfg.name
        if cfg.mode != "ghost":
            cfg.dir = Path(_ask("Directory to create it in", f"./{base}")).expanduser()

    if "host" not in given and cfg.mode == "professional":
        cfg.host = _ask("Bind address", DEFAULT_HOSTS["professional"])

    if "port" not in given and cfg.mode != "ghost":
        default = str(DEFAULT_PORTS[cfg.mode])
        cfg.port = _ask_valid("Port", default, parse_port)

    if "url" not in given and cfg.mode == "professional":
        cfg.url = _ask_valid(
            "Public URL (blank to skip)", "", lambda v: _validate_url(v.strip())
        )

    if "seed" not in given:
        raw = _ask("Folder with .pkg files to publish (blank to skip)", "")
        cfg.seed = Path(raw).expanduser() if raw else None

    if cfg.mode == "local" and "set_registry" not in given:
        cfg.set_registry = _ask_yn("Use this server as your cpkg registry?", True)

    if cfg.mode != "ghost" and "start" not in given:
        cfg.start = _ask_yn("Start it now?", cfg.mode == "local")


def resolve_defaults(cfg: ServerConfig) -> None:
    if cfg.mode not in MODES:
        raise ServerSetupError(f"unknown type '{cfg.mode}' (use {', '.join(MODES)})")
    _validate_name(cfg.name)
    cfg.url = _validate_url(cfg.url)

    if not cfg.host:
        cfg.host = DEFAULT_HOSTS[cfg.mode]
    if cfg.port < 0:
        cfg.port = DEFAULT_PORTS[cfg.mode]

    if cfg.mode == "ghost":
        cfg.start = True
        cfg.set_registry = False
        cfg.host = "127.0.0.1" if cfg.host == "0.0.0.0" and not cfg.url else cfg.host
        if cfg.port == 0:
            cfg.port = free_port(cfg.host)
    elif cfg.port == 0:
        raise ServerSetupError("port 0 is only valid for ghost servers")

    if cfg.set_registry is None:
        cfg.set_registry = cfg.mode == "local"

    if cfg.seed is not None and not cfg.seed.is_dir():
        raise ServerSetupError(f"seed folder '{cfg.seed}' does not exist")

    if cfg.mode == "local" and cfg.host not in ("127.0.0.1", "localhost", "::1"):
        cfg.notes.append(f"local server is bound to {cfg.host}, not loopback")


def public_url(cfg: ServerConfig) -> str:
    if cfg.url:
        return cfg.url
    host = "127.0.0.1" if cfg.host in ("0.0.0.0", "") else cfg.host
    host = f"[{host}]" if ":" in host else host
    return f"http://{host}:{cfg.port}"


# ----------------------------------------------------------------------------- scaffold
def _write(path: Path, text: str, force: bool) -> None:
    if path.exists() and not force:
        raise ServerSetupError(f"'{path}' already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _seed_packages(src: Path, reg_dir: Path) -> list[str]:
    copied = []
    for f in sorted(src.glob("*.pkg")):
        if _PKG_RE.match(f.name):
            shutil.copyfile(f, reg_dir / f.name)
            copied.append(f.name)
    return copied


def write_index(reg_dir: Path) -> list[str]:
    idx = reg_dir / "index.json"
    old_desc: dict[str, str] = {}
    try:
        for item in json.loads(idx.read_text(encoding="utf-8")).get("packages", []):
            if isinstance(item, dict) and item.get("file"):
                old_desc[item["file"]] = item.get("description", "")
    except (OSError, ValueError, AttributeError):
        pass

    files = sorted(f.name for f in reg_dir.glob("*.pkg") if _PKG_RE.match(f.name))
    packages = [
        {"file": n, "description": old_desc[n]} if old_desc.get(n) else n for n in files
    ]
    idx.write_text(json.dumps({"packages": packages}, indent=2), encoding="utf-8")
    return files


def scaffold(cfg: ServerConfig) -> Path:
    """Create the server folder. Returns the folder that holds serve.py."""
    if cfg.mode == "ghost":
        root = Path(tempfile.mkdtemp(prefix="cpkg-ghost-"))
    else:
        root = (cfg.dir or Path(f"./{cfg.name}")).expanduser().resolve()
        if root.exists() and any(root.iterdir()) and not cfg.force:
            raise ServerSetupError(
                f"'{root}' is not empty (use --force to write into it anyway)"
            )
        root.mkdir(parents=True, exist_ok=True)

    reg_dir = root / "registry"
    reg_dir.mkdir(exist_ok=True)

    if cfg.seed is not None:
        _seed_packages(cfg.seed, reg_dir)
    write_index(reg_dir)

    server_json = {
        "name": cfg.name,
        "mode": cfg.mode,
        "host": cfg.host,
        "port": cfg.port,
        "url": public_url(cfg),
    }
    _write(root / "server.json", json.dumps(server_json, indent=2) + "\n", True)
    _write(root / "serve.py", SERVE_PY, True)

    if cfg.mode == "professional":
        _write(root / "Dockerfile", DOCKERFILE.format(port=cfg.port), cfg.force)
        _write(
            root / f"{cfg.name}.service",
            SYSTEMD_UNIT.format(name=cfg.name, host=cfg.host, port=cfg.port),
            cfg.force,
        )
        _write(root / ".dockerignore", "__pycache__\n*.pyc\n", cfg.force)

    return root


def remove_ghost(root: Path) -> None:
    if root.name.startswith("cpkg-ghost-"):
        shutil.rmtree(root, ignore_errors=True)


# ----------------------------------------------------------------------------- run
def run_server(root: Path, host: str, port: int) -> None:
    """Foreground server. Same code path the generated serve.py uses."""
    import runpy

    ns = runpy.run_path(str(root / "serve.py"), run_name="cpkg_serve")
    ns["serve"](root, host, port)


SERVE_PY = '''\
import json
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from os import environ
from pathlib import Path

PKG_RE = re.compile(
    r"^(win|universal|linux|macos)_(x86_64|x86|arm|aarch64)_.+_[^_]+\\.pkg$",
    re.IGNORECASE,
)


def reindex(reg_dir):
    idx = reg_dir / "index.json"
    desc = {}
    try:
        for item in json.loads(idx.read_text(encoding="utf-8")).get("packages", []):
            if isinstance(item, dict) and item.get("file"):
                desc[item["file"]] = item.get("description", "")
    except (OSError, ValueError, AttributeError):
        pass
    files = sorted(f.name for f in reg_dir.glob("*.pkg") if PKG_RE.match(f.name))
    packages = [{"file": n, "description": desc[n]} if desc.get(n) else n for n in files]
    idx.write_text(json.dumps({"packages": packages}, indent=2), encoding="utf-8")
    return files


class Handler(SimpleHTTPRequestHandler):
    reg_dir = None

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/index.json":
            reindex(self.reg_dir)
        super().do_GET()

    def do_POST(self):
        self.send_error(405)

    do_PUT = do_DELETE = do_PATCH = do_POST

    def list_directory(self, path):
        self.send_error(404)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def serve(root, host, port):
    reg_dir = Path(root) / "registry"
    reg_dir.mkdir(exist_ok=True)
    files = reindex(reg_dir)
    handler = type("RegistryHandler", (Handler,), {"reg_dir": reg_dir})
    httpd = ThreadingHTTPServer((host, port), partial(handler, directory=str(reg_dir)))
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else host
    print(f"serving {len(files)} package(s) on http://{shown}:{httpd.server_address[1]}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    cfg = {}
    try:
        cfg = json.loads((root / "server.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    host = environ.get("HOST") or (sys.argv[1] if len(sys.argv) > 1 else cfg.get("host", "127.0.0.1"))
    port = int(environ.get("PORT") or (sys.argv[2] if len(sys.argv) > 2 else cfg.get("port", 8000)))
    serve(root, host, port)
'''

DOCKERFILE = """\
FROM python:3.12-slim
WORKDIR /srv
COPY . /srv
ENV HOST=0.0.0.0 PORT={port}
EXPOSE {port}
CMD ["python", "serve.py"]
"""

SYSTEMD_UNIT = """\
[Unit]
Description=cpkg registry ({name})
After=network.target

[Service]
WorkingDirectory=/srv/{name}
ExecStart=/usr/bin/python3 /srv/{name}/serve.py {host} {port}
Restart=on-failure
DynamicUser=yes

[Install]
WantedBy=multi-user.target
"""
