# -*- coding: utf-8 -*-
import logging
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator


class RsyncErrorModel(BaseModel):
    """Model to structure and validate Rsync error details."""
    message: str = Field(..., description="A brief error message.")
    return_code: int = Field(..., description="Exit code from rsync.")
    output: str = Field(..., description="Detailed error output from rsync.")


class RsyncError(Exception):
    """Custom exception for rsync-related errors."""

    def __init__(self, error_data: dict):
        try:
            self.error_details = RsyncErrorModel(**error_data)
        except ValidationError as e:
            raise ValueError(f"Invalid RsyncError data: {e}")

    def __str__(self):
        return (
            f"RsyncError: {self.error_details.message} "
            f"(Exit Code: {self.error_details.return_code})\n"
            f"Details: {self.error_details.output}"
        )


class CommandExecutor(BaseModel):
    """Utility class to execute shell commands with real-time progress."""

    log_level: str = Field(
        "INFO", description="Logging level for the executor.")
    verify_backup: bool = Field(
        False, description="Activate checksum verification in the rsync command.")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value):
        """Ensure log_level is valid."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if value.upper() not in valid_levels:
            raise ValueError(
                f"Invalid log_level: {value}. Valid options are: {valid_levels}")
        return value.upper()

    def _configure_logging(self):
        """Configure logging based on the validated log level."""
        numeric_level = getattr(logging, self.log_level, logging.INFO)
        logging.basicConfig(level=numeric_level)
        logging.debug(f"Logging level set to {self.log_level}")

    def get_rsync_command(self, src: str, dst: Path, log_file: Path, extra_args: str = "") -> str:
        """Construct the rsync command."""
        if self.log_level == "DEBUG":
            extra_args += " --stats"
        if self.verify_backup:
            logging.warning(
                "Backup verification is enabled; the current backup process may take longer than usual.")
            extra_args += "--checksum"
        return f"rsync --archive --compress --log-file={log_file} --info=progress2 --delete {extra_args} {src} {dst}"

    def execute_command(self, command: str):
        """Execute a shell command and handle errors."""
        self._configure_logging()
        logging.debug(f"#### Executing command: {command}")
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                text=True,
                bufsize=1,
            )
            if process.stdout:
                for line in process.stdout:
                    sys.stdout.write(f"\r{line.strip()}")
                    sys.stdout.flush()

            process.wait()
            sys.stdout.write("\n")

            if process.returncode != 0:
                stderr_output = process.stderr.read() if process.stderr else ""
                raise RsyncError({
                    "message": "Command execution failed",
                    "return_code": process.returncode,
                    "output": stderr_output.strip(),
                })
        except subprocess.SubprocessError as e:
            raise RsyncError({
                "message": "Subprocess execution failed",
                "return_code": -1,
                "output": str(e),
            }) from e
