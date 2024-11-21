# -*- coding: utf-8 -*-
"""Command line script to upload a whole directory tree."""
import argparse
import cProfile as profile
import sys
from pathlib import Path

from loguru import logger as logging

from BackupOrchestrator import BackupOrchestrator

__author__ = ["Ariel Hernandez <ahestevenz@bleiben.ar>"]
__copyright__ = "Copyright 2024 Bleiben. All rights reserved."
__license__ = """Proprietary"""


def _main(config: BackupOrchestrator.BackupConfig):
    """Actual program (without command line parsing). This is so we can profile.

    Parameters
    ----------
    config : Config
        Configuration object containing validated arguments.
    """
    disksync = BackupOrchestrator.BackupOrchestrator(config=config)
    disksync.rsync_modules(save_conf=True)
    return 0


def main():
    """CLI for uploading the encrypted files."""
    argparser = argparse.ArgumentParser(
        description="Welcome to the Backup Orchestrator Management"
    )
    argparser.add_argument(
        "-j",
        "--json_file",
        help='JSON file with backup set points (default: "%(default)s")',
        default="/Users/ahestevenz/.userfiles/conf/backup.json",
    )
    argparser.add_argument(
        "-d",
        "--backup_directory",
        help='Destination directory (default: "%(default)s")',
        default="/Volumes/Datensicherung/Datensicherung/",
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
        config = BackupOrchestrator.BackupConfig(
            json_file=Path(args.json_file),
            backup_directory=Path(args.backup_directory),
            loglevel=loglevel,
        )
    except ValueError as e:
        print(f"Configuration Error: {e}")
        sys.exit(1)

    logging.remove()
    logging.add(sys.stdout, level=config.loglevel)

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
