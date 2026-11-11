# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""The configuration file: models, loading, validation, migration (CLAUDE.md §4).

The file is the only thing the operator edits by hand. Everything the server
learns about hosts lives under .state/, never here.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

CONFIG_VERSION = 2

HOST_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,31}$")
E164_RE = re.compile(r"^\+[1-9][0-9]{6,14}$")
_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
RESERVED_MODULE_NAMES = frozenset({"config.yml", "backup_report.log"})

ADDRESS_HELP = (
    "use a fully qualified name such as galactica.home.lan, a .local name such as "
    "galactica.local, or an IP address (D-18)"
)


class ConfigError(Exception):
    """The config file is missing, unreadable or invalid. Carries every problem found."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class AlreadyCurrentError(ConfigError):
    pass


# --------------------------------------------------------------------------- helpers


def check_address(value: str) -> str:
    """FQDN or .local name (must contain a dot), or an IP literal (D-18)."""
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if "." not in value:
        raise ValueError(f"{value!r} is a bare host name; {ADDRESS_HELP}")
    name = value[:-1] if value.endswith(".") else value
    if len(name) > 253 or not all(_LABEL_RE.match(label) for label in name.split(".")):
        raise ValueError(f"{value!r} is not a valid host name")
    return value


def _check_user(value: str) -> str:
    if not USER_RE.match(value):
        raise ValueError(f"{value!r} is not a valid account name")
    return value


def _expand(value: Any, info: ValidationInfo) -> Any:
    """Expand a leading ~ against the home of the account running the server."""
    if isinstance(value, str) and (value == "~" or value.startswith("~/")):
        home = (info.context or {}).get("home") or Path.home()
        return str(Path(home) / value[2:]) if value != "~" else str(home)
    return value


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --------------------------------------------------------------------------- models


class ServerSection(_Model):
    backup_directory: Path
    ssh_host: str
    ssh_port: int = Field(22, ge=1, le=65535)
    receive_user: str

    _expand_dir = field_validator("backup_directory", mode="before")(_expand)

    @field_validator("backup_directory")
    @classmethod
    def _absolute(cls, v: Path) -> Path:
        if not v.is_absolute() or v == Path("/"):
            raise ValueError("must be an absolute path (and not /)")
        return v

    @field_validator("ssh_host")
    @classmethod
    def _host(cls, v: str) -> str:
        return check_address(v)

    @field_validator("receive_user")
    @classmethod
    def _user(cls, v: str) -> str:
        return _check_user(v)


class WakeSettings(_Model):
    enabled: bool = True
    wait_seconds: int = Field(180, ge=0)


class Settings(_Model):
    mode: Literal["mirror", "snapshot"] = "mirror"
    snapshot_keep: int = Field(8, ge=1)
    verify_backup: bool = False
    resume_backup: bool = True
    dry_run: bool = False
    host_config_backup: bool = True
    unfinished_ttl_hours: int = Field(30, ge=1)
    max_parallel_hosts: int = Field(2, ge=1)
    job_timeout_minutes: int = Field(0, ge=0)
    io_timeout_seconds: int = Field(600, ge=30)
    min_free_gb: int = Field(50, ge=0)
    wake: WakeSettings = Field(default_factory=WakeSettings)


class EmailConfig(_Model):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = Field(587, ge=1, le=65535)
    starttls: bool = True
    username: str = ""
    password_file: Path | None = None
    from_: str = Field("", alias="from")
    to: list[str] = Field(default_factory=list)

    _expand_pw = field_validator("password_file", mode="before")(_expand)

    @model_validator(mode="after")
    def _when_enabled(self) -> EmailConfig:
        if not self.enabled:
            return self
        problems = []
        if not self.smtp_host:
            problems.append("smtp_host is required when email is enabled")
        if not self.from_:
            problems.append("from is required when email is enabled")
        if not self.to:
            problems.append("to needs at least one address when email is enabled")
        if self.password_file is None:
            problems.append("password_file is required when email is enabled")
        elif not self.password_file.is_file():
            problems.append(
                f"password_file {self.password_file} does not exist; "
                "create it with: bn-backup notify set-smtp-password"
            )
        elif stat.S_IMODE(self.password_file.stat().st_mode) != 0o600:
            problems.append(f"password_file {self.password_file} must have mode 0600")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class SignalConfig(_Model):
    enabled: bool = False
    signal_cli: Path = Path("/opt/homebrew/bin/signal-cli")
    account: str = ""
    note_to_self: bool = True
    recipients: list[str] = Field(default_factory=list)

    _expand_cli = field_validator("signal_cli", mode="before")(_expand)

    @field_validator("recipients")
    @classmethod
    def _numbers(cls, v: list[str]) -> list[str]:
        for n in v:
            if not E164_RE.match(n):
                raise ValueError(f"{n!r} is not an E.164 phone number such as +61400000000")
        return v

    @model_validator(mode="after")
    def _when_enabled(self) -> SignalConfig:
        if not self.enabled:
            return self
        if not E164_RE.match(self.account):
            raise ValueError("account must be an E.164 phone number such as +61400000000")
        if not self.note_to_self and not self.recipients:
            raise ValueError("enable note_to_self or list at least one recipient")
        return self


class Notifications(_Model):
    email: EmailConfig = Field(default_factory=EmailConfig)
    signal: SignalConfig = Field(default_factory=SignalConfig)


class HostConfig(_Model):
    address: str
    admin_user: str
    ssh_port: int = Field(22, ge=1, le=65535)

    @field_validator("address")
    @classmethod
    def _address(cls, v: str) -> str:
        return check_address(v)

    @field_validator("admin_user")
    @classmethod
    def _user(cls, v: str) -> str:
        return _check_user(v)


class ModuleConfig(_Model):
    host: str
    user: str
    src_path: str
    excludes: list[str] = Field(default_factory=list)

    @field_validator("user")
    @classmethod
    def _user(cls, v: str) -> str:
        return _check_user(v)

    @field_validator("src_path")
    @classmethod
    def _src(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("must be an absolute path")
        if v == "/":
            raise ValueError("must not be /")
        if v.endswith("/"):
            raise ValueError("must not end with / (the folder itself is backed up)")
        return v

    @field_validator("excludes")
    @classmethod
    def _excludes(cls, v: list[str]) -> list[str]:
        for pattern in v:
            if not pattern or "\n" in pattern:
                raise ValueError("exclude patterns must be non-empty single lines")
        return v


class Config(_Model):
    version: Literal[2]
    server: ServerSection
    settings: Settings = Field(default_factory=Settings)
    notifications: Notifications = Field(default_factory=Notifications)
    hosts: dict[str, HostConfig] = Field(min_length=1)
    modules: dict[str, ModuleConfig] = Field(min_length=1)

    @field_validator("hosts")
    @classmethod
    def _host_keys(cls, v: dict[str, HostConfig]) -> dict[str, HostConfig]:
        for key in v:
            if not HOST_KEY_RE.match(key):
                raise ValueError(
                    f"host key {key!r} must be lower-case letters, digits and '-' "
                    "(starting with a letter or digit, at most 63 characters)"
                )
        return v

    @field_validator("modules")
    @classmethod
    def _module_names(cls, v: dict[str, ModuleConfig]) -> dict[str, ModuleConfig]:
        for name in v:
            if not MODULE_NAME_RE.match(name):
                raise ValueError(
                    f"module name {name!r} may only contain letters, digits, '-' and '_' "
                    "(1 to 64 characters)"
                )
        return v

    # ------------------------------------------------------------- derived views

    def user_hosts(self) -> list[tuple[str, str]]:
        """Every (host, user) pair that has modules, sorted."""
        return sorted({(m.host, m.user) for m in self.modules.values()})

    def users_on(self, host: str) -> list[str]:
        return sorted({m.user for m in self.modules.values() if m.host == host})

    def module_set(self) -> dict[str, ModuleSpec]:
        """Config modules plus the generated host-config modules (§6.9)."""
        out: dict[str, ModuleSpec] = {}
        for name, m in self.modules.items():
            out[name] = ModuleSpec(
                name=name,
                host=m.host,
                user=m.user,
                type="path",
                src_path=m.src_path,
                excludes=tuple(m.excludes),
            )
        if self.settings.host_config_backup:
            for host, user in self.user_hosts():
                name = host_config_name(user, host)
                out[name] = ModuleSpec(name=name, host=host, user=user, type="host-config")
        return dict(sorted(out.items()))


def host_config_name(user: str, host: str) -> str:
    return f"{user}-{host}"


@dataclass(frozen=True)
class ModuleSpec:
    """One unit of work in a run: a config module or a generated host-config module."""

    name: str
    host: str
    user: str
    type: Literal["path", "host-config"]
    src_path: str | None = None
    excludes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def basename(self) -> str | None:
        return self.src_path.rsplit("/", 1)[-1] if self.src_path else None


# --------------------------------------------------------------------------- loading


class _UniqueKeyLoader(yaml.SafeLoader):
    """A SafeLoader that refuses duplicate keys (YAML would silently keep the last one)."""


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=True)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def parse_yaml(text: str, where: str = "config") -> Any:
    try:
        return yaml.load(text, Loader=_UniqueKeyLoader)  # a SafeLoader subclass
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        line = f" (line {mark.line + 1})" if mark is not None else ""
        problem = getattr(e, "problem", None) or str(e)
        raise ConfigError([f"{where}{line}: {problem}"]) from e


def _format_pydantic(err: ValidationError) -> list[str]:
    out = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "config"
        msg = e["msg"].removeprefix("Value error, ")
        if e["type"] == "extra_forbidden":
            msg = "unknown key (check the spelling)"
        elif e["type"] == "missing":
            msg = "required"
        out.append(f"{loc}: {msg}")
    return out


def semantic_errors(cfg: Config) -> list[str]:
    """Rules that span several fields (§4)."""
    errors: list[str] = []
    for name, m in cfg.modules.items():
        if m.host not in cfg.hosts:
            errors.append(f"modules.{name}.host: {m.host!r} is not listed under hosts")
        if name in RESERVED_MODULE_NAMES or name.startswith("."):
            errors.append(f"modules.{name}: this name is reserved")
    if cfg.settings.host_config_backup:
        generated: dict[str, tuple[str, str]] = {}
        for host, user in cfg.user_hosts():
            name = host_config_name(user, host)
            if name in cfg.modules:
                errors.append(
                    f"modules.{name}: clashes with the generated host-config module for "
                    f"{user}@{host}; rename the module"
                )
            if name in generated:
                other = generated[name]
                errors.append(
                    f"{user}@{host} and {other[1]}@{other[0]} would both get the host-config "
                    f"module {name!r}; rename a host or turn off host_config_backup"
                )
            generated[name] = (host, user)
    return errors


def validate_data(data: Any, home: Path | None = None) -> Config:
    if not isinstance(data, dict):
        raise ConfigError(["config: the file must be a YAML mapping (key: value)"])
    if "version" not in data:
        raise ConfigError(
            [
                "version: missing. This looks like a v1 configuration; convert it with "
                "bn-backup config migrate OLD.yml -o NEW.yml"
            ]
        )
    try:
        cfg = Config.model_validate(data, context={"home": home or Path.home()})
    except ValidationError as e:
        raise ConfigError(_format_pydantic(e)) from e
    errors = semantic_errors(cfg)
    if errors:
        raise ConfigError(errors)
    return cfg


@dataclass(frozen=True)
class LoadedConfig:
    config: Config
    path: Path
    raw: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


def load_config(path: Path, home: Path | None = None) -> LoadedConfig:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ConfigError(
            [f"{path}: not found. Run `bn-backup server init` to create a template"]
        ) from None
    except OSError as e:
        raise ConfigError([f"{path}: cannot read ({e.strerror})"]) from e
    data = parse_yaml(raw.decode("utf-8", errors="replace"), where=str(path))
    return LoadedConfig(config=validate_data(data, home), path=path, raw=raw)


def show(cfg: Config, as_json: bool) -> str:
    data = cfg.model_dump(mode="json", by_alias=True)
    if as_json:
        return json.dumps(data, indent=2) + "\n"
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


# --------------------------------------------------------------------------- migrate

_SAFE_SCALAR = re.compile(r"^[A-Za-z0-9_./@+][A-Za-z0-9_./@:+-]*$")
_YAML_WORDS = {"y", "n", "yes", "no", "on", "off", "true", "false", "null", "~"}


def yaml_scalar(value: str) -> str:
    """A string as a YAML scalar, quoted only when needed."""
    plain = (
        _SAFE_SCALAR.match(value)
        and value.lower() not in _YAML_WORDS
        and not re.match(r"^[0-9.+-]", value)
    )
    return value if plain else json.dumps(value)


def _bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def migrate(text: str, current_user: str) -> tuple[str, list[str]]:
    """Convert a v1 config to v2 text. Returns (new text, list of guesses to check)."""
    data = parse_yaml(text, where="input")
    if not isinstance(data, dict):
        raise ConfigError(["input: not a YAML mapping"])
    if "version" in data:
        if data["version"] == CONFIG_VERSION:
            raise AlreadyCurrentError(["already at version 2; nothing to migrate"])
        raise ConfigError([f"version: unknown version {data['version']!r}"])
    settings = data.get("settings") or {}
    modules = data.get("modules") or {}
    if not isinstance(settings, dict) or not isinstance(modules, dict):
        raise ConfigError(["input: settings and modules must be mappings"])
    if "backup_directory" not in settings:
        raise ConfigError(["settings.backup_directory: missing in the v1 file"])
    if not modules:
        raise ConfigError(["modules: the v1 file has no modules"])

    guesses: list[str] = []
    todo = "   # TODO verify"
    hosts: dict[str, str] = {}
    for name, m in modules.items():
        if not isinstance(m, dict) or "host" not in m or "user" not in m or "src_path" not in m:
            raise ConfigError([f"modules.{name}: needs host, user and src_path"])
        hosts.setdefault(str(m["host"]), str(m["user"]))

    lines = [
        "# Converted from a v1 configuration by `bn-backup config migrate`.",
        "# Lines marked TODO verify are guesses: check each one, then run",
        "# `bn-backup config validate`.",
        "version: 2",
        "",
        "server:",
        f"  backup_directory: {yaml_scalar(str(settings['backup_directory']))}",
        f"  ssh_host: CHANGE-ME{todo}: the server's name as hosts see it",
        "  ssh_port: 22",
        f"  receive_user: {yaml_scalar(current_user)}{todo}",
        "",
        "settings:",
        f"  verify_backup: {_bool(settings.get('verify_backup', False))}",
    ]
    guesses.append("server.ssh_host: set the name hosts use to reach this server")
    guesses.append(f"server.receive_user: {current_user} (the account running this command)")
    if "resume_backup" in settings:
        lines.append(f"  resume_backup: {_bool(settings['resume_backup'])}")
    else:
        lines.append(f"  resume_backup: true{todo}: v1 default was false")
        guesses.append("settings.resume_backup: true (v2 default; v1 used false)")
    lines.append(f"  dry_run: {_bool(settings.get('dry_run', False))}")
    lines += ["", "hosts:"]
    for host, user in hosts.items():
        address = f"{host}.CHANGE-ME.lan"
        lines += [
            f"  {yaml_scalar(host)}:",
            f"    address: {yaml_scalar(address)}{todo}",
            f"    admin_user: {yaml_scalar(user)}{todo}",
        ]
        guesses.append(f"hosts.{host}.address: {address}")
        guesses.append(f"hosts.{host}.admin_user: {user} (user of its first module)")
    lines += ["", "modules:"]
    for name, m in modules.items():
        lines += [
            f"  {yaml_scalar(str(name))}:",
            f"    host: {yaml_scalar(str(m['host']))}",
            f"    user: {yaml_scalar(str(m['user']))}",
            f"    src_path: {yaml_scalar(str(m['src_path']))}",
        ]
        dropped = sorted(set(m) - {"host", "user", "src_path", "os"})
        if dropped:
            guesses.append(f"modules.{name}: dropped unknown v1 keys {', '.join(dropped)}")
    return "\n".join(lines) + "\n", guesses


# --------------------------------------------------------------------------- template

TEMPLATE = """\
# bleiben Backup Orchestrator configuration (format version 2).
# Edit it, then run `bn-backup server init` again.
version: 2

