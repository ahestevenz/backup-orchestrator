# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Command line: bn-backup <thing> <action> (D-33, CLAUDE.md §6.18)."""

from __future__ import annotations

import argparse
import os
import pwd
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from . import __version__
from .config import AlreadyCurrentError, ConfigError, LoadedConfig, load_config
from .paths import OperatorPaths


class UsageError(Exception):
    """A problem the user can fix; printed without a traceback, exit 1."""


@dataclass
class Context:
    """What every command handler gets: parsed options and the operator's paths."""

    args: argparse.Namespace
    operator: str
    paths: OperatorPaths
    _loaded: LoadedConfig | None = None

    @property
    def config_path(self) -> Path:
        return Path(self.args.config) if self.args.config else self.paths.config

    def loaded(self) -> LoadedConfig:
        if self._loaded is None:
            self._loaded = load_config(self.config_path, home=self.paths.home)
        return self._loaded


Handler = Callable[[Context], int]

# Commands that may run as root (they must, in fact: §6.15).
ROOT_COMMANDS = {("schedule", "install"), ("schedule", "remove")}
# Commands that do not require the current user to be server.receive_user (§6.1).
ANY_USER_COMMANDS = {("server", "init"), ("config", None), ("schedule", None)}


def current_user() -> str:
    return pwd.getpwuid(os.geteuid()).pw_name


# --------------------------------------------------------------------------- handlers


def _config_validate(ctx: Context) -> int:
    ctx.loaded()
    print(f"{ctx.config_path}: valid")
    return 0


def _config_migrate(ctx: Context) -> int:
    from .config import migrate
    from .fsutil import atomic_write_text

    old = Path(ctx.args.old)
    try:
        text = old.read_text(encoding="utf-8")
    except OSError as e:
        raise UsageError(f"{old}: cannot read ({e.strerror})") from e
    new_text, guesses = migrate(text, current_user())
    if ctx.args.output:
        out = Path(ctx.args.output)
        if out.exists():
            raise UsageError(f"{out} already exists; choose another name or delete it first")
        atomic_write_text(out, new_text, 0o600)
        print(f"wrote {out}")
    else:
        sys.stdout.write(new_text)
    print("\nCheck these guesses (marked `# TODO verify` in the file):", file=sys.stderr)
    for g in guesses:
        print(f"  - {g}", file=sys.stderr)
    return 0


def _config_show(ctx: Context) -> int:
    from .config import show

    sys.stdout.write(show(ctx.loaded().config, ctx.args.json))
    return 0


def _not_yet(ctx: Context) -> int:
    raise UsageError("this command is not available in this build yet")


def _lazy(module: str, name: str) -> Handler:
    """Import a command's module only when that command runs."""

    def run(ctx: Context) -> int:
        mod = __import__(f"bn_backup.{module}", fromlist=[name])
        handler: Handler = getattr(mod, name)
        return handler(ctx)

    return run


