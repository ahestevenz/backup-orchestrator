"""Command line script to upload a whole directory tree."""
from __future__ import print_function

from builtins import input
import argparse
from loguru import logger as logging
import cProfile as profile
import shutil
import os, sys

# local 
from BackupOrchestrator import BackupOrchestrator

__author__ = [ "Ariel Hernandez <ahestevenz@bleiben.ar>" ]
__copyright__ = "Copyright 2020 Bleiben. All rights reserved."
__license__ = """Proprietary"""


def _main(args):
    """Actual program (without command line parsing). This is so we can profile.
    Parameters
    ----------
    args: namespace object as returned by ArgumentParser.parse_args()
    """
    disksync = BackupOrchestrator.BackupOrchestrator(args['json_file'], args['backup_directory'], args["loglevel"]) 
    disksync.rsync_modules(save_conf = True)
    
    return 0
    

def main():
    """CLI for upload the encripted files"""

    # Module specific
    argparser = argparse.ArgumentParser(description='Welcome to the Backup Module Management')
    argparser.add_argument('-j', '--json_file', help='JSON file with backup set points (default: "%(default)s")', required=False,
                          default='/Users/ahestevenz/.userfiles/conf/backup.json')
    argparser.add_argument('-d', '--backup_directory', help='Destination directory (default: "%(default)s")', required=False,
                          default='/Volumes/Datensicherung/Datensicherung/')

    # Default Args
    argparser.add_argument('-v', '--verbose', help='Increase logging output  (default: INFO)'
                            '(can be specified several times)', action='count', default=0)
    argparser.add_argument('-p', '--profile', help='Run with profiling and store '
                            'output in given file', metavar='output.prof')
    args = vars(argparser.parse_args())

    _V_LEVELS = ["INFO", "DEBUG", "TRACE"]
    args["loglevel"] = _V_LEVELS[min(len(_V_LEVELS)-1, args['verbose'])]
    logging.remove()
    logging.add(sys.stdout, level=args["loglevel"])

    if args['profile'] is not None:
        logging.info("Start profiling")
        r = 1
        profile.runctx("r = _main(args)", globals(), locals(), filename=args['profile'])
        logging.info("Done profiling")
    else:
        logging.info("Running without profiling")
        r = _main(args)

    return r

if __name__ == '__main__':
    exit(main())
