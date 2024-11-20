 # TODO:
# Sanity check for each computer
# Sanity check for every dst directory
# Handle network issues
# Handle current/previous directories with different dst directories
# Can we recofigure SSH connections if they are missing?
# Verify the backup

from typing import List, Dict
from pathlib import Path
import json
import shutil
import subprocess
import datetime
from loguru import logger as logging
from pydantic import BaseModel, Field, ValidationError


class HostInfo(BaseModel):
    """Represents information about a host for backup."""
    user: str
    host: str
    os: str
    src_path: str


class BackupConfig(BaseModel):
    """Represents the backup configuration from a JSON file."""
    modules: Dict[str, HostInfo]


class BackupOrchestrator:
    def __init__(self, json_file: str, backup_dir: str, log_level: str = "INFO"):
        logging.info("## Welcome to the Backup System Management ##")
        self.backup_dirs = {
            "current": Path(backup_dir) / "current",
            "previous": Path(backup_dir) / "previous",
        }
        self.json_file = {
            "current": Path(json_file),
            "previous": self.backup_dirs["current"] / Path(json_file).name,
        }
        self.logs_dir = Path(backup_dir) / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.host_list: List[HostInfo] = []
        self.log_level = log_level
        self.json_info: Dict[str, BackupConfig] = {}

        self._load_backup_info()

    def _load_backup_info(self):
        """Load and validate backup configuration from JSON files."""
        logging.debug("#### Loading JSON file information.")
        for key, file_path in self.json_file.items():
            if file_path.is_file():
                with file_path.open() as f:
                    try:
                        self.json_info[key] = BackupConfig(modules=json.load(f))
                    except ValidationError as e:
                        logging.error(f"Invalid backup configuration in {file_path}: {e}")
                        raise
            else:
                self.json_info[key] = BackupConfig(modules={})

    def _write_backup_date(self):
        """Write the current backup date to a log file."""
        date_format = "%Y%m%d-%H%M%S"
        date_path = self.backup_dirs["current"] / "backup_date.log"
        date_info = datetime.datetime.now().strftime(date_format)
        date_path.write_text(date_info)
        logging.debug(f"#### Backup date written: {date_info}")

    def _prepare_directory(self, path: Path):
        """Ensure a directory exists."""
        path.mkdir(parents=True, exist_ok=True)

    def _get_rsync_command(self, src: str, dst: str, log_file: Path, extra_args: str = "") -> str:
        """Construct the rsync command."""
        if self.log_level == "DEBUG":
            extra_args += " --stats"
        return f"rsync --archive --compress --log-file={log_file} --info=progress2 --delete {extra_args} {src} {dst}"

    def _execute_command(self, command: str):
        """Execute a shell command using subprocess."""
        logging.debug(f"#### Executing command: {command}")
        with subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
            for line in process.stdout:
                print(line, end="")

    def _move_missing_modules(self):
        """Identify and move missing modules from current to previous backup."""
        if "previous" in self.json_info and self.json_info["previous"].modules != self.json_info["current"].modules:
            self._prepare_directory(self.backup_dirs["previous"])
            missing_modules = set(self.json_info["previous"].modules) - set(self.json_info["current"].modules)
            for module in missing_modules:
                logging.info(f"## Moving missing module: {module}")
                src_dir = self.backup_dirs["current"] / module
                dst_dir = self.backup_dirs["previous"] / module
                if dst_dir.is_dir():
                    shutil.rmtree(dst_dir)
                if src_dir.exists():
                    shutil.move(src_dir, dst_dir)
            shutil.copy(self.json_file["previous"], self.backup_dirs["previous"])
            shutil.copy(self.backup_dirs["current"] / "backup_date.log", self.backup_dirs["previous"])

    def _backup_host_configuration(self, host_info: HostInfo):
        """Backup configuration files and home directory for a specific host."""
        home_dir = "home" if host_info.os == "linux" else "Users"
        host_path = self.backup_dirs["current"] / f"{host_info.user}-{host_info.host}"
        self._prepare_directory(host_path)

        # Backup /etc configuration files
        etc_files = ["motd", "hosts"]
        for file in etc_files:
            cmd = self._get_rsync_command(
                src=f"{host_info.user}@{host_info.host}:/etc/{file}",
                dst=host_path / "hosts",
                log_file=self.logs_dir / f"rsync-output-conf-hosts-{host_info.user}.txt",
            )
            self._execute_command(cmd)

        # Backup home directory
        home_conf_path = host_path / host_info.user
        self._prepare_directory(home_conf_path)
        cmd = self._get_rsync_command(
            src=f"{host_info.user}@{host_info.host}:/{home_dir}/{host_info.user}/.[^.]*",
            dst=home_conf_path,
            log_file=self.logs_dir / f"rsync-output-conf-{host_info.user}.txt",
            extra_args="--exclude '.Trash' --exclude '.cache'",
        )
        self._execute_command(cmd)

    def rsync_modules(self, save_conf: bool = True):
        """Perform backup of all modules."""
        self._move_missing_modules()
        self._prepare_directory(self.backup_dirs["current"])

        for module_name, host_info in self.json_info["current"].modules.items():
            logging.info(f"## Starting backup for module: {module_name}")
            self.host_list.append(host_info)

            cmd = self._get_rsync_command(
                src=f"{host_info.user}@{host_info.host}:{host_info.src_path}",
                dst=self.backup_dirs["current"] / module_name,
                log_file=self.logs_dir / f"rsync-output-{module_name}.txt",
            )
            self._execute_command(cmd)
            logging.success(f"## Backup completed for module: {module_name}")

        if save_conf:
            unique_hosts = {f"{h.user}@{h.host}" for h in self.host_list}
            for host in unique_hosts:
                host_info = next(h for h in self.host_list if f"{h.user}@{h.host}" == host)
                self._backup_host_configuration(host_info)

        shutil.copy(self.json_file["current"], self.backup_dirs["current"])
        self._write_backup_date()


