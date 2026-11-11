# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""`hosts list/add/bootstrap/configure/remove/forget` and `agent upgrade` (CLAUDE.md §6.6).

Installing, upgrading and removing agents use the operator connection (the
operator's own login and password); everything else uses the control key.
"""

from __future__ import annotations

import contextlib
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from .agentctl import Agent, CtlError, TransportError
from .config import HOST_KEY_RE, ConfigError, check_address
from .env import Env
from .fsutil import ensure_dir
from .keys import forget_keys, regenerate, store_key
from .releases import ReleaseError, get_package
from .state import HostRecord, MacAddress, known_hosts, load_host, lock_holder, save_host

MACOS_AGENT = "/Applications/BNBackupAgent.app/Contents/MacOS/bn-backup-agent"
LINUX_AGENT = "/usr/bin/bn-backup-agent"
FDA_POLL_SECONDS = 15
FDA_WAIT_SECONDS = 30 * 60

Say = Callable[[str], None]


class HostError(Exception):
    """A host step failed; the message says what to do."""


def agent_path(os_name: str | None) -> str:
    return MACOS_AGENT if os_name == "darwin" else LINUX_AGENT


def known_hosts_line(env: Env) -> str:
    """The server's SSH host key as seen by agents: `<ssh_host> <type> <key>` (§6.6 step 5)."""
    try:
        kind, key = env.server_host_key.read_text(encoding="utf-8").split()[:2]
    except (OSError, ValueError) as e:
        raise HostError(f"cannot read the server's host key {env.server_host_key}: {e}") from e
    host = env.cfg.server.ssh_host
    port = env.cfg.server.ssh_port
    name = host if port == 22 else f"[{host}]:{port}"
    return f"{name} {kind} {key}"


def _record(env: Env, host: str) -> HostRecord:
    t = env.target(host)
    rec = load_host(env.paths, host) or HostRecord(
        host=host, address=t.address, ssh_port=t.ssh_port, admin_user=t.admin_user
    )
    # Bootstrap, configure and upgrade refresh these, so remove works later.
    rec.address, rec.ssh_port, rec.admin_user = t.address, t.ssh_port, t.admin_user
    return rec


# --------------------------------------------------------------------------- steps


def detect_os(env: Env, rec: HostRecord, say: Say) -> None:
    t = env.target(rec.host)
    rc, out = env.operator_conn.capture(t, "uname -s; uname -m", first_contact=True)
    lines = out.split()
    if rc != 0 or len(lines) < 2:
        raise HostError(f"could not log in to {t.login} to detect the OS")
    rec.os = {"Darwin": "darwin", "Linux": "linux"}.get(lines[0])
    if rec.os is None:
        raise HostError(f"{rec.host} runs {lines[0]}, which is not supported")
    rec.arch = lines[1]
    save_host(env.paths, rec)
    say(f"{rec.host}: {lines[0]} {rec.arch}")


def check_users(env: Env, rec: HostRecord) -> None:
    t = env.target(rec.host)
    for user in env.cfg.users_on(rec.host):
        rc, _ = env.operator_conn.capture(t, f"id -u {shlex.quote(user)}")
        if rc != 0:
            raise HostError(f"there is no account {user!r} on {rec.host}; fix the config")


def install_agent(env: Env, rec: HostRecord, override: Path | None, say: Say) -> None:
    t = env.target(rec.host)
    try:
        pkg = get_package(
            env.version,
            rec.os or "",
            rec.arch or "",
            env.operator_paths.release_cache,
            override,
        )
    except ReleaseError as e:
        raise HostError(str(e)) from e
    say(f"{rec.host}: installing {pkg.name} (you may be asked for {t.admin_user}'s password)")
    if rec.os == "linux":
        remote = f"/tmp/{pkg.name}"
        if env.operator_conn.copy(t, pkg, remote) != 0:
            raise HostError(f"could not copy {pkg.name} to {rec.host}")
        q = shlex.quote(remote)
        cmd = f"sudo apt-get install -y {q}; rc=$?; rm -f {q}; exit $rc"
    else:
        remote = f"/Users/Shared/{pkg.name}"
        if env.operator_conn.copy(t, pkg, remote) != 0:
            raise HostError(f"could not copy {pkg.name} to {rec.host}")
        cmd = f"sudo installer -pkg {shlex.quote(remote)} -target /"
    if env.operator_conn.run(t, cmd) != 0:
        raise HostError(f"installing the agent on {rec.host} failed")
    rec.installed_version = env.version
    save_host(env.paths, rec)


def setup_agent(env: Env, rec: HostRecord, say: Say) -> None:
    t = env.target(rec.host)
    cfg = env.cfg
    control_pub = env.operator_paths.control_key_pub.read_text(encoding="utf-8").strip()
    cmd = shlex.join(
        [
            "sudo",
            agent_path(rec.os),
            "ctl",
            "setup",
            "--host-name",
            rec.host,
            "--server-host",
            cfg.server.ssh_host,
            "--server-port",
            str(cfg.server.ssh_port),
            "--server-user",
            cfg.server.receive_user,
            "--server-known-hosts-line",
            known_hosts_line(env),
            "--admin-user",
            t.admin_user,
            "--control-key",
            control_pub,
        ]
    )
    say(f"{rec.host}: setting up the agent")
    if env.operator_conn.run(t, cmd) != 0:
        raise HostError(f"ctl setup failed on {rec.host}")
    rec.setup_done = True
    save_host(env.paths, rec)


def configure(env: Env, host: str, say: Say = print) -> list[str]:
    """Set up every user of this host's modules (§6.6 configure). Returns the users added."""
    agent = env.agent(host)
    try:
        info = agent.info()
    except (CtlError, TransportError) as e:
        raise HostError(
            f"{host}: the agent does not answer ({e}); run bn-backup hosts bootstrap {host}"
        ) from e
    added = []
    for user in env.cfg.users_on(host):
        if user not in info.users or not env.paths.key_file(host, user).exists():
            try:
                key = agent.user_add(user)
            except (CtlError, TransportError) as e:
                raise HostError(f"{host}: could not set up {user}: {e}") from e
            store_key(env.paths, host, user, key)
            added.append(user)
            say(f"{host}: set up {user}")
        ensure_dir(env.paths.staging_user(host, user), 0o700)
    regenerate(env.paths, env.operator_paths.authorized_keys, env.operator_paths.rrsync)
    rec = _record(env, host)
    save_host(env.paths, rec)
    return added


def fda_flow(env: Env, host: str, agent: Agent, say: Say) -> None:
    """macOS: wait until someone at the Mac switches on Full Disk Access (§6.6 step 8)."""
    from .status import probe_result

    users = env.cfg.users_on(host)
    if not users:
        return
    result, _ = probe_result(env, agent, host, users[0])
    if result is not None and result.get("fda") == "granted":
        return
    with contextlib.suppress(CtlError, TransportError):
        agent.open_fda_settings()
    say(
        f"Go to {host} and switch on BNBackupAgent in System Settings → Privacy & Security → "
        "Full Disk Access"
    )
    waited = 0
    while waited < FDA_WAIT_SECONDS:
        env.clock.sleep(FDA_POLL_SECONDS)
        waited += FDA_POLL_SECONDS
        result, _ = probe_result(env, agent, host, users[0])
        if result is not None and result.get("fda") == "granted":
            say(f"{host}: Full Disk Access granted")
            return
    raise HostError(
        f"{host}: Full Disk Access was not switched on within 30 minutes; "
        f"run bn-backup hosts bootstrap {host} again when it is"
    )


def store_info(env: Env, rec: HostRecord, agent: Agent) -> None:
    info = agent.info()
    rec.mac_addresses = [MacAddress.model_validate(m.model_dump()) for m in info.mac_addresses]
    rec.agent_version = info.agent_version
    rec.rsync_version = info.rsync_version
    rec.os = info.os
    save_host(env.paths, rec)


def _installed_and_current(env: Env, rec: HostRecord, agent: Agent) -> bool:
    if not rec.setup_done:
        return False
    try:
        agent.ping()
        info = agent.info()
    except (CtlError, TransportError):
        return False
    return info.configured and info.agent_version == env.version


def bootstrap(env: Env, host: str, override: Path | None = None, say: Say = print) -> bool:
    """First-time setup of one host (§6.6 steps 1-10). Safe to re-run."""
    from .status import host_rows, render_rows

    t = env.target(host)
    if not env.resolves(t.address) or not env.reachable(t.address, t.ssh_port, 10.0):
        raise HostError(f"{host}: {t.address} does not resolve or its SSH port does not answer")
    rec = _record(env, host)
    save_host(env.paths, rec)
    if not rec.os:
        detect_os(env, rec, say)
    check_users(env, rec)
    agent = env.agent(host)
    if not _installed_and_current(env, rec, agent):
        install_agent(env, rec, override, say)
        setup_agent(env, rec, say)
    try:
        agent.ping()
    except (CtlError, TransportError) as e:
        raise HostError(f"{host}: the control key does not work ({e})") from e
    configure(env, host, say)
    if rec.os == "darwin":
        fda_flow(env, host, agent, say)
    store_info(env, rec, agent)
    rec.bootstrapped = True
    save_host(env.paths, rec)
    rows = host_rows(env, host, env.cfg.users_on(host), wake=False, gate=False)
    say(render_rows(rows))
    return all(r.ok for r in rows)


def upgrade(env: Env, host: str, override: Path | None = None, say: Say = print) -> bool:
    """`agent upgrade`: bootstrap steps 4, 5, 6, then 8 only if needed, then 9 (§6.6)."""
    from .status import probe_result

    rec = _record(env, host)
    if not rec.os:
        detect_os(env, rec, say)
    install_agent(env, rec, override, say)
    setup_agent(env, rec, say)
    agent = env.agent(host)
    try:
        agent.ping()
    except (CtlError, TransportError) as e:
        raise HostError(f"{host}: the control key does not work ({e})") from e
    if rec.os == "darwin":
        users = env.cfg.users_on(host)
        if users:
            result, _ = probe_result(env, agent, host, users[0])
            if result is None or result.get("fda") != "granted":
                # D-07: every new macOS build loses the grant.
                fda_flow(env, host, agent, say)
    store_info(env, rec, agent)
    return True


def forget(env: Env, host: str) -> None:
    forget_keys(env.paths, host)
    regenerate(env.paths, env.operator_paths.authorized_keys, env.operator_paths.rrsync)
    record = env.paths.host_record(host)
    if record.exists():
        record.unlink()


def remove(env: Env, host: str, say: Say = print) -> None:
    """Uninstall the agent, then forget the host (§6.6 remove, D-35)."""
    if host in env.cfg.hosts:
        raise HostError(f"{host} is still in the config; remove it from the config first")
    if lock_holder(env.operator_paths.lock) is not None:
        raise HostError("a run is in progress; try again when it has finished")
    rec = load_host(env.paths, host)
    if rec is None:
        raise HostError(f"{host}: unknown host; nothing to remove")
    t = env.target(host)
    if not env.reachable(t.address, t.ssh_port, 10.0):
        raise HostError(
            f"{host} is unreachable; use `bn-backup hosts forget {host}` to clean up only the "
            "server side"
        )
    say(f"{host}: uninstalling the agent (you may be asked for {t.admin_user}'s password)")
    cmd = shlex.join(["sudo", agent_path(rec.os), "ctl", "uninstall"])
    if env.operator_conn.run(t, cmd) != 0:
        raise HostError(f"ctl uninstall failed on {host}")
    if (
        rec.os == "linux"
        and env.operator_conn.run(t, "sudo apt-get remove -y bn-backup-agent") != 0
    ):
        raise HostError(f"apt-get remove failed on {host}")
    forget(env, host)


# --------------------------------------------------------------------------- commands


def _env(ctx: Any) -> Env:
    return Env(loaded=ctx.loaded(), operator_paths=ctx.paths, operator=ctx.operator)


def _override(ctx: Any) -> Path | None:
    p = getattr(ctx.args, "agent_package", None)
    return Path(p) if p else None


def _each(hosts: list[str], action: Callable[[str], bool]) -> int:
    failed = False
    for h in hosts:
        try:
            failed |= not action(h)
        except HostError as e:
            print(f"bn-backup: {e}", file=sys.stderr)
            failed = True
    return 2 if failed else 0


def cmd_list(ctx: Any) -> int:
    env = _env(ctx)
    names = sorted(set(env.cfg.hosts) | set(known_hosts(env.paths)))
    print(f"{'HOST':<16} {'ADDRESS':<28} {'OS/ARCH':<16} {'AGENT':<8} {'BOOTSTRAPPED':<13} USERS")
    for h in names:
        rec = load_host(env.paths, h)
        in_cfg = h in env.cfg.hosts
        address = env.target(h).address
        osarch = f"{rec.os}/{rec.arch}" if rec and rec.os else "–"
        users = ", ".join(env.cfg.users_on(h)) if in_cfg else "(not in config)"
        print(
            f"{h:<16} {address:<28} {osarch:<16} {(rec.agent_version if rec else None) or '–':<8} "
            f"{'yes' if rec and rec.bootstrapped else 'no':<13} {users}"
        )
    return 0


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def cmd_add(ctx: Any) -> int:
    from .config_edit import add_host

    a = ctx.args
    cfg = ctx.loaded().config
    if not HOST_KEY_RE.match(a.host):
        print(f"bn-backup: {a.host!r} is not a valid host key (lower-case letters, digits, '-')")
        return 1
    if a.host in cfg.hosts:
        print(f"bn-backup: {a.host} is already in the config")
        return 1
    address = a.address or _ask("Address (for example galactica.home.lan)")
    try:
        check_address(address)
    except ValueError as e:
        print(f"bn-backup: {e}")
        return 1
    admin = a.admin_user or _ask("Admin account on that host")
    port = a.ssh_port or int(_ask("SSH port", "22"))
    try:
        add_host(ctx.config_path, a.host, address, admin, port, home=ctx.paths.home)
    except ConfigError as e:
        print("bn-backup: the config would become invalid; nothing was changed:")
        for err in e.errors:
            print(f"  - {err}")
        return 1
    print(f"added {a.host} to {ctx.config_path}")
    ctx._loaded = None
    if not a.no_bootstrap:
        env = _env(ctx)
        rc = _each([a.host], lambda h: bootstrap(env, h, _override(ctx)))
    else:
        rc = 0
    print(f"Add the modules for {a.host} to the config (hosts: … modules: …).")
    return rc


def cmd_bootstrap(ctx: Any) -> int:
    env = _env(ctx)
    if ctx.args.host:
        if ctx.args.host not in env.cfg.hosts:
            print(f"bn-backup: {ctx.args.host} is not in the config")
            return 1
        hosts = [ctx.args.host]
    else:
        hosts = [
            h for h in env.cfg.hosts if not ((rec := load_host(env.paths, h)) and rec.bootstrapped)
        ]
        if not hosts:
            print("Every host in the config is already set up.")
            return 0
    return _each(hosts, lambda h: bootstrap(env, h, _override(ctx)))


def cmd_configure(ctx: Any) -> int:
    env = _env(ctx)
    hosts = [ctx.args.host] if ctx.args.host else sorted(env.cfg.hosts)

    def one(h: str) -> bool:
        configure(env, h)
        return True

    return _each(hosts, one)


def cmd_remove(ctx: Any) -> int:
    env = _env(ctx)

    def one(h: str) -> bool:
        remove(env, h)
        print(f"removed {h}")
        return True

    rc = _each([ctx.args.host], one)
    return 1 if rc else 0


def cmd_forget(ctx: Any) -> int:
    env = _env(ctx)
    forget(env, ctx.args.host)
    print(f"forgot {ctx.args.host} on the server side (the host itself was not touched)")
    return 0


def cmd_agent_upgrade(ctx: Any) -> int:
    env = _env(ctx)
    hosts = [ctx.args.host] if ctx.args.host else sorted(env.cfg.hosts)
    logger.info(f"upgrading the agent on {', '.join(hosts)} to {env.version}")
    return _each(hosts, lambda h: upgrade(env, h, _override(ctx)))
