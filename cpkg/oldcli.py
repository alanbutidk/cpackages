from .utils.color import Color
from .utils.pkg_dests_util import PackageDestinations, host_arch_name, host_os_name
from .utils.pkg_util import (
    Generate,
    Unpack,
    parse_pkg_filename,
)
from .utils.depends_parser_util import DependsParser
from .utils.registry_util import Registry, RegistryError, version_satisfies
from .utils.store_util import Store, StoreError
from .nice_output_helper import NiceOutputs
from . import __version__
from arghandle import ArgHandle
from types import SimpleNamespace
from os import environ
from pathlib import Path
from sys import stderr, stdout, argv

c = Color()
out = NiceOutputs()


def _cpkg_errp(
    text: str,
    stdout_redirect: bool = False,
    skip_hardcoded_cpkg_err_text: bool = False,
    skip_hardcoded_exc_mark: bool = False,
):
    stream = stdout if stdout_redirect else stderr

    prefix = "" if skip_hardcoded_cpkg_err_text else "CPackage error: "
    suffix = "" if skip_hardcoded_exc_mark else "!"

    print(f"{c.YELLOW}{prefix}{text}{suffix}{c.RESET}", file=stream)


def _cpkg_warnp(
    text: str,
    stdout_redirect: bool = False,
    skip_hardcoded_cpkg_warn_text: bool = False,
    skip_hardcoded_exc_mark: bool = False,
):
    stream = stdout if stdout_redirect else stderr
    prefix = "" if skip_hardcoded_cpkg_warn_text else "CPackage warn: "
    suffix = "" if skip_hardcoded_exc_mark else "!"

    print(f"{c.YELLOW}{prefix}{text}{suffix}{c.RESET}", file=stream)


class CPkgError(Exception): ...


def _make_store() -> Store:
    return Store(
        PackageDestinations(
            custom_cache_dir=environ.get("CPKG_CACHE_DIR"),
            custom_install_dir=environ.get("CPKG_INSTALL_DIR"),
        )
    )


def _get_registry(store: Store, override: str | None) -> Registry:
    url = override or environ.get("CPKG_REGISTRY") or store.get_registry()
    if not url:
        raise CPkgError(
            "No registry set. Use `cpkg registry <url-or-folder>`, the CPKG_REGISTRY env var or --registry"
        )
    return Registry(url)


# ----------------------------------------------------------------------------- install
def _install_from_file(store: Store, pkg_file: Path, seen: set, reg_getter) -> str:
    parsed = parse_pkg_filename(pkg_file.name)
    if parsed is None:
        raise CPkgError(
            f"'{pkg_file.name}' does not follow <OS>_<ARCH>_<NAME>_<VERSION>.pkg"
        )
    os_, arch, name, ver = parsed

    out.install_output(name)
    dest = store.pkg_dir(name)
    store.wipe_pkg_dir(name)  # clean slate (also handles upgrades)
    try:
        Unpack(pkg_file).unpack(dest)
    except Exception:
        store.wipe_pkg_dir(name)
        raise

    # dependencies
    dep_names = []
    dep_file = dest / "DEPENDENCIES"
    if dep_file.exists():
        for dname, op, dver in DependsParser(dep_file).parse():
            dep_names.append(dname)
            _install_spec(store, dname, op, dver, seen, reg_getter)

    store.record(
        name,
        {
            "version": ver,
            "os": os_,
            "arch": arch,
            "file": pkg_file.name,
            "deps": dep_names,
        },
    )
    out.installed_output(name, ver)
    return name


def _install_spec(store: Store, name: str, op: str, ver: str, seen: set, reg_getter):
    if name in seen:  # cycle / already handled in this run
        return
    seen.add(name)

    cur = store.get(name)
    if cur and version_satisfies(cur["version"], op, ver):
        out.already_output(name, cur["version"])
        return

    reg: Registry = reg_getter()
    entry = reg.resolve(name, op, ver)
    if entry is None:
        wanted = f"{name}{op}{ver}" if op else name
        raise CPkgError(
            f"No package matching '{wanted}' for {host_os_name()}/{host_arch_name()} in the registry"
        )
    pkg_file = reg.fetch(entry, store.cache_dir)
    _install_from_file(store, pkg_file, seen, reg_getter)