# from __future__ import print_function
# from typing import Tuple, Dict, List
# import os
# import json
# import shutil
# from loguru import logger as logging
# import subprocess
# import datetime
# import numpy as np
# from pathlib import Path

# class bnBackupModule(object):

#     def __init__(self, json_file:str, backup_directory_path:str, log_level:str):
#         logging.info('## Welcome to the Backup System Management ##')
#         logging.info(f'## The backup directory is {backup_directory_path}')
#         self.host_list = []
#         self.json_file = {}
#         self.backup_dirs = {}
#         for state in ['current', 'previous']:
#             self.backup_dirs[state] = Path(backup_directory_path)/Path(state)
#         self.json_file['current'] = Path(json_file)
#         self.json_file['previous'] = self.backup_dirs['current']/self.json_file['current'].name
#         self.logs_path = Path(backup_directory_path)/Path('logs')
#         self.logs_path.mkdir(parents=True, exist_ok=True)
#         self.log_level = log_level
#         self.load_info()
    
#     def get_command(self, 
#                     src:str, 
#                     dst:str,
#                     log:str,
#                     extra_args:str = ""):
#         if self.log_level == "DEBUG":
#             extra_args += " --stats"
#         cmd =f"rsync --archive --compress --log-file={log} --info=progress2 --delete {extra_args} {src} {dst}"
#         return cmd

#     def run_subprocess(self, cmd:str):
#         with subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=0, shell=True) as p:
#             char = p.stdout.read(1)
#             while char != b'':
#                 print(char.decode('UTF-8'), end='', flush=True)
#                 char = p.stdout.read(1)
#         logging.debug(f'#### Running {cmd}')

#     def rsync_conf(self):
#         self.host_list = np.unique(self.host_list, axis=0)
#         for computer in self.host_list:
#             host, user = computer[0], computer[2]
#             home = "home" if computer[1] == "linux" else "Users"
#             logging.info(f'## Backup of the configuration of {user}@{host}')
#             path_to_host = self.backup_dirs['current']/Path(f'{user}-{host}')
#             path_to_host.mkdir(parents=False, exist_ok=True)
#             for file in ['motd', 'hosts']:
#                 cmd = self.get_command(f'{user}@{host}:/etc/{file}',
#                                        f'{path_to_host}/hosts',
#                                        f'{self.logs_path}/rsync-output-conf-hosts-{user}.txt')
#                 self.run_subprocess(cmd)
#             path_to_home_conf = path_to_host/Path(user)
#             path_to_home_conf.mkdir(parents=False, exist_ok=True)
#             cmd = self.get_command(f'{user}@{host}:/{home}/{user}/.[^.]*',
#                                    path_to_home_conf,
#                                    f'{self.logs_path}/rsync-output-conf-{user}.txt',
#                                    f'--exclude ".Trash" --exclude ".cache"')
#             self.run_subprocess(cmd)

#     def rsync_modules(self, save_conf:bool = True):
#         self.finding_missing_modules()
#         self.backup_dirs['current'].mkdir(parents=False, exist_ok=True)
#         for (k, v) in self.json_info['current'].items():
#             logging.info(f'## I am starting backup of {k}')
#             user, host, host_os = v['user'], v['host'], v['os']
#             self.host_list.append([host, host_os, user])
#             src_path = v['src_path']
#             logging.info(f'Backup for the user:host:  {user}:{host}')
#             logging.info(f'In the following source path {src_path}')
#             cmd = self.get_command(f'{user}@{host}:{src_path}',
#                                    f'{self.backup_dirs["current"]}/{k}',
#                                    f'{self.logs_path}/rsync-output-{k}.txt')
#             self.run_subprocess(cmd)
#             logging.success(f"## The backup of {k} is done!")
#         if (save_conf):
#             self.rsync_conf()
#         shutil.copy(self.json_file['current'], self.backup_dirs['current'])
#         self.write_date()

#     def finding_missing_modules(self):
#         if ('previous' in self.json_info) and (not self.json_info['previous'].items() <= self.json_info['current'].items()):
#             self.backup_dirs['previous'].mkdir(parents=False, exist_ok=True)
#             modules = self.json_info['previous'].keys() - self.json_info['current']
#             for module in modules:
#                 logging.info(f"## Moving {module} ...")
#                 src_dir = self.backup_dirs['current']/Path(module)
#                 dst_dir = self.backup_dirs['previous']/Path(module)
#                 if os.path.isdir(dst_dir):
#                     shutil.rmtree(dst_dir)
#                 shutil.move(src_dir, dst_dir)
#             shutil.copy(self.json_file['previous'],self.backup_dirs['previous'])
#             shutil.copy(self.backup_dirs['current']/Path('backup_date.log'),self.backup_dirs['previous'])

#     def load_info(self):
#         self.json_info = {}
#         logging.debug(f'#### Loading json file from {self.json_file["current"]}')
#         for item in self.json_file.items():
#             if os.path.isfile(item[1]):
#                 with open(item[1]) as f:
#                     self.json_info[item[0]] = json.load(f)
    
#     def write_date(self):
#         date_format="%Y%m%d-%H%M%S"
#         date_path = self.backup_dirs['current']/Path('backup_date.log')
#         date_info = datetime.datetime.now().strftime(date_format)
#         date_file = open( date_path, "w+")
#         logging.debug(f'#### Date: {date_info}')
#         date_file.write(date_info)
#         logging.debug(f'#### Date was written in {date_path}')
#         date_file.close