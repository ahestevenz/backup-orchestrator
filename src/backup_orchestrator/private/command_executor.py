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


import functools
import logging
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

# Exit codes documented in rsync(1).
RSYNC_EXIT_CODES = {
    1: "syntax or usage error",
    2: "protocol incompatibility",
    3: "errors selecting input/output files or directories",
    4: "requested action not supported",
    5: "error starting client-server protocol",
    6: "daemon unable to append to log file",
    10: "error in socket I/O",
    11: "error in file I/O",
    12: "error in rsync protocol data stream",
    13: "errors with program diagnostics",
    14: "error in IPC code",
    20: "received SIGUSR1 or SIGINT",
    21: "some error returned by waitpid()",
    22: "error allocating core memory buffers",
    23: "partial transfer due to error",
    24: "partial transfer due to vanished source files",
    25: "the --max-delete limit stopped deletions",
    30: "timeout in data send/receive",
    35: "timeout waiting for daemon connection",
    127: "rsync not found",
    255: "SSH connection failed (host unreachable or authentication error)",
}


# How many rsync error lines to show before pointing at the log file.
MAX_ERROR_LINES = 8


def _rsync_hint(return_code: int, output: str) -> str | None:
    """Return an actionable hint for well-known rsync failures."""
    lowered = output.lower()
    if "unrecognized option" in lowered or "unknown option" in lowered:
        return (
            "The local rsync does not support one of the options used. macOS ships "
            "openrsync (rsync 2.6.9 compatible); install a modern rsync with "
            "`brew install rsync` and make sure it comes first in your PATH."
        )
    if return_code == 255 or "could not resolve hostname" in lowered:
        return "Check that the host is online and reachable via `ssh user@host`."
    if "permission denied (publickey" in lowered:
        return "SSH authentication failed; check your SSH keys for this host."
    if "permission denied" in lowered:
        denied = lowered.count("permission denied")
        return (
            f"{denied} file(s)/folder(s) could not be read by the SSH user on the "
            "remote host. Everything readable was copied. Fix the ownership or "
            "permissions there, back up as the owning user, or exclude the paths "
            "(e.g. app caches) if you do not need them."
        )
    if "no such file or directory" in lowered:
        return "Check that the source path exists on the remote host."
    return None


def _strip_usage(output: str) -> str:
    """Drop the long rsync usage banner, keeping only the actual error lines."""
    lines = []
    for line in output.splitlines():
        if line.lstrip().lower().startswith("usage:"):
            break
        lines.append(line)
    return "\n".join(lines).strip() or output.strip()


class RsyncErrorModel(BaseModel):
    """Model to structure and validate Rsync error details."""

    message: str = Field(..., description="A brief error message.")
    return_code: int = Field(..., description="Exit code from rsync.")
    output: str = Field(..., description="Detailed error output from rsync.")
    command: str = Field("", description="The command that was executed.")
    log_file: str = Field("", description="rsync --log-file path, if any.")


class RsyncError(Exception):
    """Custom exception for rsync-related errors."""

    def __init__(self, error_data: dict):
        try:
            self.error_details = RsyncErrorModel(**error_data)
        except ValidationError as e:
            raise ValueError(f"Invalid RsyncError data: {e}") from e
        super().__init__(self.summary)

    @property
    def summary(self) -> str:
        """One-line description of the failure."""
        code = self.error_details.return_code
        meaning = RSYNC_EXIT_CODES.get(code)
        reason = f" ({meaning})" if meaning else ""
        return f"{self.error_details.message}: exit code {code}{reason}"

    def __str__(self):
        details = self.error_details
        parts = [self.summary]
        lines = [ln for ln in _strip_usage(details.output).splitlines() if ln.strip()]
        if lines:
            shown = lines[:MAX_ERROR_LINES]
            hidden = len(lines) - len(shown)
            if hidden:
                where = (
                    f"see {details.log_file}"
                    if details.log_file
                    else "full output above"
                )
                shown.append(f"... and {hidden} more line(s) ({where})")
            parts.append("  rsync said: " + "\n              ".join(shown))
        if details.command:
            parts.append(f"  command:    {details.command}")
        hint = _rsync_hint(details.return_code, details.output)
        if hint:
            parts.append(f"  hint:       {hint}")
        return "\n".join(parts)


