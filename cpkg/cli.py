from .utils.color import Color
from .utils.pkg_dests_util import host_arch_name, host_os_name
from .utils.pkg_util import (
    Generate,
    Unpack,
    parse_pkg_filename,
)
from .utils.depends_parser_util import DependsParser
from .utils.registry_util import Registry, RegistryError, version_satisfies
from .utils.store_util import Store, StoreError
from .nice_output_helper import NiceOutputs
from .backend_helper import get_registry, make_store
from . import server_helper as sh
from . import __version__
from arghandle import ArgHandle
from types import SimpleNamespace
from dataclasses import dataclass, field
from pathlib import Path
from os import chdir, environ, getcwd
from os.path import realpath
import re
import signal
from sys import stderr, stdout, argv
from subprocess import run

try:  # autobuild.py next to cli.py (inside the cpkg package)...
    from .autobuild import Tokenize, Parser, Optimizer, Executor
    from . import autobuild as _ab  # _ab._expand_includes / _parse_cli_vars / _CLI_PROFILE
except ImportError:  # ...or installed / on PYTHONPATH as a top-level module
    from autobuild import Tokenize, Parser, Optimizer, Executor
    import autobuild as _ab

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


# ----------------------------------------------------------------------------- build
@dataclass
class BuildOptions:
    """What the user asked for on the command line.

    recipes: .abuild -> recipe names to run; Makefile -> make targets
    vars:    raw NAME[=VALUE] specs; .abuild -> typed CLI vars, Makefile -> NAME=VALUE
    """

    recipes: list[str] = field(default_factory=list)
    vars: list[str] = field(default_factory=list)


_VAR_SPEC_RE = re.compile(r"[A-Za-z_]\w*(=.*)?", re.S)


def _check_build_vars(specs: list[str]) -> None:
    for spec in specs:
        if not _VAR_SPEC_RE.fullmatch(spec):
            raise CPkgError(f"Invalid --var '{spec}' (expected NAME=VALUE)")


def _var_argv(specs: list[str]) -> list[str]:
    return [tok for spec in specs for tok in ("--var", spec)]


def _make_assign(spec: str) -> str:
    return spec if "=" in spec else f"{spec}=true"  # bare NAME == true, like autobuild


def _build_autobuild(abuild: Path, opts: BuildOptions, name: str) -> None:
    """Run the package's .abuild with autobuild's engine (in-process)."""
    src_dir = abuild.parent
    cli_vars = _ab._parse_cli_vars(_var_argv(opts.vars))

    # The engine is cwd-relative (.abuild, .abuild.cache, include "..."), and its
    # flag()/option()/args()/getargv() read sys.argv - so point both at the package
    # for the duration of the build instead of leaking cpkg's own command line.
    saved_cwd, saved_argv, saved_profile = getcwd(), argv[:], _ab._CLI_PROFILE
    chdir(src_dir)
    argv[:] = [saved_argv[0], *opts.recipes, *_var_argv(opts.vars)]
    _ab._CLI_PROFILE = cli_vars.get("profile")  # templates read --profile from here
    try:
        try:
            source = _ab._expand_includes(
                abuild.read_text(encoding="utf-8"), str(src_dir), [realpath(abuild)]
            )
            ast = Parser(Tokenize(source).GetTokens()).GetAST()
            ast = Optimizer(ast, cli_vars=cli_vars).GetAST()
            # Building the Executor runs the file's top-level statements and
            # registers its recipes.
            ex = Executor(ast, cli_vars=cli_vars)

            recipes = opts.recipes or ([ex.default_recipe] if ex.default_recipe else [])
            available = ", ".join(sorted(ex.recipes_declared)) or "(none)"
            if not recipes:
                raise CPkgError(
                    f"{name}: .abuild has no default() recipe; "
                    f"pick one with --recipe (available: {available})"
                )
            for r in recipes:
                if r not in ex.recipes_declared:
                    raise CPkgError(
                        f"{name}: unknown recipe '{r}' (available: {available})"
                    )
            for r in recipes:
                ex.RunRecipe(r)
            ex.commit_cache()  # digests recorded by top-level changed()
        except CPkgError:
            raise
        except (SystemExit, Exception) as e:
            # the engine reports its failures via SystemExit
            raise CPkgError(f"{name}: autobuild failed: {e}") from e
    finally:
        chdir(saved_cwd)
        argv[:] = saved_argv
        _ab._CLI_PROFILE = saved_profile


