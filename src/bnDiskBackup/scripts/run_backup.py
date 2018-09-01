"""Command line script to upload a whole directory tree."""
from __future__ import print_function

from builtins import input
import argparse
import logging
import cProfile as profile
import getpass
import os
import datetime

# local 
from bnDiskBackup import bnDiskBackup

__author__ = [ "Ariel Hernandez <ariel.h.estevenz@ieee.org>" ]
__copyright__ = "Copyright 2018 ZoomAgri. All rights reserved."
__license__ = """Proprietary"""


def _main(args):
    """Actual program (without command line parsing). This is so we can profile.
    Parameters
    ----------
    args: namespace object as returned by ArgumentParser.parse_args()
    """

    disksync = bnDiskBackup.bnDiskBackup('/Users/ahestevenz/.userfiles/conf/backup.json')    
    disksync.rsync_modules()
    return 0


def main():
    """CLI for upload the encripted files"""

    # Module specific
    argparser = argparse.ArgumentParser(description='Upload images to the server.'
    'The user may or may not have RSA public key for the remote-host\n'
    'i.e: zoom-encryption-upload-dir -s . -d /mnt/shared/ZoomBarley/database-pixma/ -e .png.enc -z zcloud1 -u za', formatter_class=argparse.RawTextHelpFormatter)
    argparser.add_argument('-s', '--src_dir', help='Source Directory (default: "%(default)s")', required=False,
                          default="")
    argparser.add_argument('-d', '--dst_dir', help='Dest Directory (default: "%(default)s")', required=False,
                          default="")
    argparser.add_argument('-z', '--server', help='Upload to server, nullstring for local copy (default: "%(default)s")', required=False,
                          default="")
    argparser.add_argument('-e', '--extension', help='Upload only files with this extension (default: "%(default)s")', required=False,
                          default="")
    argparser.add_argument('-u', '--user', help='Connect to server using this username, nullstring for same local username (default: "%(default)s")', required=False,
                          default="")

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
