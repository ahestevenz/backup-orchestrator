# -*- coding: utf-8 -*-
# TODO:
# Sanity check for each computer
# Can we recofigure SSH connections if they are missing?
# Handle network issues

# Handle current/previous directories with different dst directories

# Verify the backup

import datetime
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

from loguru import logger as logging
from pydantic import BaseModel, Field, ValidationError, field_validator


class HostInfo(BaseModel):
    """Represents information about a host for backup."""
    user: str
    host: str
    os: str
    src_path: str


class BackupConfig(BaseModel):
    json_file: Path
    backup_directory: Path
    log_level: str = Field(default="INFO")

    @field_validator("log_level")
    def validate_loglevel(cls, v):
        valid_levels = ["INFO", "DEBUG", "TRACE"]
        if v not in valid_levels:
            raise ValueError(
                f"Invalid log_level: {v}. Choose from {valid_levels}")
        return v


class BackupModules(BaseModel):
    """Represents the backup configuration from a JSON file."""
    modules: Dict[str, HostInfo]


class BackupOrchestrator:
    def __init__(self, config: BackupConfig):
        if not config.backup_directory.exists():
            try:
                config.backup_directory.mkdir(parents=True, exist_ok=True)
                logging.info(
                    f"Directory {config.backup_directory} created successfully.")
            except Exception as e:
                raise NotADirectoryError(
                    f"Cannot create the directory {config.backup_directory}."
                    + "Please check permissions and verify the directory path."
                ) from e

        logging.info("## Welcome to the Backup System Management ##")
        self.backup_dirs = {
            "current": config.backup_directory / "current",
        }
        self.json_file = {
            "current": config.json_file,
        }
        self.report_modules: Dict[str, List[str]] = {
            "successful": [],
            "failed": []
        }
        previous_config_file = self.backup_dirs["current"] / \
            self.json_file["current"].name
        if previous_config_file.exists():
            self.backup_dirs["previous"] = config.backup_directory / "previous"
            self.json_file["previous"] = previous_config_file
        else:
            logging.info("No previous configuration found.")

        self.logs_dir = config.backup_directory / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.host_list: List[HostInfo] = []
        self.log_level = config.log_level
        self.json_info: Dict[str, BackupModules] = {}

        self._load_backup_info()

    def _load_backup_info(self):
        """Load and validate backup configuration from JSON files."""
        logging.debug("#### Loading JSON file information.")
        for key, file_path in self.json_file.items():
            if file_path.is_file():
                with file_path.open() as f:
                    try:
                        self.json_info[key] = BackupModules(
                            modules=json.load(f))
                    except ValidationError as e:
                        logging.error(
                            f"Invalid backup configuration in {file_path}: {e}")
                        raise
            else:
                self.json_info[key] = BackupModules(modules={})

    def _prepare_directory(self, path: Path):
        """Ensure a directory exists."""
        path.mkdir(parents=True, exist_ok=True)

    def _get_rsync_command(self, src: str, dst: Path, log_file: Path, extra_args: str = "") -> str:
        """Construct the rsync command."""
        if self.log_level == "DEBUG":
            extra_args += " --stats"
        return f"rsync --archive --compress --log-file={log_file} --info=progress2 --delete {extra_args} {src} {dst}"

    def _execute_command(self, command: str):
        """Execute a shell command using subprocess."""
        logging.debug(f"#### Executing command: {command}")
        with subprocess.Popen(command, stdout=subprocess.PIPE, bufsize=0, shell=True) as p:
            if p.stdout is not None:
                char = p.stdout.read(1)
                while char != b'':
                    print(char.decode('UTF-8'), end='', flush=True)
                    char = p.stdout.read(1)

    def _move_missing_modules(self):
        """Identify and move missing modules from current to previous backup."""
        if "previous" in self.json_info and self.json_info["previous"].modules != self.json_info["current"].modules:
            self._prepare_directory(self.backup_dirs["previous"])
            missing_modules = set(
                self.json_info["previous"].modules) - set(self.json_info["current"].modules)
            for module in missing_modules:
                logging.info(f"## Moving missing module: {module}")
                src_dir = self.backup_dirs["current"] / module
                dst_dir = self.backup_dirs["previous"] / module
                if dst_dir.is_dir():
                    shutil.rmtree(dst_dir)
                if src_dir.exists():
                    shutil.move(src_dir, dst_dir)
            shutil.copy(self.json_file["previous"],
                        self.backup_dirs["previous"])
            shutil.copy(
                self.backup_dirs["current"] / "backup_date.log", self.backup_dirs["previous"])

    def _backup_host_configuration(self, host_info: HostInfo):
        """Backup configuration files and home directory for a specific host."""
        home_dir = "home" if host_info.os == "linux" else "Users"
        host_path = self.backup_dirs["current"] / \
            f"{host_info.user}-{host_info.host}"
        self._prepare_directory(host_path)

        # Backup /etc configuration files
        etc_files = ["motd", "hosts"]
        for file in etc_files:
            cmd = self._get_rsync_command(
                src=f"{host_info.user}@{host_info.host}:/etc/{file}",
                dst=host_path / "hosts",
                log_file=self.logs_dir /
                    f"rsync-output-conf-hosts-{host_info.user}.txt",
            )
            self._execute_command(cmd)

        # Backup home directory
        home_conf_path = host_path / host_info.user
        self._prepare_directory(home_conf_path)
        cmd = self._get_rsync_command(
            src=f"{host_info.user}@{host_info.host}:/{home_dir}/{host_info.user}/.[^.]*",
            dst=home_conf_path,
            log_file=self.logs_dir / f"rsync-output-conf-{host_info.user}.txt",
            extra_args="--exclude '.Trash' --exclude '.cache'",
        )
        self._execute_command(cmd)

    def _write_report(self):
        """Write the current backup report to a log file."""
        report_file = self.backup_dirs["current"] / "backup_report.log"
        date_format = "%Y%m%d-%H%M%S"
        date_info = datetime.datetime.now().strftime(date_format)
        logging.debug(f"#### Backup date written: {date_info}")
        with report_file.open('w') as f:
            f.write("Backup Report\n")
            f.write("====================\n\n")
            for report in self.report_modules.keys():
                f.write("\n")
                f.write(f"{report.capitalize()} Modules:\n")
                if self.report_modules[report]:
                    for module in self.report_modules[report]:
                        f.write(f"- {module}\n")
                else:
                    f.write("\n")
            f.write("\n")
            f.write(f"Date: {date_info}")

    def rsync_modules(self, save_conf: bool = True):
        """Perform backup of all modules."""
        self._move_missing_modules()
        self._prepare_directory(self.backup_dirs["current"])

        for module_name, host_info in self.json_info["current"].modules.items():
            logging.info(f"## Starting backup for module: {module_name}")
            self.host_list.append(host_info)

            if Path(host_info.src_path).exists():
                cmd = self._get_rsync_command(
                    src=f"{host_info.user}@{host_info.host}:{host_info.src_path}",
                    dst=self.backup_dirs["current"] / module_name,
                    log_file=self.logs_dir / f"rsync-output-{module_name}.txt",
                )
                self._execute_command(cmd)
                self.report_modules["successful"].append(
                    f" {module_name}: {host_info.src_path}")
                logging.success(
                    f"## Backup completed for module: {module_name}")
            else:
                logging.error(
                    f"## Module: {module_name}, {host_info.src_path} does not exist.")
                self.report_modules["failed"].append(
                    f" {module_name}: {host_info.src_path}")

        if save_conf:
            unique_hosts = {f"{h.user}@{h.host}" for h in self.host_list}
            for host in unique_hosts:
                host_info = next(
                    h for h in self.host_list if f"{h.user}@{h.host}" == host)
                self._backup_host_configuration(host_info)

        shutil.copy(self.json_file["current"], self.backup_dirs["current"])
        self._write_report()