def _build_make(makefile: Path, opts: BuildOptions, name: str) -> None:
    """Run the package's Makefile with make (opts.recipes = targets)."""
    cmd = [
        "make",
        "-f",
        makefile.name,
        *opts.recipes,
        *(_make_assign(v) for v in opts.vars),
    ]
    try:
        res = run(cmd, cwd=makefile.parent)
    except FileNotFoundError:
        raise CPkgError(f"{name}: 'make' was not found on PATH")
    if res.returncode != 0:
        raise CPkgError(
            f"{name}: '{' '.join(cmd)}' failed with exit code {res.returncode}"
        )


# ----------------------------------------------------------------------------- install
def _install_from_file(
    store: Store,
    pkg_file: Path,
    seen: set,
    reg_getter,
    build: BuildOptions | None = None,
) -> str:
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

    build_file = (
        Path(dest / "src" / "Makefile")
        if Path(dest / "src" / "Makefile").exists()
        else (
            Path(dest / "src" / ".abuild")
            if Path(dest / "src" / ".abuild").exists()
            else None
        )
    )
    AB_BUILD = False
    MK_BUILD = False

    if not build_file:
        pass
    else:
        if build_file.name == ".abuild":
            AB_BUILD = True
        elif build_file.name.lower() == "makefile":
            MK_BUILD = True

    # dependencies first, so the build can rely on them being installed.
    # (--recipe / --var only apply to the packages named on the command line;
    # dependencies are built with their own default recipe.)
    dep_names = []
    dep_file = dest / "DEPENDENCIES"
    if dep_file.exists():
        for dname, op, dver in DependsParser(dep_file).parse():
            dep_names.append(dname)
            _install_spec(store, dname, op, dver, seen, reg_getter)

    if AB_BUILD or MK_BUILD:
        try:
            if AB_BUILD:
                _build_autobuild(build_file, build or BuildOptions(), name)
            else:
                _build_make(build_file, build or BuildOptions(), name)
        except BaseException:  # failed build (or Ctrl+C): leave nothing half-installed
            store.wipe_pkg_dir(name)
            raise

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


def _install_spec(
    store: Store,
    name: str,
    op: str,
    ver: str,
    seen: set,
    reg_getter,
    build: BuildOptions | None = None,
):
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
    _install_from_file(store, pkg_file, seen, reg_getter, build)


def cmd_install(args, store: Store):
    parser = DependsParser()
    seen: set = set()
    _reg = {}
    _check_build_vars(args.var)  # fail before downloading anything
    build = BuildOptions(recipes=list(args.recipe), vars=list(args.var))

    def reg_getter() -> Registry:
        if "r" not in _reg:
            _reg["r"] = get_registry(store, args.registry)
        return _reg["r"]

    total = len(args.packages)
    for i, spec in enumerate(args.packages, 1):
        p = Path(spec)
        if spec.lower().endswith(".pkg") and p.is_file():
            _install_from_file(store, p, seen, reg_getter, build)
        else:
            parsed = parser.parse_line(spec)
            if not parsed:
                raise CPkgError(f"Invalid package spec '{spec}'")
            _install_spec(store, *parsed, seen, reg_getter, build)
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
    reg = get_registry(store, args.registry)
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


def raise_exit():
    raise SystemExit(0)