def cmd_install(args, store: Store):
    parser = DependsParser()
    seen: set = set()
    _reg = {}

    def reg_getter() -> Registry:
        if "r" not in _reg:
            _reg["r"] = _get_registry(store, args.registry)
        return _reg["r"]

    total = len(args.packages)
    for i, spec in enumerate(args.packages, 1):
        p = Path(spec)
        if spec.lower().endswith(".pkg") and p.is_file():
            _install_from_file(store, p, seen, reg_getter)
        else:
            parsed = parser.parse_line(spec)
            if not parsed:
                raise CPkgError(f"Invalid package spec '{spec}'")
            _install_spec(store, *parsed, seen, reg_getter)
        out.progress(i, total)


# ----------------------------------------------------------------------------- remove
def cmd_remove(args, store: Store):
    for name in args.packages:
        if not store.get(name):
            _cpkg_warnp(f"{name} is not installed")
            continue
        users = store.dependents_of(name)
        if users and not args.force:
            raise CPkgError(
                f"{name} is required by: {', '.join(users)} (use --force to remove anyway)"
            )
        store.wipe_pkg_dir(name)
        store.forget(name)
        out.remove_output(name)


# ----------------------------------------------------------------------------- list/search/info
def cmd_list(args, store: Store):
    db = store.installed()
    if not db:
        print("No packages installed.")
        return
    rows = [
        (n, i["version"], f"{i['os']}/{i['arch']}", ", ".join(i.get("deps", [])) or "-")
        for n, i in sorted(db.items())
    ]
    out.table(rows, ("NAME", "VERSION", "PLATFORM", "DEPENDS"))


def cmd_search(args, store: Store):
    reg = _get_registry(store, args.registry)
    res = reg.search(args.term or "")
    if not res:
        print("Nothing found.")
        return
    out.table(
        [(e["name"], e["version"], e["description"] or "-") for e in res],
        ("NAME", "LATEST", "DESCRIPTION"),
    )


def cmd_info(args, store: Store):
    cur = store.get(args.package)
    if not cur:
        raise CPkgError(f"{args.package} is not installed")
    print(
        f"{c.BOLD}{args.package} {cur['version']}{c.RESET}  ({cur['os']}/{cur['arch']})"
    )
    print(f"Location: {store.pkg_dir(args.package)}")
    info_f = store.pkg_dir(args.package) / "INFO.md"
    if info_f.exists():
        print()
        print(info_f.read_text(encoding="utf-8", errors="replace"))


# ----------------------------------------------------------------------------- pack / registry
def cmd_pack(args, store: Store):
    path = Generate(args.dir).gen(
        name=args.name,
        vs=args.version,
        os_name=args.os,
        arch=args.arch,
        src_dir=args.src,
    )
    print(f"{c.GREEN}{path}{c.RESET}")


def cmd_registry(args, store: Store):
    if args.url:
        store.set_registry(args.url)
        print(f"{c.GREEN}Registry set to {args.url}{c.RESET}")
    else:
        print(store.get_registry() or "(not set)")


def _commands() -> dict[str, dict]:
    """Command table. pos: None | "?" (optional) | "+" (1+) | 1 (exactly one)."""
    return {
        "install": dict(
            help="install packages (name, name==1.0, or a local .pkg)",
            func=cmd_install,
            pos=("packages", "+"),
            opts=[dict(flags=["--registry"], help="registry url or local folder")],
        ),
        "remove": dict(
            help="remove installed packages",
            func=cmd_remove,
            pos=("packages", "+"),
            opts=[dict(flags=["--force"], help="force removal", bool=True)],
        ),
        "list": dict(help="list installed packages", func=cmd_list, pos=None, opts=[]),
        "search": dict(
            help="search the registry",
            func=cmd_search,
            pos=("term", "?"),
            opts=[dict(flags=["--registry"], help="registry url or local folder")],
        ),
        "info": dict(
            help="show info about an installed package",
            func=cmd_info,
            pos=("package", 1),
            opts=[],
        ),
        "pack": dict(
            help="build a .pkg from a package folder "
            "(DIR is the root folder: has INFO.md and <name>/LICENSE, <name>/<src>)",
            func=cmd_pack,
            pos=("dir", 1),
            opts=[
                dict(flags=["--name"], help="package name", required=True),
                dict(flags=["--version"], help="package version", required=True),
                dict(flags=["--os"], help="target OS", default=host_os_name),
                dict(flags=["--arch"], help="target arch", default=host_arch_name),
                dict(flags=["--src"], help="source folder name", default=lambda: "src"),
            ],
        ),
        "registry": dict(
            help="show or set the registry (url or local folder)",
            func=cmd_registry,
            pos=("url", "?"),
            opts=[],
        ),
    }


