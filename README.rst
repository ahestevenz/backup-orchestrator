Backup Module System
====================

**backup-module** is a python package which makes backups based on modules written in a JSON file. 

**bnBackupModule** 
------------------

Python class that sync directories and files specified in a JSON file. This class uses methods based on RSYNC command with several arguments.

**backup.json**
--------------

This JSON file specifies the modules which will be syncronized, and it must be written with the format described below.

    {
        "dir1-ahe" : {
        "src_path"  : "/Users/ahestevenz/dir1",
        "user"  : "ahestevenz",
        "host"  : "galactica",
        "os" : "mac"
        },
        "dir2-ahe" : {
        "src_path"  : "/Users/ahestevenz/dir2",   
        "user"  : "ahestevenz",
        "host"  : "galactica",
        "os" : "mac"
        },
        "dir3-ahe" : {
        "src_path"  : "/home/ahestevenz/dir3", 
        "user"  : "ahestevenz",
        "host"  : "columbia",
        "os" : "linux"
        }
    }

Finally, run the command!
-------------------------
.. code-block:: bash

    (master) ahestevenz@galactica:~/Desktop/bleiben/2_code/backup-module (dev)*$ bn-run-backup -h
    usage: bn-run-backup [-h] [-j JSON_FILE] [-d BACKUP_DIRECTORY] [-v]
                         [-p output.prof]

    Welcome to the Backup Module Management

    optional arguments:
      -h, --help            show this help message and exit
      -j JSON_FILE, --json_file JSON_FILE
                            JSON file with backup set points (default:
                            "/Users/ahestevenz/.userfiles/conf/backup.json")
      -d BACKUP_DIRECTORY, --backup_directory BACKUP_DIRECTORY
                            Destination directory (default:
                            "/Volumes/Datensicherung/Datensicherung/")
      -v, --verbose         Increase logging output (default: INFO)(can be
                            specified several times)
      -p output.prof, --profile output.prof
                            Run with profiling and store output in given file