server:
  backup_directory: /Volumes/Backup/bn-backup   # on the APFS (Case-sensitive) drive
  ssh_host: server.home.lan                    # how hosts reach this server
  ssh_port: 22
  receive_user: {user}                          # your account on this server

settings:
  mode: mirror               # mirror | snapshot (snapshot recommended for photographers)
  snapshot_keep: 8
  verify_backup: false       # extra pass: compare contents and report differences (slow)
  resume_backup: true
  host_config_backup: true   # /etc/hosts, /etc/motd and dotfiles per user@host

notifications:
  email:
    enabled: false
    smtp_host: smtp.example.com
    smtp_port: 587
    starttls: true
    username: you@example.com
    password_file: ~/.config/bn-backup/smtp_password   # bn-backup notify set-smtp-password
    from: you@example.com
    to: [you@example.com]
  signal:
    enabled: false
    signal_cli: /opt/homebrew/bin/signal-cli
    account: "+61400000000"
    note_to_self: true
    recipients: []

hosts:
  galactica:
    address: galactica.home.lan
    admin_user: {user}

modules:
  photo-archive:                       # one module per archive
    host: galactica
    user: {user}
    src_path: /Volumes/PhotoArchive/Photos
  lightroom:                           # close Lightroom before a run
    host: galactica
    user: {user}
    src_path: /Users/{user}/Pictures/Lightroom
    excludes: ["*.lrdata"]             # previews: large, rebuilt by Lightroom
"""


def template(user: str) -> str:
    return TEMPLATE.format(user=user)
