from __future__ import print_function
from typing import Tuple, Dict, List
import os
import json
import shutil
from loguru import logger as logging
import subprocess
import datetime
import numpy as np
import shlex
from pathlib import Path

class bnBackupModule(object):

    def __init__(self, json_file:str, backup_directory_path:str):
        logging.info('## Welcome to the Backup System Management ##')
        logging.info(f'## The backup directory is {backup_directory_path}')
        self.host_list = []
        self.json_file = {}
        self.backup_dirs = {}
        for state in ['current', 'previous']:
            # self.backup_dirs[state] = os.path.join(backup_directory_path, state)
            self.backup_dirs[state] = Path(backup_directory_path)/Path(state)
        self.json_file['current'] = Path(json_file)
        self.json_file['previous'] = self.backup_dirs['current']/self.json_file['current'].name
        self.logs_path = Path(backup_directory_path)/Path('logs')
        self.logs_path.mkdir(parents=True, exist_ok=True)
        self.load_info()

    def get_command(self, 
                    src:str, 
                    dst:str,
                    log:str,
                    extra_args:str = ""):
        cmd =f"rsync --archive --verbose --human-readable --itemize-changes --info=progress2 \
                --delete {extra_args} {src} {dst} 2>&1 > {log}"
        return cmd

    def run_command(self, command):
        process = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE)
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(output.strip())
        rc = process.poll()
        return rc

    def run_subprocess(self, cmd:str):
        subprocess.run(cmd, shell=True, universal_newlines=True, check=True)
        logging.debug(f'#### Running {cmd}')

    def rsync_conf(self):
        self.host_list = np.unique(self.host_list, axis=0)
        for computer in self.host_list:
            host, user = computer[0], computer[2]
            home = "home" if computer[1] == "linux" else "Users"
            logging.info(f'## Backup of the configuration of {user}@{host}')
            # path_to_host =  os.path.join(self.backup_dirs['current'], f'{user}-{host}') 
            # if (not os.path.isdir(path_to_host)):
            #     os.makedirs(path_to_host)
            path_to_host = self.backup_dirs['current']/Path(f'{user}-{host}')
            path_to_host.mkdir(parents=False, exist_ok=True)
            for file in ['motd', 'hosts']:
                cmd = self.get_command(f'{user}@{host}:/etc/{file}',
                                       f'{path_to_host}/hosts',
                                       f'{self.logs_path}/rsync-output-conf-hosts-{user}.txt')
                # cmd =f"rsync --archive --verbose --human-readable --itemize-changes --progress \
                # --delete {user}@{host}:/etc/{file}  {path_to_host}/hosts 2>&1 > {self.logs_path}/rsync-output-conf-hosts-{user}.txt"
                self.run_command(cmd)
            # path_to_home_conf =  os.path.join(path_to_host, user)
            # if (not os.path.isdir(path_to_home_conf)):
            #     os.makedirs(path_to_home_conf)
            path_to_home_conf = path_to_host/Path(user)
            path_to_home_conf.mkdir(parents=False, exist_ok=True)
            cmd = self.get_command(f'{user}@{host}:/{home}/{user}/.[^.]*',
                                   path_to_home_conf,
                                   f'{self.logs_path}/rsync-output-conf-{user}.txt',
                                   f'--exclude ".Trash" --exclude ".cache"')
            # cmd =f"rsync --archive --verbose --exclude '.Trash' --exclude '.cache' --human-readable --itemize-changes --progress \
            # --delete {user}@{host}:/{home}/{user}/.[^.]*  {path_to_home_conf} 2>&1 > {self.logs_path}/rsync-output-conf-{user}.txt"
            self.run_command(cmd)

    # TODO Add tqdm or "in progress" information
    def rsync_modules(self, save_conf:bool = True):
        self.finding_missing_modules()
        self.backup_dirs['current'].mkdir(parents=False, exist_ok=True)
        # if (not os.path.isdir(self.backup_dirs['current'])):
        #     os.makedirs(self.backup_dirs['current'])
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
            # cmd = f"rsync --archive --verbose --human-readable --itemize-changes --progress \
            # --delete {user}@{host}:{src_path} {self.backup_dirs['current']}/{k} 2>&1 > {self.logs_path}/rsync-output-{k}.txt"
            self.run_command(cmd)
            logging.info(f"## The backup of {k} is done!")
        if (save_conf):
            self.rsync_conf()
        shutil.copy(self.json_file['current'], self.backup_dirs['current'])
        self.write_date()

    def finding_missing_modules(self):
        if ('previous' in self.json_info) and (not self.json_info['previous'].items() <= self.json_info['current'].items()):
            self.backup_dirs['previous'].mkdir(parents=False, exist_ok=True)
            # if (not os.path.isdir(self.backup_dirs['previous'])):
            #     os.makedirs(self.backup_dirs['previous'])
            modules = self.json_info['previous'].keys() - self.json_info['current']
            for module in modules:
                logging.info(f"## Moving {module} ...")
                # src_dir = os.path.join(self.backup_dirs['current'], module)
                # dst_dir = os.path.join(self.backup_dirs['previous'], module)
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