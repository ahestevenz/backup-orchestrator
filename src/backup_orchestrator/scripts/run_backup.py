# -*- coding: utf-8 -*-
"""Command line script to upload a whole directory tree."""
import argparse
import cProfile as profile
import sys
from pathlib import Path

from loguru import logger as logging

from backup_orchestrator.backup_orchestrator import BackupConfig, BackupOrchestrator

__author__ = ["Ariel Hernandez <ahestevenz@bleiben.ar>"]
__copyright__ = "Copyright 2024 Bleiben. All rights reserved."


def _main(config: BackupConfig):
    """Actual program (without command line parsing). This is so we can profile.

    Parameters
    ----------
    config : Config
        Configuration object containing validated arguments.
    """
    disksync = BackupOrchestrator(config=config)
    disksync.rsync_modules(save_conf=True)
    return 0


def main():
    """CLI for uploading the encrypted files."""
    argparser = argparse.ArgumentParser(
        description="Welcome to the Backup Orchestrator Management"
    )
    argparser.add_argument(
        "-j",
        "--yaml_file",
        help='YAML file with backup set points (default: "%(default)s")',
        default="/Users/ahestevenz/.userfiles/conf/backup.yml",
    )
    argparser.add_argument(
        "-v",
        "--verbose",
        help="Increase logging output (default: INFO) (can be specified several times)",
        action="count",
        default=0,
    )
    argparser.add_argument(
        "-p",
        "--profile",
        help="Run with profiling and store output in given file",
        metavar="output.prof",
    )
    args = argparser.parse_args()

    _V_LEVELS = ["INFO", "DEBUG", "TRACE"]
    loglevel = _V_LEVELS[min(len(_V_LEVELS) - 1, args.verbose)]

    # Create Config instance with validated arguments
    try:
        config = BackupConfig(
            yaml_file=Path(args.yaml_file),
            log_level=loglevel,
        )
    except ValueError as e:
        print(f"Configuration Error: {e}")
        sys.exit(1)

    logging.remove()
    logging.add(sys.stdout, level=config.log_level)

    if args.profile:
        logging.info("Start profiling")
        profile.runctx(
            "_main(config)", globals(), {"config": config}, filename=args.profile
        )
        logging.info("Done profiling")
    else:
        logging.info("Running without profiling")
        _main(config)

    return 0


if __name__ == "__main__":
    exit(main())