HANDLERS: dict[tuple[str, str | None], Handler] = {
    ("config", "validate"): _config_validate,
    ("config", "migrate"): _config_migrate,
    ("config", "show"): _config_show,
    ("server", "init"): _lazy("server_init", "cmd_server_init"),
    ("server", "status"): _lazy("status", "cmd_server_status"),
    ("hosts", "list"): _lazy("hosts", "cmd_list"),
    ("hosts", "add"): _lazy("hosts", "cmd_add"),
    ("hosts", "bootstrap"): _lazy("hosts", "cmd_bootstrap"),
    ("hosts", "configure"): _lazy("hosts", "cmd_configure"),
    ("hosts", "remove"): _lazy("hosts", "cmd_remove"),
    ("hosts", "forget"): _lazy("hosts", "cmd_forget"),
    ("agent", "upgrade"): _lazy("hosts", "cmd_agent_upgrade"),
    ("agent", "status"): _lazy("status", "cmd_agent_status"),
    ("status", None): _lazy("status", "cmd_status"),
    ("run", None): _lazy("runner", "cmd_run"),
    ("runs", "list"): _lazy("runs", "cmd_list"),
    ("runs", "show"): _lazy("runs", "cmd_show"),
    ("runs", "cancel"): _lazy("runs", "cmd_cancel"),
    ("schedule", "install"): _lazy("schedule", "cmd_install"),
    ("schedule", "show"): _lazy("schedule", "cmd_show"),
    ("schedule", "remove"): _lazy("schedule", "cmd_remove"),
    ("notify", "test"): _lazy("notify", "cmd_test"),
    ("notify", "set-smtp-password"): _lazy("notify", "cmd_set_smtp_password"),
}


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bn-backup",
        description="bleiben Backup Orchestrator: local backups for photographers.",
    )
    p.add_argument("--version", action="version", version=f"bn-backup {__version__}")
    p.add_argument("-c", "--config", metavar="CONFIG", help="config file to use")
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v debug, -vv trace")
    sub = p.add_subparsers(dest="thing", metavar="COMMAND", required=True)

    def group(name: str, help_: str) -> argparse._SubParsersAction[argparse.ArgumentParser]:
        g = sub.add_parser(name, help=help_)
        return g.add_subparsers(dest="action", metavar="ACTION", required=True)

    def json_flag(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--json", action="store_true", help="machine-readable output")

    def agent_package(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--agent-package", metavar="PATH", help="use a local agent package")

    srv = group("server", "the server itself")
    srv.add_parser("init", help="one-time setup of this server")
    json_flag(srv.add_parser("status", help="server checks only"))

    cfg = group("config", "the configuration file")
    cfg.add_parser("validate", help="check the config and print every problem")
    m = cfg.add_parser("migrate", help="convert a v1 config to the current format")
    m.add_argument("old", metavar="OLD.yml")
    m.add_argument("-o", "--output", metavar="NEW.yml")
    json_flag(cfg.add_parser("show", help="print the config with every default filled in"))

    hosts = group("hosts", "the computers being backed up")
    hosts.add_parser("list", help="hosts and what the server knows about them")
    a = hosts.add_parser("add", help="add a host to the config and set it up")
    a.add_argument("host", metavar="HOST")
    a.add_argument("--address", metavar="A")
    a.add_argument("--admin-user", metavar="U")
    a.add_argument("--ssh-port", metavar="P", type=int)
    a.add_argument("--no-bootstrap", action="store_true")
    agent_package(a)
    b = hosts.add_parser("bootstrap", help="first-time setup of hosts")
    b.add_argument("host", nargs="?", metavar="HOST")
    agent_package(b)
    hosts.add_parser("configure", help="apply users and keys to a host").add_argument(
        "host", nargs="?", metavar="HOST"
    )
    hosts.add_parser("remove", help="uninstall the agent and forget a host").add_argument(
        "host", metavar="HOST"
    )
    hosts.add_parser("forget", help="forget a host on the server side only").add_argument(
        "host", metavar="HOST"
    )

    agent = group("agent", "the agent on each host")
    u = agent.add_parser("upgrade", help="install the agent matching this server")
    u.add_argument("host", nargs="?", metavar="HOST")
    agent_package(u)
    s = agent.add_parser("status", help="host rows of the board")
    s.add_argument("host", nargs="?", metavar="HOST")
    json_flag(s)
    s.add_argument("--no-wake", action="store_true")

    st = sub.add_parser("status", help="the whole board: would a backup start and succeed?")
    json_flag(st)
    st.add_argument("--no-wake", action="store_true")

    r = sub.add_parser("run", help="run a backup")
    r.add_argument("--dry-run", action="store_true", help="change nothing; report what would run")
    r.add_argument("--fresh", action="store_true", help="discard staged work and start over")
    r.add_argument("--no-wake", action="store_true", help="do not wake sleeping hosts")

    runs = group("runs", "past and current runs")
    ls = runs.add_parser("list", help="past runs, newest first")
    ls.add_argument("--limit", type=int, default=20, metavar="N")
    json_flag(ls)
    sh = runs.add_parser("show", help="one run in detail")
    sh.add_argument("run_id", metavar="RUN_ID")
    json_flag(sh)
    runs.add_parser("cancel", help="stop the run in progress")

    sched = group("schedule", "scheduled runs")
    si = sched.add_parser("install", help="install the schedule (needs sudo)")
    when = si.add_mutually_exclusive_group(required=True)
    when.add_argument(
        "--weekly",
        metavar="DAY",
        choices=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    )
    when.add_argument("--daily", action="store_true")
    si.add_argument("--at", required=True, metavar="HH:MM")
    sched.add_parser("show", help="print the schedule")
    sched.add_parser("remove", help="remove the schedule (needs sudo)")

    notify = group("notify", "email and Signal notifications")
    notify.add_parser("test", help="send a test message on every enabled channel")
    notify.add_parser("set-smtp-password", help="store the email app password")
    return p


# --------------------------------------------------------------------------- main


def setup_logging(verbose: int, log_file: Path | None) -> None:
    logger.remove()
    level = {0: "INFO", 1: "DEBUG"}.get(verbose, "TRACE")
    logger.add(sys.stderr, level=level, format="<level>{message}</level>", colorize=None)
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            logger.add(
                log_file,
                level="DEBUG" if verbose else "INFO",
                rotation="10 MB",
                retention=5,
                format="{time:YYYY-MM-DD HH:mm:ss} {level: <7} {message}",
            )
        except OSError:
            logger.warning(f"cannot write the log file {log_file}")


def operator_home(user: str) -> Path:
    return Path(pwd.getpwnam(user).pw_dir)


def check_account(ctx: Context, key: tuple[str, str | None]) -> None:
    """Who may run what (§6.1)."""
    is_root = os.geteuid() == 0
    if key in ROOT_COMMANDS:
        return  # the schedule commands check sudo themselves
    if is_root:
        raise UsageError("run bn-backup as your own account, without sudo")
    if key in ANY_USER_COMMANDS or (key[0], None) in ANY_USER_COMMANDS:
        return
    receive_user = ctx.loaded().config.server.receive_user
    if ctx.operator != receive_user:
        raise UsageError(
            f"run bn-backup as {receive_user} (server.receive_user in the config), "
            f"not as {ctx.operator}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    key = (args.thing, getattr(args, "action", None))
    operator = current_user()
    # Under sudo (schedule install/remove) the operator is the user who ran sudo.
    if os.geteuid() == 0 and key in ROOT_COMMANDS and os.environ.get("SUDO_USER"):
        operator = os.environ["SUDO_USER"]
    paths = OperatorPaths(home=operator_home(operator))
    setup_logging(args.verbose, None if os.geteuid() == 0 else paths.log_file)
    ctx = Context(args=args, operator=operator, paths=paths)
    handler = HANDLERS.get(key, _not_yet)
    try:
        check_account(ctx, key)
        return handler(ctx)
    except AlreadyCurrentError as e:
        print(e.errors[0], file=sys.stderr)
        return 1
    except ConfigError as e:
        print(f"{ctx.config_path}: invalid configuration:", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    except UsageError as e:
        print(f"bn-backup: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
