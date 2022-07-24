# Backup Module System

**bn-backup-module** is a python package which makes backups based on modules written in a JSON file. 

## bnBackupModule

Python class that sync directories and files specified in a JSON file. This class uses methods based on RSYNC command with several arguments.


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
(venv_py)$ git clone https://github.com/ahestevenz/backup-module
(venv_py)$ cd backup-module
(venv_py)$ pip install .
```

### Start your backup process

```run
(venv_py39) ahestevenz@galactica:~/dev/backup-module(dev⚡) » bn-run-backup -h                                 
usage: bn-run-backup [-h] [-j JSON_FILE] [-d BACKUP_DIRECTORY] [-v] [-p output.prof]

Welcome to the Backup Module Management

optional arguments:
  -h, --help            show this help message and exit
  -j JSON_FILE, --json_file JSON_FILE
                        JSON file with backup set points (default: "/Users/ahestevenz/.userfiles/conf/backup.json")
  -d BACKUP_DIRECTORY, --backup_directory BACKUP_DIRECTORY
                        Destination directory (default: "/Volumes/Datensicherung/Datensicherung/")
  -v, --verbose         Increase logging output (default: INFO)(can be specified several times)
  -p output.prof, --profile output.prof
                        Run with profiling and store output in given file
```

The command *bn-run-backup* uses two arguments to backup your system:
* The JSON configuration file
* The path to the **backup directory**

The JSON file specifies the modules which will be syncronized, and it must be written with the format described below.

    {
        "dir1-ahe" : {
        "src_path"  : "/Users/ahestevenz/dir1",
        "user"  : "ahestevenz",
        "host"  : "galactica",
        "os" : "darwin"
        },
        "dir2-ahe" : {
        "src_path"  : "/Users/ahestevenz/dir2",   
        "user"  : "ahestevenz",
        "host"  : "galactica",
        "os" : "darwin"
        },
        "dir3-ahe" : {
        "src_path"  : "/home/ahestevenz/dir3", 
        "user"  : "ahestevenz",
        "host"  : "columbia",
        "os" : "linux"
        }
    }

Finally, only need to run (as an example):
```run
(venv_py39) ahestevenz@galactica:~/dev/backup-module(dev⚡) » bn-run-backup -j my_conf.json -d /mnt/backup
```

## TODO List 
- [x] Add Docker container option
