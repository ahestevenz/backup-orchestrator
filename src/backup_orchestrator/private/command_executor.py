# -*- coding: utf-8 -*-
"""
command_executor.py

Provides utilities for executing shell commands with structured error handling,
logging, and support for rsync-based backup operations.

This module defines:

Classes:
    RsyncErrorModel: Pydantic model for structured and validated rsync error details.
    RsyncError: Custom exception wrapping RsyncErrorModel for consistent error reporting.
    CommandExecutor: Executes shell commands (especially rsync) with options for:
        - Configurable logging
        - Optional backup verification using checksum
        - Resumable backups
        - Real-time progress display

Features:
    - Validates configuration and logging levels using Pydantic models.
    - Constructs safe, configurable rsync commands.
    - Handles subprocess execution errors and reports them via RsyncError.
"""


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
            super().__init__(f"Rsync error: {self.error_details}")
        except ValidationError as e:
            raise ValueError(f"Invalid RsyncError data: {e}") from e

    def __str__(self):
        return (
            f"RsyncError: {self.error_details.message} "
            f"(Exit Code: {self.error_details.return_code})\n"
            f"Details: {self.error_details.output}"
        )


class CommandExecutor(BaseModel):
    """Utility class to execute shell commands with real-time progress."""

    log_level: str = Field("INFO", description="Logging level for the executor.")
    verify_backup: bool = Field(
        False, description="Activate checksum verification in the rsync command."
    )
    resume_backup: bool = Field(
        False,
        description="If enabled, incomplete files are kept at the destination, \
        allowing the command to be resumed from where it left off instead of starting from zero.",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value) -> str:
        """Ensure log_level is valid."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if value.upper() not in valid_levels:
            raise ValueError(
                f"Invalid log_level: {value}. Valid options are: {valid_levels}"
            )
        return value.upper()

    def _configure_logging(self) -> None:
        """Configure logging based on the validated log level."""
        numeric_level = getattr(logging, self.log_level, logging.INFO)
        logging.basicConfig(level=numeric_level)
        logging.debug("Logging level set to %s", self.log_level)

    def get_rsync_command(
        self, src: str, dst: Path, log_file: Path, extra_args: list[str] | None = None
    ) -> list[str]:
        """Construct the rsync command."""
        if not extra_args:
            extra_args = []
        if self.log_level == "DEBUG":
            extra_args.append("--stats")
        if self.verify_backup:
            logging.warning(
                "Backup verification is enabled; the current backup process \
                    may take longer than usual."
            )
            extra_args.append("--checksum ")
        if self.resume_backup:
            extra_args.append(" --partial ")
        return [
            "rsync",
            "--archive",
            "--compress",
            f"--log-file={log_file}",
            "--info=progress2",
            "--delete",
            *extra_args,
            src,
            dst.as_posix(),
        ]

    def execute_command(self, command: list[str]) -> None:
        """Execute a shell command and handle errors."""
        self._configure_logging()
        logging.debug("#### Executing command: %s", command)
        try:
            # pylint: disable=consider-using-with
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
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
                raise RsyncError(
                    {
                        "message": "Command execution failed",
                        "return_code": process.returncode,
                        "output": stderr_output.strip(),
                    }
                )
        except subprocess.SubprocessError as e:
            raise RsyncError(
                {
                    "message": "Subprocess execution failed",
                    "return_code": -1,
                    "output": str(e),
                }
            ) from e
