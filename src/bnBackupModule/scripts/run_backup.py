"""Command line script to upload a whole directory tree."""
from __future__ import print_function

from builtins import input
import argparse
import cProfile as profile
import logging
import datetime
import os

# local 
from bnBackupModule import bnBackupModule

__author__ = [ "Ariel Hernandez <ariel.h.estevenz@ieee.org>" ]
__copyright__ = "Copyright 2018 ZoomAgri. All rights reserved."
__license__ = """Proprietary"""


def _main(args):
    """Actual program (without command line parsing). This is so we can profile.
    Parameters
    ----------
    args: namespace object as returned by ArgumentParser.parse_args()
    """

    disksync = bnBackupModule.bnBackupModule(args['json_file'], args['backup_directory'])    
    disksync.rsync_modules()

    date_format="%Y%m%d-%H%M%S"
    date_path = os.path.join (args['backup_directory'],'backup_date.log')
    date_info = datetime.datetime.now().strftime(date_format)
    date_file = open( date_path, "w+")
    date_file.write(date_info)
    date_file.close

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
                            '(can be specified several times)', action='count', default=1)
    argparser.add_argument('-p', '--profile', help='Run with profiling and store '
                            'output in given file', metavar='output.prof')
    args = vars(argparser.parse_args())

    FORMAT = '%(asctime)s - %(levelname)s - %(module)s - %(funcName)s - %(lineno)d - %(message)s'
    _V_LEVELS = [logging.INFO, logging.DEBUG]
    loglevel = min(len(_V_LEVELS)-1, args['verbose'])
    logging.basicConfig(format=FORMAT, level = _V_LEVELS[loglevel])

    if args['profile'] is not None:
        logging.info("Start profiling")
        r = 1
        profile.runctx("r = _main(args)", globals(), locals(), filename=args['profile'])
        logging.info("Done profiling")
    else:
        logging.info("Running without profiling")
        r = _main(args)

    logging.shutdown()

    return r

if __name__ == '__main__':
    exit(main())
