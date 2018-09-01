from __future__ import print_function
# from builtins import input
# from builtins import range
# from builtins import object
# import struct
# import hashlib
# from random import choice
# from string import ascii_lowercase
import os
import json
import shutil
import logging
import warnings
import subprocess

class bnDiskBackup(object):

    def __init__(self, json_file):
        self.json_file = json_file
        self.load_info()
        
    def rsync_modules(self):
        cmd = 'ping pegasus'        
        for (k, v) in self.json_info.items():
            print('I am starting backup of', k)
            logging.info('I am starting backup of %s', k)
            cmd = 'ping pegasus'
            ping = subprocess.run(cmd, shell=True, universal_newlines=True, check=True)
            print(ping.stdout)

            
            # print(k)
            # print(v['host'])
            # print(v['user'])

    def load_info(self):
        with open(self.json_file) as f:
            self.json_info = json.load(f)            
    
    def query_yes_no(self, question, default_answer=None):
        '''Ask a yes/no question via raw_input() and return their answer.
        "question" is a string that is presented to the user.
        "default_answer" is the presumed answer if the user just hits <Enter>.
            It must be "yes", "no" or None (meaning
            an answer is required of the user).

        The "answer" return value is True for "yes" or False for "no".
        '''
        valid = {'yes': True, 'y': True, 'ye': True,
                'no': False, 'n': False}
        if default_answer is None:
            prompt = ' [y/n] '
        elif default_answer == 'yes':
            prompt = ' [Y/n] '
        elif default_answer == 'no':
            prompt = ' [y/N] '
        else:
            raise ValueError('invalid default answer: "%s"' % default_answer)

        while True:
            # sys.stdout.write(question + prompt)
            print((question + prompt), end=' ')
            choice = input().lower()
            if default_answer is not None and choice == '':
                return valid[default_answer]
            elif choice in valid:
                return valid[choice]
            else:
                print('Please respond with "yes" or "no" (or "y" or "n").', end=' ')
    
    