def cmd_create_server(args, store: Store):
    cfg = sh.ServerConfig(force=args.force)
    given = set()
    if args.type:
        cfg.mode = args.type.lower()
        given.add("mode")
    if args.name:
        cfg.name = args.name
        given.add("name")
    if args.dir:
        cfg.dir = Path(args.dir)
        given.add("dir")
    if args.host:
        cfg.host = args.host
        given.add("host")
    if args.port:
        try:
            cfg.port = sh.parse_port(args.port, allow_zero=True)
        except sh.ServerSetupError as e:
            raise CPkgError(str(e))
        given.add("port")
    if args.url:
        cfg.url = args.url
        given.add("url")
    if args.seed:
        cfg.seed = Path(args.seed)
        given.add("seed")
    if args.start:
        cfg.start = True
        given.add("start")
    if args.no_registry:
        cfg.set_registry = False
        given.add("set_registry")

    if cfg.mode not in sh.MODES:
        raise CPkgError(f"unknown type '{cfg.mode}' (use {', '.join(sh.MODES)})")

    interactive = not sh.is_noninteractive(args.yes)
    try:
        if interactive:
            sh.fill_interactively(cfg, given)
        sh.resolve_defaults(cfg)
        if cfg.mode != "ghost" and cfg.start and sh.port_in_use(cfg.host, cfg.port):
            raise CPkgError(f"port {cfg.port} is already in use")
        root = sh.scaffold(cfg)
    except sh.ServerSetupError as e:
        raise CPkgError(str(e))

    url = sh.public_url(cfg)
    for note in cfg.notes:
        _cpkg_warnp(note)

    if cfg.mode == "ghost":
        gh_env = environ.get("GITHUB_ENV")
        if gh_env:
            with open(gh_env, "a", encoding="utf-8") as f:
                f.write(f"CPKG_REG_URL={url}\n")
        print(f"{c.GREEN}Ghost server at {url}{c.RESET}  (CPKG_REG_URL={url})")
        print("Ctrl+C to stop; the folder is deleted on exit.")
        signal.signal(signal.SIGTERM, lambda *_: raise_exit())
        try:
            sh.run_server(root, cfg.host, cfg.port)
        finally:
            sh.remove_ghost(root)
        return

    print(f"{c.GREEN}{c.BOLD}Created {cfg.mode} server '{cfg.name}' in {root}{c.RESET}")
    print(
        f"Drop .pkg files into {root / 'registry'}; index.json is rebuilt on every request."
    )
    if cfg.set_registry:
        store.set_registry(url)
        print(f"{c.GREEN}Registry set to {url}{c.RESET}")
    if cfg.mode == "professional":
        print(
            "Also written: Dockerfile and a systemd unit. Set the public URL in clients with"
        )
        print(f"  cpkg registry {url}")
    if cfg.start:
        print(f"Starting on {url} (Ctrl+C to stop)")
        sh.run_server(root, cfg.host, cfg.port)
    else:
        print(f"Start it with: python {root / 'serve.py'}")


def _commands() -> dict[str, dict]:
    """Command table. pos: None | "?" (optional) | "+" (1+) | 1 (exactly one)."""
    return {
        "install": dict(
            help="install packages (name, name==1.0, or a local .pkg)",
            func=cmd_install,
            pos=("packages", "+"),
            opts=[
                dict(flags=["--registry"], help="registry url or local folder"),
                dict(
                    flags=["--recipe"],
                    help="recipe to build (.abuild) / target (Makefile); repeatable",
                    multi=True,
                ),
                dict(
                    flags=["--var", "-D"],
                    help="build variable NAME=VALUE (.abuild var / make var); repeatable",
                    multi=True,
                ),
            ],
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
        "create-server": dict(
            help="create a registry server (local, professional or ghost); "
            "prompts on a TTY, fully flag-driven with --yes / in CI",
            func=cmd_create_server,
            pos=("dir", "?"),
            opts=[
                dict(flags=["--type"], help="local | professional | ghost"),
                dict(flags=["--name"], help="server name (default cpkg-registry)"),
                dict(flags=["--host"], help="bind address"),
                dict(
                    flags=["--port"], help="port (ghost: 0 or unset = random free port)"
                ),
                dict(flags=["--url"], help="public url (professional)"),
                dict(flags=["--seed"], help="folder of .pkg files to publish"),
                dict(
                    flags=["--start"],
                    help="start the server after creating it",
                    bool=True,
                ),
                dict(
                    flags=["--no-registry"],
                    help="do not set it as the active registry",
                    bool=True,
                ),
                dict(
                    flags=["--force"], help="write into a non-empty folder", bool=True
                ),
                dict(
                    flags=["--yes", "-y"], help="never prompt, use defaults", bool=True
                ),
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
        multi = {
            f: _attr(o["flags"])
            for o in spec["opts"]
            if o.get("multi")
            for f in o["flags"]
        }
        # repeatable flags: every value, in order
        multi_vals = {a: [] for a in multi.values()}
        toks, positionals, i = cmd.args[1:], [], 0
        while i < len(toks):
            t = toks[i]
            if t.startswith("-") and len(t) > 1:
                if t not in known:
                    raise CPkgError(f"{name}: unknown option '{t}'")
                if t in valued:
                    if i + 1 >= len(toks) or toks[i + 1].startswith("-"):
                        raise CPkgError(f"{name}: '{t}' expects a value")
                    if t in multi:
                        multi_vals[multi[t]].append(toks[i + 1])
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
            if o.get("multi"):
                setattr(ns, _attr(o["flags"]), multi_vals[_attr(o["flags"])])
                continue
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
        args.func(args, make_store())
        return 0
    except (CPkgError, RegistryError, StoreError) as e:
        _cpkg_errp(str(e))
    except Exception as e:  # pkg_util errors already carry their own colored text
        _cpkg_errp(str(e), skip_hardcoded_exc_mark=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())