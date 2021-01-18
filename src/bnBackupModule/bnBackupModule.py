from __future__ import print_function
import os
import json
import shutil
import logging
import warnings
import subprocess
import datetime
import numpy as np

class bnBackupModule(object):

    def __init__(self, json_file, backup_directory_path):
        logging.info('## Welcome to the Backup System Management ##')
        self.host_list = []
        self.json_file = {}
        self.backup_dirs = {}
        for state in ['current', 'previous']:
            self.backup_dirs[state] = os.path.join(backup_directory_path, state)
        self.json_file['current'] = json_file
        self.json_file['previous'] = os.path.join(self.backup_dirs['current'], os.path.basename(json_file))
        logging.info('## The backup directory is %s', backup_directory_path)
        self.logs_path = os.path.join(backup_directory_path, 'logs')
        if (not os.path.isdir(self.logs_path)):
            os.makedirs(self.logs_path)
        self.load_info()

    def rsync_conf(self):
        for computer in self.host_list:
            host = computer[0]
            home = "home" if computer[1]=="linux" else "Users"
            user = computer[2]
            logging.info('## Backup of the configuration of %s', host)
            path_to_host =  os.path.join(self.backup_dirs['current'], '%s-%s'%(host, user))
            if (not os.path.isdir(path_to_host)):
                os.makedirs(path_to_host)
            cmd ='rsync --archive --verbose --human-readable --itemize-changes --progress \
            --delete %s@%s:/etc/hosts  %s/hosts 2>&1 > %s/rsync-output-conf-hosts-%s.txt '%(user, host, path_to_host, self.logs_path, user)
            subprocess.run(cmd, shell=True, universal_newlines=True, check=True)
            cmd ='rsync --archive --verbose --human-readable --itemize-changes --progress \
            --delete %s@%s:/etc/motd  %s/motd 2>&1 > %s/rsync-output-conf-motd-%s.txt'%(user, host, path_to_host, self.logs_path, user)
            subprocess.run(cmd, shell=True, universal_newlines=True, check=True)
            path_to_home_conf =  os.path.join(path_to_host, user)
            if (not os.path.isdir(path_to_home_conf)):
                os.makedirs(path_to_home_conf)
            cmd ='rsync --archive --verbose --exclude ".Trash" --exclude ".cache" --human-readable --itemize-changes --progress \
            --delete %s@%s:/%s/%s/.[^.]*  %s 2>&1 > %s/rsync-output-conf-%s.txt'%(user, host, home, user, path_to_home_conf, self.logs_path, user)
            subprocess.run(cmd, shell=True, universal_newlines=True, check=True)

        
    def rsync_modules(self, bkp_conf = True):
        self.finding_missing_modules()
        if (not os.path.isdir(self.backup_dirs['current'])):
            os.makedirs(self.backup_dirs['current'])
        for (k, v) in self.json_info['current'].items():
            logging.info('## I am starting backup of %s', k)
            user = v['user']
            host = v['host']
            host_os = v['os']
            self.host_list.append([host, host_os, user])
            src_path = v['src_path']
            logging.info('Backup for the user:host:  %s:%s ', user, host)
            logging.info('In the following source path %s', src_path)
            cmd = 'rsync --archive --verbose --human-readable --itemize-changes --progress \
            --delete %s@%s:%s %s/%s 2>&1 > %s/rsync-output-%s.txt'% (user, host, src_path, self.backup_dirs['current'], k, self.logs_path, k)
            subprocess.run(cmd, shell=True, universal_newlines=True, check=True)
            logging.info("## The backup of %s is done!", k)
        if (bkp_conf):
            self.host_list = np.unique(self.host_list, axis=0)
            self.rsync_conf()
        shutil.copy(self.json_file['current'],self.backup_dirs['current'])
        self.write_date()

    def finding_missing_modules(self):
        if ('previous' in self.json_info) and (not self.json_info['previous'].items() <= self.json_info['current'].items()):
            if (not os.path.isdir(self.backup_dirs['previous'])):
                os.makedirs(self.backup_dirs['previous'])
            modules = self.json_info['previous'].keys() - self.json_info['current']
            for module in modules:
                logging.info("## Moving %s ...", module)
                src_dir = os.path.join(self.backup_dirs['current'], module)
                dst_dir = os.path.join(self.backup_dirs['previous'], module)
                if os.path.isdir(dst_dir):
                    shutil.rmtree(dst_dir)
                shutil.move(src_dir, dst_dir)
            shutil.copy(self.json_file['previous'],self.backup_dirs['previous'])
            shutil.copy(os.path.join(self.backup_dirs['current'],'backup_date.log'),self.backup_dirs['previous'])

    def load_info(self):
        self.json_info = {}
        for item in self.json_file.items():
            if os.path.isfile(item[1]):
                with open(item[1]) as f:
                    self.json_info[item[0]] = json.load(f)
    
    def write_date(self):
        date_format="%Y%m%d-%H%M%S"
        date_path = os.path.join(self.backup_dirs['current'],'backup_date.log')
        date_info = datetime.datetime.now().strftime(date_format)
        date_file = open( date_path, "w+")
        date_file.write(date_info)
        date_file.close