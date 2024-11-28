# Backup Orchestrator

**bn-backup-orchestrator** is a python package which makes backups based on modules written in a YAML file.

## BackupOrchestrator

Python class that sync directories and files specified in a YAML file. This class uses methods based on RSYNC command with several arguments.


## Installation
### Requirements

#### Python environment

It is highly recomomended to run the backup command inside of python environment, in case the system does not have any use the following procedure (check [Virtualenvwrapper Installation](https://virtualenvwrapper.readthedocs.io/en/latest/install.html) for more details).

```setup
$ pip install --user virtualenvwrapper virtualenv
```

Add three lines to your shell startup file (.bashrc, .profile, etc.) to set the location where the virtual environments should live:

```
export WORKON_HOME=$HOME/.virtualenvs
export PROJECT_HOME=$HOME/Devel
source /usr/local/bin/virtualenvwrapper.sh
```

After editing it, reload the startup file (e.g., run `source ~/.bashrc`) and create a python environment:

```
$ mkvirtualenv venv_py
$ workon venv_py
```

#### Installing the package

Once the python environment was configured, run the following procedure to install all the required packages
```setup
(venv_py)$ git clone https://github.com/ahestevenz/backup-orchestrator.git
(venv_py)$ cd backup-orchestrator
(venv_py)$ pip install .
```

### Start your backup process

![](./assets/run-bn-backup.gif)

```run
> bn-run-backup -h
usage: bn-run-backup [-h] [-j YAML_FILE] [-v] [-p output.prof]

Welcome to the Backup Orchestrator Management

options:
  -h, --help            show this help message and exit
  -j YAML_FILE, --yaml_file YAML_FILE
                        YAML file with backup set points (default: "/Users/ahestevenz/.userfiles/conf/backup.yaml")
  -v, --verbose         Increase logging output (default: INFO) (can be specified several times)
  -p output.prof, --profile output.prof
                        Run with profiling and store output in given file
```

The command *bn-run-backup* uses only one argument to backup your system:
* The YAML configuration file

The YAML file specifies the modules which will be syncronized, and it must be written with the format described below.
```
settings:
  backup_directory: "/path/to/backup"
  verify_backup: false

modules:
  dir1-ahe:
    src_path: "/Users/ahestevenz/dir1"
    user: "ahestevenz"
    host: "galactica"
    os: "darwin"

  dir2-ahe:
    src_path: "/Users/ahestevenz/dir2"
    user: "ahestevenz"
    host: "galactica"
    os: "darwin"

  dir3-ahe:
    src_path: "/home/ahestevenz/dir3"
    user: "ahestevenz"
    host: "columbia"
    os: "linux"
```

Finally, only need to run (as an example):

```run
~/De/t/1/backup-orchestrator on release/r1 !1 ?1 > bn-run-backup  -j /Users/ahestevenz/.userfiles/conf/backup_test.yml
```

## TODO List
- [x] Add Docker container option