def _attr(flags: list[str]) -> str:
    return flags[0].lstrip("-").replace("-", "_")


def parse_args(args_list: list[str] | None = None) -> SimpleNamespace:
    # ArgHandle reads sys.argv directly, so splice in args_list (if given) for the parse.
    saved = argv[:]
    if args_list is not None:
        argv[:] = [saved[0], *args_list]
    try:
        cli = ArgHandle(
            "cpkg",
            __version__,
            NoArgsMsg="No command given! Use --help/-h for usage.",
        )
        specs = _commands()
        handles = {}
        for name, spec in specs.items():
            cmd = cli.RegisterCommand(name, spec["help"])
            for o in spec["opts"]:
                cmd.RegisterArg(
                    o["flags"],
                    Type=bool if o.get("bool") else str,
                    HelpMsg=o["help"],
                )
            handles[name] = cmd

        cli.Parse()  # no-args message, global --version/--help, `<cmd> --help`

        name = cli.ActiveCommand()
        if name is None:
            raise CPkgError(f"unknown command '{argv[1]}'. Use --help/-h for usage.")
        spec, cmd = specs[name], handles[name]

        # `-h/--help` anywhere after the command -> that command's help
        if any(t in ("-h", "--help") for t in cmd.args[1:]):
            cmd.args[1:] = ["--help"]
            cmd.HandleBasic()

        known = {f for o in spec["opts"] for f in o["flags"]}
        valued = {f for o in spec["opts"] if not o.get("bool") for f in o["flags"]}
        toks, positionals, i = cmd.args[1:], [], 0
        while i < len(toks):
            t = toks[i]
            if t.startswith("-") and len(t) > 1:
                if t not in known:
                    raise CPkgError(f"{name}: unknown option '{t}'")
                if t in valued:
                    if i + 1 >= len(toks) or toks[i + 1].startswith("-"):
                        raise CPkgError(f"{name}: '{t}' expects a value")
                    i += 1
            else:
                positionals.append(t)
            i += 1

        ns = SimpleNamespace(cmd=name, func=spec["func"])
        if spec["pos"] is None:
            if positionals:
                raise CPkgError(f"{name}: unexpected argument '{positionals[0]}'")
        else:
            pname, arity = spec["pos"]
            if arity == "+" and not positionals:
                raise CPkgError(f"{name}: expected at least one {pname}")
            if arity == 1 and len(positionals) != 1:
                raise CPkgError(f"{name}: expected exactly one {pname}")
            if arity == "?" and len(positionals) > 1:
                raise CPkgError(f"{name}: expected at most one {pname}")
            setattr(
                ns,
                pname,
                (positionals[0] if positionals else None)
                if arity in (1, "?")
                else positionals,
            )

        for o in spec["opts"]:
            raw = getattr(cmd, _attr(o["flags"]))
            if o.get("bool"):
                val = bool(raw.value)
            elif raw:
                val = raw.value
            elif o.get("required"):
                raise CPkgError(f"{name}: {o['flags'][0]} is required")
            else:
                d = o.get("default")
                val = d() if callable(d) else d
            setattr(ns, _attr(o["flags"]), val)
        return ns
    finally:
        argv[:] = saved


def main(args_list: list[str] | None = None) -> int:
    try:
        args = parse_args(args_list)
        args.func(args, _make_store())
        return 0
    except (CPkgError, RegistryError, StoreError) as e:
        _cpkg_errp(str(e))
    except Exception as e:  # pkg_util errors already carry their own colored text
        _cpkg_errp(str(e), skip_hardcoded_exc_mark=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