@functools.lru_cache(maxsize=None)
def _progress_args(rsync_bin: str = "rsync") -> tuple[str, ...]:
    """Pick the best progress option supported by the local rsync.

    `--info=progress2` needs rsync >= 3.1; older versions and macOS openrsync
    only understand `--progress`.
    """
    try:
        result = subprocess.run(
            [rsync_bin, "--info=progress2", "--version"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0:
            return ("--info=progress2",)
    except (OSError, subprocess.SubprocessError):
        pass
    logging.warning(
        "The local rsync does not support --info=progress2; falling back to "
        "--progress. Install rsync >= 3.1 (e.g. `brew install rsync`) for "
        "overall progress reporting."
    )
    return ("--progress",)


class CommandExecutor(BaseModel):
    """Utility class to execute shell commands with real-time progress."""

    log_level: str = Field("INFO", description="Logging level for the executor.")
    verify_backup: bool = Field(
        False, description="Activate checksum verification in the rsync command."
    )
    resume_backup: bool = Field(
        False,
        description="If enabled, incomplete files are kept at the destination, "
        "allowing the command to be resumed from where it left off instead"
        "of starting from zero.",
    )
    dry_run: bool = Field(
        False,
        description="If True, simulate the backup operations without making any changes "
        "or writing files. Useful for testing or validating the backup process.",
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
            extra_args.append("--checksum")
        if self.resume_backup:
            extra_args.append("--partial")
        if self.dry_run:
            extra_args.append("--dry-run")
        return [
            "rsync",
            "--archive",
            "--compress",
            f"--log-file={log_file}",
            *_progress_args(),
            "--delete",
            *extra_args,
            src,
            dst.as_posix(),
        ]

    def execute_command(self, command: list[str]) -> None:
        """Execute a shell command and handle errors."""
        self._configure_logging()
        command_str = shlex.join(command)
        log_file = next(
            (a.split("=", 1)[1] for a in command if a.startswith("--log-file=")), ""
        )
        logging.debug("#### Executing command: %s", command_str)

        if shutil.which(command[0]) is None:
            raise RsyncError(
                {
                    "message": f"'{command[0]}' executable not found",
                    "return_code": 127,
                    "output": "",
                    "command": command_str,
                }
            )

        try:
            # pylint: disable=consider-using-with
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # rsync may print file names that are not valid UTF-8; never let
                # display decoding abort a backup.
                encoding="utf-8",
                errors="replace",
                shell=False,
                bufsize=1,
            )
            # Drain stderr concurrently so a chatty rsync cannot fill the pipe
            # buffer and deadlock while we are reading stdout.
            stderr_chunks: list[str] = []
            stderr_pipe = process.stderr
            stderr_reader = threading.Thread(
                target=lambda: stderr_chunks.append(
                    stderr_pipe.read() if stderr_pipe else ""
                ),
                daemon=True,
            )
            stderr_reader.start()

            if process.stdout:
                width = shutil.get_terminal_size().columns - 1
                for line in process.stdout:
                    # \r returns to column 0 and \x1b[K clears leftovers from a
                    # longer previous line; truncating avoids wrapping.
                    sys.stdout.write(f"\r\x1b[K{line.strip()[-width:]}")
                    sys.stdout.flush()

            process.wait()
            stderr_reader.join()
            sys.stdout.write("\n")

            if process.returncode != 0:
                stderr_output = "".join(stderr_chunks)
                raise RsyncError(
                    {
                        "message": "Command execution failed",
                        "return_code": process.returncode,
                        "output": stderr_output.strip(),
                        "command": command_str,
                        "log_file": log_file,
                    }
                )
        except subprocess.SubprocessError as e:
            raise RsyncError(
                {
                    "message": "Subprocess execution failed",
                    "return_code": -1,
                    "output": str(e),
                    "command": command_str,
                }
            ) from e
