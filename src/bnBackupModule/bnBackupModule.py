from __future__ import print_function
from typing import Tuple, Dict, List
import os
import json
import shutil
from loguru import logger as logging
import subprocess
import datetime
import numpy as np
from pathlib import Path

class bnBackupModule(object):

    def __init__(self, json_file:str, backup_directory_path:str, log_level:str):
        logging.info('## Welcome to the Backup System Management ##')
        logging.info(f'## The backup directory is {backup_directory_path}')
        self.host_list = []
        self.json_file = {}
        self.backup_dirs = {}
        for state in ['current', 'previous']:
            self.backup_dirs[state] = Path(backup_directory_path)/Path(state)
        self.json_file['current'] = Path(json_file)
        self.json_file['previous'] = self.backup_dirs['current']/self.json_file['current'].name
        self.logs_path = Path(backup_directory_path)/Path('logs')
        self.logs_path.mkdir(parents=True, exist_ok=True)
        self.log_level = log_level
        self.load_info()

    def get_command(self, 
                    src:str, 
                    dst:str,
                    log:str,
                    extra_args:str = ""):
        if self.log_level == "DEBUG":
            extra_args += " --stats"
        cmd =f"rsync --archive --compress --log-file={log} --info=progress2 --delete {extra_args} {src} {dst}"
        return cmd

    def run_subprocess(self, cmd:str):
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=0, shell=True) as p:
            char = p.stdout.read(1)
            while char != b'':
                print(char.decode('UTF-8'), end='', flush=True)
                char = p.stdout.read(1)
        logging.debug(f'#### Running {cmd}')

    def rsync_conf(self):
        self.host_list = np.unique(self.host_list, axis=0)
        for computer in self.host_list:
            host, user = computer[0], computer[2]
            home = "home" if computer[1] == "linux" else "Users"
            logging.info(f'## Backup of the configuration of {user}@{host}')
            path_to_host = self.backup_dirs['current']/Path(f'{user}-{host}')
            path_to_host.mkdir(parents=False, exist_ok=True)
            for file in ['motd', 'hosts']:
                cmd = self.get_command(f'{user}@{host}:/etc/{file}',
                                       f'{path_to_host}/hosts',
                                       f'{self.logs_path}/rsync-output-conf-hosts-{user}.txt')
                self.run_subprocess(cmd)
            path_to_home_conf = path_to_host/Path(user)
            path_to_home_conf.mkdir(parents=False, exist_ok=True)
            cmd = self.get_command(f'{user}@{host}:/{home}/{user}/.[^.]*',
                                   path_to_home_conf,
                                   f'{self.logs_path}/rsync-output-conf-{user}.txt',
                                   f'--exclude ".Trash" --exclude ".cache"')
            self.run_subprocess(cmd)

    def rsync_modules(self, save_conf:bool = True):
        self.finding_missing_modules()
        self.backup_dirs['current'].mkdir(parents=False, exist_ok=True)
        for (k, v) in self.json_info['current'].items():
            logging.info(f'## I am starting backup of {k}')
            user, host, host_os = v['user'], v['host'], v['os']
            self.host_list.append([host, host_os, user])
            src_path = v['src_path']
            logging.info(f'Backup for the user:host:  {user}:{host}')
            logging.info(f'In the following source path {src_path}')
            cmd = self.get_command(f'{user}@{host}:{src_path}',
                                   f'{self.backup_dirs["current"]}/{k}',
                                   f'{self.logs_path}/rsync-output-{k}.txt')
            self.run_subprocess(cmd)
            logging.info(f"## The backup of {k} is done!")
        if (save_conf):
            self.rsync_conf()
        shutil.copy(self.json_file['current'], self.backup_dirs['current'])
        self.write_date()

    def finding_missing_modules(self):
        if ('previous' in self.json_info) and (not self.json_info['previous'].items() <= self.json_info['current'].items()):
            self.backup_dirs['previous'].mkdir(parents=False, exist_ok=True)
            modules = self.json_info['previous'].keys() - self.json_info['current']
            for module in modules:
                logging.info(f"## Moving {module} ...")
                src_dir = self.backup_dirs['current']/Path(module)
                dst_dir = self.backup_dirs['previous']/Path(module)
                if os.path.isdir(dst_dir):
                    shutil.rmtree(dst_dir)
                shutil.move(src_dir, dst_dir)
            shutil.copy(self.json_file['previous'],self.backup_dirs['previous'])
            shutil.copy(self.backup_dirs['current']/Path('backup_date.log'),self.backup_dirs['previous'])

    def load_info(self):
        self.json_info = {}
        logging.debug(f'#### Loading json file from {self.json_file["current"]}')
        for item in self.json_file.items():
            if os.path.isfile(item[1]):
                with open(item[1]) as f:
                    self.json_info[item[0]] = json.load(f)
    
    def write_date(self):
        date_format="%Y%m%d-%H%M%S"
        date_path = self.backup_dirs['current']/Path('backup_date.log')
        date_info = datetime.datetime.now().strftime(date_format)
        date_file = open( date_path, "w+")
        logging.debug(f'#### Date: {date_info}')
        date_file.write(date_info)
        logging.debug(f'#### Date was written in {date_path}')
        date_file.close