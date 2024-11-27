# -*- coding: utf-8 -*-
import datetime
import shutil
from pathlib import Path
from typing import Any, Dict, List

import yaml
from loguru import logger as logging
from pydantic import BaseModel, Field, ValidationError, field_validator

from backup_orchestrator.private.command_executor import CommandExecutor, RsyncError


class HostInfo(BaseModel):
    """Represents information about a host for backup."""
    user: str
    host: str
    os: str
    src_path: str


class BackupConfig(BaseModel):
    yaml_file: Path
    log_level: str = Field(default="INFO")

    @field_validator("log_level")
    def validate_loglevel(cls, v):
        valid_levels = ["INFO", "DEBUG", "TRACE"]
        if v not in valid_levels:
            raise ValueError(
                f"Invalid log_level: {v}. Choose from {valid_levels}")
        return v


class BackupModules(BaseModel):
    """Represents the backup configuration from a YAML file."""
    modules: Dict[str, HostInfo] = Field(default_factory=dict)


class BackupOrchestrator(BaseModel):
    """Pydantic-powered BackupOrchestrator class."""
    config: BackupConfig
    yaml_info: Dict[str, BackupModules] = Field(default_factory=dict)
    host_list: List = Field(default_factory=list)
    report: Dict[str, List[str]] = Field(
        default_factory=lambda: {"successful": [],
                                 "failed": [], "unreachable_hosts": []}
    )
    executor: CommandExecutor = Field(default=None, exclude=True)
    backup_directory: Path = Field(default=None)
    verify_backup: bool = Field(default=False)

    def model_post_init(self, __context: Any) -> None:
        """Perform additional initialization and validation after parsing."""
        self._load_backup_info()
        if not self.backup_directory.exists():
            try:
                self.backup_directory.mkdir(parents=True, exist_ok=True)
                logging.info(
                    f"Directory {self.backup_directory} created successfully."
                )
            except Exception as e:
                raise NotADirectoryError(
                    f"Cannot create the directory {self.backup_directory}. "
                    "Please check permissions and verify the directory path."
                ) from e

        logging.info("## Welcome to the Backup System Management ##")

        self.executor = CommandExecutor(
            log_level=self.config.log_level, verify_backup=self.verify_backup)
        self.get_logs_path().mkdir(parents=True, exist_ok=True)

    def get_current_backup_path(self) -> Path:
        """Returns the path to the current backup directory."""
        return self.backup_directory / "current"

    def get_previous_backup_path(self) -> Path:
        """Returns the path to the previous backup directory."""
        return self.backup_directory / "previous"

    def get_logs_path(self) -> Path:
        """Returns the path to the logs directory."""
        return self.backup_directory / "logs"

    def _get_required_setting(self, settings: dict, key: str) -> str:
        """Fetch a required setting or raise an error if it is missing."""
        value = settings.get(key)
        if value is None:
            raise ValueError(
                f"The '{key}' field is required in the 'settings' section of the configuration file.")
        return value

    def _load_backup_info(self):
        """Load and validate backup configuration from YAML files."""
        logging.debug("#### Loading YAML file information.")

        current_yaml_file = self.config.yaml_file
        if current_yaml_file.is_file():
            with current_yaml_file.open() as f:
                try:
                    config_data = yaml.safe_load(f)
                    settings = config_data.get("settings", {})
                    self.backup_directory = Path(
                        self._get_required_setting(settings, "backup_directory"))
                    self.verify_backup = settings.get("verify_backup", False)

                    # Validate and assign modules
                    modules = config_data.get("modules", {})
                    self.yaml_info["current"] = BackupModules(modules=modules)

                except ValidationError as e:
                    logging.error(
                        f"Invalid backup configuration in {current_yaml_file}: {e}")
                    raise
        else:
            logging.warning(
                "No current YAML file found. Initializing empty modules.")
            self.yaml_info["current"] = BackupModules()

        previous_config_file = self.get_current_backup_path() / current_yaml_file.name
        if previous_config_file.exists():
            with previous_config_file.open() as f:
                try:
                    previous_config_data = yaml.safe_load(f)
                    self.yaml_info["previous"] = BackupModules(
                        modules=previous_config_data.get("modules", {}))
                except ValidationError as e:
                    logging.error(
                        f"Invalid backup configuration in {previous_config_file}: {e}")
                    raise
        else:
            logging.warning(
                "No previous backup found; skipping the copy of backup-related files.")

    def _prepare_directory(self, path: Path):
        """Ensure a directory exists."""
        path.mkdir(parents=True, exist_ok=True)

    def _move_missing_modules(self):
        """Identify and move missing modules from current to previous backup."""
        previous_backup_path = self.get_previous_backup_path()
        current_backup_path = self.get_current_backup_path()

        if "previous" in self.yaml_info and self.yaml_info["previous"].modules != self.yaml_info["current"].modules:
            self._prepare_directory(previous_backup_path)
            missing_modules = set(
                self.yaml_info["previous"].modules) - set(self.yaml_info["current"].modules)
            for module in missing_modules:
                logging.warning(f"## Moving missing module: {module}")
                src_dir = current_backup_path / module
                dst_dir = previous_backup_path / module
                if dst_dir.is_dir():
                    shutil.rmtree(dst_dir)
                if src_dir.exists():
                    shutil.move(src_dir, dst_dir)
            shutil.copy(self.config.yaml_file, previous_backup_path)
            shutil.copy(
                current_backup_path / "backup_report.log", previous_backup_path)

    def _backup_host_configuration(self, host_info: HostInfo):
        """Backup configuration files and home directory for a specific host."""
        home_dir = "home" if host_info.os == "linux" else "Users"
        host_path = self.get_current_backup_path(
        ) / f"{host_info.user}-{host_info.host}"
        self._prepare_directory(host_path)
        try:
            # Backup /etc configuration files
            etc_files = ["motd", "hosts"]
            for file in etc_files:
                cmd = self.executor.get_rsync_command(
                    src=f"{host_info.user}@{host_info.host}:/etc/{file}",
                    dst=host_path / "hosts",
                    log_file=self.get_logs_path(
                    ) / f"rsync-output-conf-hosts-{host_info.user}.txt",
                )
                self.executor.execute_command(cmd)

            # Backup home directory
            home_conf_path = host_path / host_info.user
            self._prepare_directory(home_conf_path)
            cmd = self.executor.get_rsync_command(
                src=f"{host_info.user}@{host_info.host}:/{home_dir}/{host_info.user}/.[^.]*",
                dst=home_conf_path,
                log_file=self.get_logs_path(
                ) / f"rsync-output-conf-{host_info.user}.txt",
                extra_args="--exclude '.Trash' --exclude '.cache'",
            )
            self.executor.execute_command(cmd)
        except RsyncError as e:
            logging.error(
                f"## Host: {host_info.host} has the following error: \n {e}.")
            self.report["unreachable_hosts"].append(
                f" Host {host_info.host}: \n {e}")

    def _write_report(self):
        """Write the current backup report to a log file."""
        report_file = self.get_current_backup_path() / "backup_report.log"
        date_format = "%Y%m%d-%H%M%S"
        date_info = datetime.datetime.now().strftime(date_format)
        logging.debug(f"#### Backup date written: {date_info}")
        with report_file.open('w') as f:
            f.write("Backup Report\n")
            f.write("====================\n\n")
            f.write("\n")
            f.write("# Modules\n")
            for report in self.report.keys():
                f.write("\n")
                f.write(f"{report.title()}:\n")
                if self.report[report]:
                    for item in self.report[report]:
                        f.write(f"  - {item}\n")
                else:
                    f.write("\n")
            f.write("\n")
            f.write(f"# Date: {date_info}")

    def rsync_modules(self, save_conf: bool = True):
        """Perform backup of all modules."""
        self._move_missing_modules()
        self._prepare_directory(self.get_current_backup_path())

        for module_name, host_info in self.yaml_info["current"].modules.items():
            logging.info(f"## Starting backup for module: {module_name}")
            self.host_list.append(host_info)

            try:
                cmd = self.executor.get_rsync_command(
                    src=f"{host_info.user}@{host_info.host}:{host_info.src_path}",
                    dst=self.get_current_backup_path() / module_name,
                    log_file=self.get_logs_path(
                    ) / f"rsync-output-{module_name}.txt",
                )
                self.executor.execute_command(cmd)
                self.report["successful"].append(
                    f" {module_name}: {host_info.src_path}")
                logging.success(
                    f"## Backup completed for module: {module_name}")
            except RsyncError as e:
                logging.error(
                    f"## Module: {module_name}, {host_info.src_path} has the following error: \n {e}.")
                self.report["failed"].append(
                    f" {module_name}: {host_info.src_path}")

        if save_conf:
            unique_hosts = {f"{h.user}@{h.host}" for h in self.host_list}
            for host in unique_hosts:
                logging.info(f"## Starting backup for host: {host}")
                host_info = next(
                    h for h in self.host_list if f"{h.user}@{h.host}" == host)
                self._backup_host_configuration(host_info)

        shutil.copy(self.config.yaml_file, self.get_current_backup_path())
        self._write_report()
