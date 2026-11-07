# -*- coding: utf-8 -*-
"""
backup_orchestrator.py

Provides a Pydantic-powered system to orchestrate backups of hosts and modules
using rsync, with structured logging, validation, and error handling.

This module defines:

Classes:
    HostInfo: Represents information about a host to be backed up.
    BackupConfig: Configuration model for backup operations, including logging.
    BackupModules: Represents the backup configuration from a YAML file.
    BackupOrchestrator: Coordinates backup operations for hosts and modules,
        handling:
        - Construction and execution of rsync commands
        - Backup of configuration files and home directories
        - Management of current and previous backups
        - Logging and reporting of successful, failed, and unreachable hosts

Features:
    - Validates configuration and log levels using Pydantic.
    - Supports resumable backups and optional verification with checksums.
    - Maintains backup reports and logs for auditing purposes.
    - Handles subprocess errors via the RsyncError exception.
"""


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
    """
    Configuration model for backup operations.

    Attributes:
        yaml_file (Path): Path to the YAML configuration file.
        log_level (str): Logging level for backup operations.
            Must be one of "INFO", "DEBUG", or "TRACE".
            Defaults to "INFO".
    """

    yaml_file: Path
    log_level: str = Field(default="INFO")

    @field_validator("log_level")
    @classmethod
    def validate_loglevel(cls, v: str) -> str:
        """
        Validate that the log_level value is one of the allowed levels.

        Args:
            v (str): The log level to validate.

        Returns:
            str: The validated log level.

        Raises:
            ValueError: If `v` is not one of "INFO", "DEBUG", or "TRACE".
        """
        valid_levels = ["INFO", "DEBUG", "TRACE"]
        if v not in valid_levels:
            raise ValueError(f"Invalid log_level: {v}. Choose from {valid_levels}")
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
        default_factory=lambda: {
            "successful": [],
            "failed": [],
            "unreachable_hosts": [],
        }
    )
    executor: CommandExecutor = Field(default=None, exclude=True)
    backup_directory: Path = Field(default=None)
    verify_backup: bool = Field(default=False)
    resume_backup: bool = Field(default=False)
    dry_run: bool = Field(default=False)

    def model_post_init(self, __context: Any) -> None:
        """Perform additional initialization and validation after parsing."""
        logging.info("## Welcome to the Backup System Management ##")
        self._load_config_and_backup_info()
        logging.info(
            f"## The directory {self.backup_directory} has been successfully configured."
        )
        self.executor = CommandExecutor(
            log_level=self.config.log_level,
            verify_backup=self.verify_backup,
            resume_backup=self.resume_backup,
            dry_run=self.dry_run,
        )
        if self.dry_run:
            logging.warning(
                "## DRY RUN: rsync will only report what it would do; "
                "no backup data, configuration or report will be changed."
            )
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

    # pylint: disable=no-self-use
    def _get_required_setting(self, settings: dict, key: str) -> str:
        """Fetch a required setting or raise an error if it is missing."""
        value = settings.get(key)
        if value is None:
            raise ValueError(
                f"The '{key}' field is required in the 'settings' section of \
                the configuration file."
            )
        return value

    def _create_backup_directory(self) -> None:
        if not self.backup_directory.exists():
            try:
                self.backup_directory.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise NotADirectoryError(
                    f"Cannot create the directory {self.backup_directory}. "
                    "Please check permissions and verify the directory path."
                ) from e

    def _retrieve_previous_backup_info(self, current_yaml_file: Path) -> None:
        previous_config_file = self.get_current_backup_path() / current_yaml_file.name
        if previous_config_file.exists():
            with previous_config_file.open() as f:
                try:
                    previous_config_data = yaml.safe_load(f)
                    self.yaml_info["previous"] = BackupModules(
                        modules=previous_config_data.get("modules", {})
                    )
                except ValidationError as e:
                    logging.error(
                        f"Invalid backup configuration in {previous_config_file}: {e}"
                    )
                    raise
        else:
            logging.warning(
                "No previous backup found; skipping the copy of backup-related files."
            )

    def _load_config_and_backup_info(self) -> None:
        """Load and validate backup configuration from YAML files."""
        logging.debug("#### Loading YAML file information.")

        current_yaml_file = self.config.yaml_file
        if current_yaml_file.is_file():
            with current_yaml_file.open() as f:
                try:
                    config_data = yaml.safe_load(f)
                    settings = config_data.get("settings", {})
                    self.backup_directory = Path(
                        self._get_required_setting(settings, "backup_directory")
                    )
                    self.verify_backup = settings.get("verify_backup", False)
                    self.resume_backup = settings.get("resume_backup", False)
                    self.dry_run = settings.get("dry_run", False)

                    # Validate and assign modules
                    modules = config_data.get("modules", {})
                    self.yaml_info["current"] = BackupModules(modules=modules)

                except ValidationError as e:
                    logging.error(
                        f"Invalid backup configuration in {current_yaml_file}: {e}"
                    )
                    raise
        else:
            logging.warning("No current YAML file found. Initializing empty modules.")
            self.yaml_info["current"] = BackupModules()
        self._create_backup_directory()
        self._retrieve_previous_backup_info(current_yaml_file=current_yaml_file)

    def _prepare_directory(self, path: Path) -> None:  # pylint: disable=no-self-use
        """Ensure a directory exists."""
        path.mkdir(parents=True, exist_ok=True)

    def _move_missing_modules(self) -> None:
        """Identify and move missing modules from current to previous backup."""
        previous_backup_path = self.get_previous_backup_path()
        current_backup_path = self.get_current_backup_path()

        if (
            "previous" in self.yaml_info
            and self.yaml_info["previous"].modules != self.yaml_info["current"].modules
        ):
            missing_modules = set(self.yaml_info["previous"].modules) - set(
                self.yaml_info["current"].modules
            )
            if self.dry_run:
                for module in missing_modules:
                    logging.warning(f"## DRY RUN: would move missing module: {module}")
                return
            self._prepare_directory(previous_backup_path)
            for module in missing_modules:
                logging.warning(f"## Moving missing module: {module}")
                src_dir = current_backup_path / module
                dst_dir = previous_backup_path / module
                if dst_dir.is_dir():
                    shutil.rmtree(dst_dir)
                if src_dir.exists():
                    shutil.move(src_dir, dst_dir)
            shutil.copy(self.config.yaml_file, previous_backup_path)
            shutil.copy(current_backup_path / "backup_report.log", previous_backup_path)

    def _run_job(self, job_name: str, cmd: list[str]) -> str | None:
        """Run one rsync job, never letting its failure stop the others.

        Returns None on success, or a short failure reason for the report.
        """
        try:
            self.executor.execute_command(cmd)
            return None
        except RsyncError as e:
            logging.error(f"## {job_name} failed:\n{e}")
            return e.summary
        except Exception as e:  # pylint: disable=broad-except
            # Unexpected errors (I/O, decoding, ...) are logged with a traceback
            # and the run carries on with the next job.
            logging.opt(exception=e).error(
                f"## {job_name} failed with an unexpected error: {e!r}"
            )
            return f"unexpected error: {e!r}"

    def _backup_host_configuration(self, host_info: HostInfo) -> None:
        """Backup configuration files and home directory for a specific host.

        Each step runs independently, so one failure does not skip the rest.
        """
        home_dir = "home" if host_info.os == "linux" else "Users"
        host_path = (
            self.get_current_backup_path() / f"{host_info.user}-{host_info.host}"
        )
        home_conf_path = host_path / host_info.user
        self._prepare_directory(home_conf_path)

        jobs = {
            f"/etc/{file}": self.executor.get_rsync_command(
                src=f"{host_info.user}@{host_info.host}:/etc/{file}",
                dst=host_path / file,
                log_file=self.get_logs_path()
                / f"rsync-output-conf-hosts-{host_info.user}.txt",
            )
            for file in ["motd", "hosts"]
        }
        jobs["dotfiles"] = self.executor.get_rsync_command(
            src=f"{host_info.user}@{host_info.host}:/{home_dir}/{host_info.user}/.[^.]*",
            dst=home_conf_path,
            log_file=self.get_logs_path() / f"rsync-output-conf-{host_info.user}.txt",
            extra_args=["--exclude", ".Trash", "--exclude", ".cache"],
        )

        for step, cmd in jobs.items():
            reason = self._run_job(f"Host {host_info.host} ({step})", cmd)
            if reason:
                self.report["unreachable_hosts"].append(
                    f" Host {host_info.host} ({step}): {reason}"
                )

    def _write_report(self) -> None:
        """Write the current backup report to a log file."""
        report_file = self.get_current_backup_path() / "backup_report.log"
        date_format = "%Y%m%d-%H%M%S"
        date_info = datetime.datetime.now().strftime(date_format)
        logging.debug(f"#### Backup date written: {date_info}")
        with report_file.open("w") as f:
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

    def has_failures(self) -> bool:
        """True if any module or host job failed."""
        return bool(self.report["failed"] or self.report["unreachable_hosts"])

    def rsync_modules(self, save_conf: bool = True) -> None:
        """Perform backup of all modules.

        A failing module or host is recorded in the report and the run moves on
        to the next one; the report is always written at the end.
        """
        self._move_missing_modules()
        self._prepare_directory(self.get_current_backup_path())

        try:
            for module_name, host_info in self.yaml_info["current"].modules.items():
                logging.info(f"## Starting backup for module: {module_name}")
                self.host_list.append(host_info)

                cmd = self.executor.get_rsync_command(
                    src=f"{host_info.user}@{host_info.host}:{host_info.src_path}",
                    dst=self.get_current_backup_path() / module_name,
                    log_file=self.get_logs_path() / f"rsync-output-{module_name}.txt",
                )
                reason = self._run_job(
                    f"Module {module_name} ({host_info.src_path})", cmd
                )
                if reason:
                    self.report["failed"].append(
                        f" {module_name}: {host_info.src_path} ({reason})"
                    )
                else:
                    self.report["successful"].append(
                        f" {module_name}: {host_info.src_path}"
                    )
                    logging.success(f"## Backup completed for module: {module_name}")

            if save_conf:
                unique_hosts = {f"{h.user}@{h.host}" for h in self.host_list}
                for host in unique_hosts:
                    logging.info(f"## Starting backup for host: {host}")
                    host_info = next(
                        h for h in self.host_list if f"{h.user}@{h.host}" == host
                    )
                    self._backup_host_configuration(host_info)
        finally:
            if self.dry_run:
                # Keep the stored config/report intact: the next real run uses
                # current/<config>.yml to detect removed modules.
                logging.info("## DRY RUN: backup config and report left untouched.")
            else:
                # Always leave a report behind, even if the run was interrupted.
                shutil.copy(self.config.yaml_file, self.get_current_backup_path())
                self._write_report()

        self._log_summary()

    def _log_summary(self) -> None:
        """Log a short end-of-run summary."""
        ok = len(self.report["successful"])
        failed = self.report["failed"] + self.report["unreachable_hosts"]
        if not failed:
            logging.success(f"## All {ok} module(s) backed up successfully.")
            return
        logging.warning(
            f"## Backup finished with {len(failed)} failure(s), {ok} module(s) OK:"
        )
        for item in failed:
            logging.warning(f"##  -{item}")
        if not self.dry_run:
            logging.warning(
                f"## Details: {self.get_current_backup_path() / 'backup_report.log'}"
            )
