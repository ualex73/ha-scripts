#!/usr/bin/env python3

"""
Install the following python libraries. This must happen as root (su root):

pip3 install paramiko==2.7.2
pip3 install scp==0.14.1
pip3 install docker==5.0.2
pip3 install python_telegram_bot==13.7

pip3 install voluptuous==0.12.2
pip3 install pyyaml==5.4.1
"""

import datetime
import docker
import fnmatch
import glob
import logging
import os
import paramiko
import re
import scp
import shutil
import socket
import sys
import tarfile
import telegram
import voluptuous as vol
import yaml

from logging.handlers import RotatingFileHandler

#################################################################
CONF_APP = "app"
CONF_CLEANUP = "cleanup"
CONF_CHAT_ID = "chat_id"
CONF_CHOWN = "chown"
CONF_CONFIG = "config"
CONF_CONTAINER = "container"
CONF_COUNT = "count"
CONF_DAY = "day"
CONF_DB = "db"
CONF_DBNAME = "dbname"
CONF_DBUSER = "dbuser"
CONF_DIR = "dir"
CONF_DISABLE_NOTIFICATION = "disable_notification"
CONF_DOCKER = "docker"
CONF_ENABLED = "enabled"
CONF_EXCLUDE = "exclude"
CONF_EXPIRY = "expiry"
CONF_EXPIRY_APP = "expiry_app"
CONF_EXPIRY_DB = "expiry_db"
CONF_EXPIRY_OTHER = "expire_other"
CONF_HOST = "host"
CONF_IMAGE = "image"
CONF_LOCAL = "local"
CONF_MSG = "msg"
CONF_MONTH = "month"
CONF_NAME = "name"
CONF_OTHER = "other"
CONF_PORT = "port"
CONF_RUN_HOST = "run_host"
CONF_REMOTE = "remote"
CONF_RETRY = "retry"
CONF_SCP = "scp"
CONF_SOURCEDIR = "sourcedir"
CONF_STOPDOCKER = "stopdocker"
CONF_TELEGRAM = "telegram"
CONF_TEMP = "temp"
CONF_TOKEN = "token"
CONF_TRANSFER = "transfer"
CONF_TYPE = "type"
CONF_TYPE_MYSQL = "mysql"
CONF_TYPE_POSTGRESQL = "postgresql"
CONF_TYPE_INFLUXDB_BACKUP = "influxdb-backup"
CONF_TYPE_INFLUXDB_EXPORT = "influxdb-export"
CONF_USER = "user"
CONF_YEAR = "year"
CONF_WEEKDAY = "weekday"

# Weekday: Mon=1, Tue=2, Wed=3, Thu=4, Fri=5, Sat=6, Sun=7

#################################################################
CONFIGNAME = "backup.yaml"
DB_MYSQL = "docker exec {container} sh -c 'exec mysqldump --defaults-extra-file=/var/lib/mysql/.mysql-root.conf --routines --skip-lock-tables --databases {database}' | gzip >{dir_temp}/{file_name}"
DB_POSTGRESQL = "docker exec -t {container} pg_dumpall -c -U {sqluser}| gzip >{dir_temp}/{file_name}"
DB_INFLUXDB_BACKUP = "docker exec {container} sh -c 'rm -rf /backup/output && influxd backup -portable /backup/output >/dev/null && cd /backup && tar cfz /backup/{file_name} output --remove-files'"
DB_INFLUXDB_EXPORT = "docker exec {container} influx_inspect export -compress -database {database} -datadir /var/lib/influxdb/data/ -waldir /var/lib/influxdb/wal/ -out /backup/influx-export.gz >/dev/null"

#################################################################

TRANSFER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TYPE, default=CONF_SCP): vol.Any(CONF_SCP),
        vol.Optional(CONF_HOST, default="192.168.1.2"): str,
        vol.Optional(CONF_PORT, default=22): int,
        vol.Optional(CONF_USER, default="pi"): str,
        vol.Optional(CONF_RETRY, default=1): int,
        vol.Optional(CONF_RUN_HOST, default=[]): list,
    }
)

TELEGRAM_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Optional(CONF_TOKEN, default=""): str,
        vol.Optional(CONF_CHAT_ID, default=0): int,
        vol.Optional(CONF_DISABLE_NOTIFICATION, default=False): bool,
    }
)

CONF_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_APP, default=True): bool,
        vol.Optional(CONF_DB, default=True): bool,
        vol.Optional(CONF_OTHER, default=True): bool,
        vol.Optional(CONF_EXPIRY, default=True): bool,
        vol.Optional(CONF_IMAGE, default=True): bool,
        vol.Optional(CONF_DIR, default={}): vol.Schema(
            {
                vol.Optional(CONF_DOCKER, default="/docker"): str,
                vol.Optional(CONF_LOCAL, default="/backup"): str,
                vol.Optional(CONF_REMOTE, default="/backup"): str,
                vol.Optional(CONF_TEMP, default=""): str,
            }
        ),
        vol.Optional(CONF_TRANSFER, default=[]): vol.All(
            list, [vol.Any(TRANSFER_SCHEMA)]
        ),
        vol.Optional(CONF_TELEGRAM, default={}): vol.Schema(TELEGRAM_SCHEMA),
        vol.Optional(CONF_CHOWN, default=""): str,
    }
)
# vol.Optional(CONF_TELEGRAM, default={}): vol.Schema(TELEGRAM_SCHEMA),

EXPIRY_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_DAY, default=0): int,
        vol.Optional(CONF_MONTH, default=0): int,
        vol.Optional(CONF_YEAR, default=0): int,
    }
)

EXPIRY_APP_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_DAY, default=14): int,
        vol.Optional(CONF_MONTH, default=4): int,
        vol.Optional(CONF_YEAR, default=2): int,
        vol.Optional(CONF_WEEKDAY, default=[1, 2, 3, 4, 5, 6, 7]): list,
    }
)

EXPIRY_DB_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_DAY, default=5): int,
        vol.Optional(CONF_MONTH, default=2): int,
        vol.Optional(CONF_YEAR, default=1): int,
        vol.Optional(CONF_WEEKDAY, default=[1, 2, 3, 4, 5, 6, 7]): list,
    }
)

EXPIRY_OTHER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_DAY, default=14): int,
        vol.Optional(CONF_MONTH, default=4): int,
        vol.Optional(CONF_YEAR, default=2): int,
        vol.Optional(CONF_WEEKDAY, default=[1, 2, 3, 4, 5, 6, 7]): list,
    }
)

APP_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Required(CONF_NAME): str,
        vol.Optional(CONF_STOPDOCKER, default=False): bool,
        vol.Optional(CONF_EXCLUDE, default=[]): list,
        vol.Optional(CONF_CONTAINER, default=""): str,
        vol.Optional(CONF_SOURCEDIR, default=""): str,
        vol.Optional(CONF_WEEKDAY, default=[1, 2, 3, 4, 5, 6, 7]): list,
        vol.Optional(CONF_EXPIRY, default={}): EXPIRY_SCHEMA,
        vol.Optional(CONF_RUN_HOST, default=[]): list,
    }
)

DB_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Required(CONF_NAME): str,
        vol.Optional(CONF_STOPDOCKER, default=False): bool,
        vol.Required(CONF_TYPE): vol.Any(
            CONF_TYPE_MYSQL,
            CONF_TYPE_POSTGRESQL,
            CONF_TYPE_INFLUXDB_BACKUP,
            CONF_TYPE_INFLUXDB_EXPORT,
        ),
        vol.Optional(CONF_DBNAME, default=""): str,
        vol.Optional(CONF_DBUSER, default=""): str,
        vol.Optional(CONF_CONTAINER, default=""): str,
        vol.Optional(CONF_SOURCEDIR, default=""): str,
        vol.Optional(CONF_WEEKDAY, default=[1, 2, 3, 4, 5, 6, 7]): list,
        vol.Optional(CONF_EXPIRY, default={}): EXPIRY_SCHEMA,
        vol.Optional(CONF_RUN_HOST, default=[]): list,
    }
)

OTHER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Required(CONF_NAME): str,
        vol.Optional(CONF_STOPDOCKER, default=False): bool,
        vol.Optional(CONF_EXCLUDE, default=[]): list,
        vol.Optional(CONF_SOURCEDIR, default=""): str,
        vol.Optional(CONF_WEEKDAY, default=[1, 2, 3, 4, 5, 6, 7]): list,
        vol.Optional(CONF_EXPIRY, default={}): EXPIRY_SCHEMA,
        vol.Optional(CONF_RUN_HOST, default=[]): list,
    }
)

IMAGE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_WEEKDAY, default=[7]): list,
        vol.Optional(CONF_CLEANUP, default=False): bool,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CONFIG, default={}): CONF_SCHEMA,
        vol.Optional(CONF_APP, default=[]): vol.All(list, [vol.Any(APP_SCHEMA)]),
        vol.Optional(CONF_DB, default=[]): vol.All(list, [vol.Any(DB_SCHEMA)]),
        vol.Optional(CONF_OTHER, default=[]): vol.All(list, [vol.Any(OTHER_SCHEMA)]),
        vol.Optional(CONF_EXPIRY_APP, default={}): EXPIRY_APP_SCHEMA,
        vol.Optional(CONF_EXPIRY_DB, default={}): EXPIRY_DB_SCHEMA,
        vol.Optional(CONF_EXPIRY_OTHER, default={}): EXPIRY_OTHER_SCHEMA,
        vol.Optional(CONF_IMAGE, default={}): IMAGE_SCHEMA,
    }
)

#################################################################
logging.basicConfig(
    level=logging.ERROR, format="%(asctime)s %(levelname)s: %(message)s"
)
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)
# LOGGER.propagate = False

#################################################################
ERRORS = {}
ERRORS[CONF_COUNT] = 0
ERRORS[CONF_MSG] = []

#################################################################
def ErrorMsg(msg):
    """Store the error message for reporting via e.g. Telegram."""
    ERRORS[CONF_COUNT] += 1
    ERRORS[CONF_MSG].append(msg)


#################################################################
def reportError():
    """Report about error(s) and send a Telegram if required."""

    # Normally we have zero errors
    if ERRORS[CONF_COUNT] == 0:
        LOGGER.info("No error(s) found during run")
        return

    LOGGER.error("%d error(s) found during run", ERRORS[CONF_COUNT])

    # Needs to be enabled
    if not config[CONF_CONFIG][CONF_TELEGRAM][CONF_ENABLED]:
        return

    if config[CONF_CONFIG][CONF_TELEGRAM][CONF_TOKEN] == "":
        LOGGER.error("Telegram '%s' is not configured", CONF_TOKEN)
        return

    if config[CONF_CONFIG][CONF_TELEGRAM][CONF_CHAT_ID] == "":
        LOGGER.error("Telegram '%s' is not configured", CONF_CHAT_ID)
        return

    msgtext = f"Backup: {ERRORS[CONF_COUNT]} error(s), Msg1={ERRORS[CONF_MSG][0]}"

    bot = telegram.Bot(config[CONF_CONFIG][CONF_TELEGRAM][CONF_TOKEN])
    bot.send_message(
        chat_id=config[CONF_CONFIG][CONF_TELEGRAM][CONF_CHAT_ID],
        disable_notification=config[CONF_CONFIG][CONF_TELEGRAM][
            CONF_DISABLE_NOTIFICATION
        ],
        text=msgtext,
    )


#################################################################
def readConfig():

    config = None

    location = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))
    name = f"{location}/{CONFIGNAME}"

    try:
        with open(name, "r") as f:
            config = yaml.safe_load(f)
            config = CONFIG_SCHEMA(config)
    except Exception as e:
        errmsg = f"Exception={type(e).__name__} Msg={e}"
        ErrorMsg(errmsg)
        LOGGER.error(
            errmsg, exc_info=True,
        )
        sys.exit(1)

    # Setup logging, logfile and rotation
    logname = __file__
    logname = logname.replace(".py", "")
    logname += ".log"
    # Define maximum logfile as 1MByte. 1MByte should holdd 3+ weeks of logging
    maxBytes = 1 * 1024 * 1024
    backupCount = 3

    LOGGER.propagate = False
    handler = RotatingFileHandler(logname, maxBytes=maxBytes, backupCount=backupCount)
    handler.setLevel("DEBUG")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    LOGGER.addHandler(handler)

    LOGGER.info("Using config file '%s'", name)

    # Do some backups checks, our local directories should exist
    if config[CONF_CONFIG][CONF_APP] or config[CONF_CONFIG][CONF_DB]:
        if not os.path.exists(config[CONF_CONFIG][CONF_DIR][CONF_DOCKER]):
            errmsg = f"Directory ({CONF_DOCKER}): '{config[CONF_CONFIG][CONF_DIR][CONF_DOCKER]}' does not exist"
            ErrorMsg(errmsg)
            LOGGER.error(errmsg)
            sys.exit(1)

        if not os.path.exists(config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]):
            errmsg = f"Directory ({CONF_LOCAL}): '{config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]}' does not exist"
            ErrorMsg(errmsg)
            LOGGER.error(errmsg)
            sys.exit(1)

    for transfer in config[CONF_CONFIG][CONF_TRANSFER]:
        if transfer[CONF_TYPE] != CONF_SCP:
            errmsg = "Unknown transfer type '{transfer[CONF_TYPE]}'"
            ErrorMsg(errmsg)
            LOGGER.error(errmsg)
            sys.exit(2)

    # LOGGER.debug("Config: %s", config)
    return config


#################################################################
def remoteSSH(client, cmd, remotehost=None, retrylast=True, retrycount=0):

    stdin, stdout, stderr = client.exec_command(cmd)
    # Check RC, should be zero
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        errmsg = f"SSH command '{cmd}', retry({retrycount}). Return RC={rc}"
        LOGGER.error(errmsg)

        # Dump stdout/stderr just in case
        response = stdout.readlines()
        for line in response:
            LOGGER.error("STDOUT: %s", line.rstrip())
        response = stderr.readlines()
        for line in response:
            LOGGER.error("STDERR: %s", line.rstrip())

        if retrylast:
            ErrorMsg(errmsg)

        return False, ""

    else:
        return True, stdout.readlines()


#################################################################
def remoteSCP(client, lfile, rdir, remotehost=None, retrylast=True, retrycount=0):

    scpclient = scp.SCPClient(client.get_transport())

    try:
        scpclient.put(lfile, remote_path=rdir)
    except Exception as e:
        errmsg = f"SCP failed for '{lfile}', host '{remotehost}', retry({retrycount}). Exception={type(e).__name__} Msg={e}"
        LOGGER.error(errmsg, exc_info=True)

        # Only report/end if retry expired
        if retrylast:
            ErrorMsg(errmsg)
        return False

    else:
        return True


#################################################################
def startDocker(typeName, name):

    LOGGER.debug("%s %s: Starting container", typeName, name)
    rc = os.system(f"docker start {name} >/dev/null")
    if rc != 0:
        errmsg = f"{typeName} {name}: Failed to start container, RC={int(rc/256)}"
        ErrorMsg(errmsg)
        LOGGER.error(errmsg)


#################################################################
def stopDocker(typeName, name):

    LOGGER.debug("%s %s: Stopping container", typeName, name)
    rc = os.system(f"docker stop {name} >/dev/null")
    if rc != 0:
        errmsg = f"{typeName} {name}: Failed to stop container, RC={int(rc/256)}"
        ErrorMsg(errmsg)
        LOGGER.error(errmsg)


#################################################################
def doBackupWrapper(typeName, entry):
    """A wrapper around docker stop/start, because a failure during
       backup should never leave the container stopped."""

    if entry[CONF_STOPDOCKER]:
        stopDocker(typeName, entry[CONF_NAME])

    try:
        _doAppDb(typeName, entry)
    except Exception as e:
        errmsg = f"Failure do{typeName} {entry[CONF_NAME]}. Exception={type(e).__name__} Msg={e}"
        ErrorMsg(errmsg)
        LOGGER.error(
            errmsg, exc_info=True,
        )

    if entry[CONF_STOPDOCKER]:
        startDocker(typeName, entry[CONF_NAME])


#################################################################
def _doAppDb(typeName, entry):
    def excludeFromTar(tarinfo):
        """If we exclude it, we return None, otherwise tarinfo."""
        # LOGGER.debug("x: %s", tarinfo.name)
        for pattern in entry[CONF_EXCLUDE] or []:
            if fnmatch.fnmatch(tarinfo.name, pattern):
                return None
        # LOGGER.debug("y: %s", tarinfo.name)

        return tarinfo

    # If sourcedir is used, use that one
    if entry[CONF_SOURCEDIR]:
        # Check if it is an absolute one or not
        if entry[CONF_SOURCEDIR].startswith("/"):
            dir_input = entry[CONF_SOURCEDIR]
        else:
            dir_input = (
                f"{config[CONF_CONFIG][CONF_DIR][CONF_DOCKER]}/{entry[CONF_SOURCEDIR]}"
            )
    else:
        dir_input = f"{config[CONF_CONFIG][CONF_DIR][CONF_DOCKER]}/{entry[CONF_NAME]}"

    # We can overrule the temporary directory, useful for NFS mounts
    if config[CONF_CONFIG][CONF_DIR][CONF_TEMP]:
        dir_temp = config[CONF_CONFIG][CONF_DIR][CONF_TEMP]
    else:
        dir_temp = f"{config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]}/temp"

    dir_output = (
        f"{config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]}/{typeName}/{entry[CONF_NAME]}"
    )
    dir_output_remote = (
        f"{config[CONF_CONFIG][CONF_DIR][CONF_REMOTE]}/{typeName}/{entry[CONF_NAME]}"
    )

    # Generare output date & day-of-week
    file_name = f"{entry[CONF_NAME]}.{datetime.datetime.today().strftime('%Y%m%d')}-{datetime.datetime.today().isoweekday()}"

    # Configure name if no container is specified
    if entry[CONF_CONTAINER] == "":
        entry[CONF_CONTAINER] = entry[CONF_NAME]

    if typeName == CONF_APP:
        file_name = f"{file_name}.tgz"
    elif entry[CONF_TYPE] in [CONF_TYPE_MYSQL, CONF_TYPE_POSTGRESQL]:
        # MySQL/PostgreSQL use same naming
        file_name = f"{file_name}.sql.gz"
    elif entry[CONF_TYPE] in [CONF_TYPE_INFLUXDB_EXPORT]:
        # InfluxDB filename, but is the to-be-renamed filename
        # The initial output filename is fixed in the container command
        file_name = f"{file_name}.gz"
    elif entry[CONF_TYPE] in [CONF_TYPE_INFLUXDB_BACKUP]:
        # InfluxDB filename, but is the to-be-renamed filename
        # The initial output filename is fixed in the container command
        file_name = f"{file_name}.tgz"

    # Check if local directory exists
    if not os.path.exists(dir_input):
        errmsg = (
            f"{typeName} {entry[CONF_NAME]}: Directory '{dir_input}' does not exist"
        )
        ErrorMsg(errmsg)
        LOGGER.error(errmsg)
        return

    if not os.path.exists(dir_temp):
        os.makedirs(dir_temp)
        LOGGER.debug(
            "%s %s: Directory '%s' created", typeName, entry[CONF_NAME], dir_temp
        )

    # Create output directory structure if needed
    if not os.path.exists(dir_output):
        os.makedirs(dir_output)
        LOGGER.debug(
            "%s %s: Directory '%s' created", typeName, entry[CONF_NAME], dir_output
        )

    alreadymoved = False

    # Current time
    now = datetime.datetime.now()

    # Create output file & compress file(s)
    if typeName == CONF_APP:
        # Go to the input directory, I make it relative
        os.chdir(dir_input)

        LOGGER.debug(
            "%s %s: Creating '%s' from '%s'",
            typeName,
            entry[CONF_NAME],
            file_name,
            dir_input,
        )
        # Create out tgz file
        try:
            with tarfile.open(f"{dir_temp}/{file_name}", mode="w:gz") as archive:
                # Add ".", to preserve parent directory right/permissions
                archive.add(".", recursive=False)

                for name in os.listdir("."):
                    archive.add(name, recursive=True, filter=excludeFromTar)
        except Exception as e:
            errmsg = f"{typeName} {entry[CONF_NAME]}: Failure during creation '{dir_temp}/{file_name}'. Exception={type(e).__name__} Msg={e}"
            ErrorMsg(errmsg)
            LOGGER.error(
                errmsg, exc_info=True,
            )

            return

        # Calculate how many seconds it took us to SCP
        later = datetime.datetime.now()
        diff = (later - now).total_seconds()
        fsize = os.stat(f"{dir_temp}/{file_name}").st_size
        fsize = round(fsize / 1024, 1)
        unit = "kByte"

        # Change to MByte if needed
        if fsize > 1000:
            fsize = round(fsize / 1024, 1)
            unit = "MByte"

        LOGGER.debug(
            "%s %s: Created '%s' from '%s' (%d seconds, %d %s)",
            typeName,
            entry[CONF_NAME],
            file_name,
            dir_input,
            diff,
            fsize,
            unit,
        )

        # We should start the container asap
        if entry[CONF_STOPDOCKER]:
            startDocker(type, entry[CONF_NAME])

    else:
        if entry[CONF_TYPE] == CONF_TYPE_MYSQL:
            cmd = DB_MYSQL.format(
                container=entry[CONF_CONTAINER],
                database=entry[CONF_DBNAME],
                sqluser=entry[CONF_DBUSER],
                dir_temp=dir_temp,
                file_name=file_name,
            )
        elif entry[CONF_TYPE] == CONF_TYPE_POSTGRESQL:
            cmd = DB_POSTGRESQL.format(
                container=entry[CONF_CONTAINER],
                database=entry[CONF_DBNAME],
                sqluser=entry[CONF_DBUSER],
                dir_temp=dir_temp,
                file_name=file_name,
            )
        elif entry[CONF_TYPE] == CONF_TYPE_INFLUXDB_BACKUP:
            cmd = DB_INFLUXDB_BACKUP.format(
                container=entry[CONF_CONTAINER], file_name=file_name
            )
        elif entry[CONF_TYPE] == CONF_TYPE_INFLUXDB_EXPORT:
            cmd = DB_INFLUXDB_EXPORT.format(
                container=entry[CONF_CONTAINER], database=entry[CONF_DBNAME]
            )

        LOGGER.debug("%s %s: Executing '%s'", typeName, entry[CONF_NAME], cmd)

        rc = os.system(cmd)
        if rc == 0:
            # Calculate how many seconds it took us to execute the command
            later = datetime.datetime.now()
            diff = (later - now).total_seconds()

            # Need to use the right DB stuff
            if entry[CONF_TYPE] in [CONF_TYPE_MYSQL, CONF_TYPE_POSTGRESQL]:
                fsize = os.stat(f"{dir_temp}/{file_name}").st_size
            elif entry[CONF_TYPE] == CONF_TYPE_INFLUXDB_BACKUP:
                fsize = os.stat(f"{dir_input}/backup/{file_name}").st_size
            elif entry[CONF_TYPE] == CONF_TYPE_INFLUXDB_EXPORT:
                fsize = os.stat(f"{dir_input}/backup/influx-export.gz").st_size

            fsize = round(fsize / 1024, 1)
            unit = "kByte"

            # Change to MByte if needed
            if fsize > 1000:
                fsize = round(fsize / 1024, 1)
                unit = "MByte"

            LOGGER.debug(
                "%s %s: Execution is successful (%d seconds, %d %s)",
                typeName,
                entry[CONF_NAME],
                diff,
                fsize,
                unit,
            )
        else:
            errmsg = f"{typeName} {entry[CONF_NAME]}: Execution error '{entry[CONF_TYPE]}' RC={int(rc/256)}, CMD={cmd}"
            ErrorMsg(errmsg)
            LOGGER.error(errmsg)
            return

        # Special for InfluxDB, because we need to rename in-container "/backup/influx*gz" to our output filename
        if entry[CONF_TYPE] == CONF_TYPE_INFLUXDB_BACKUP:
            file_input = f"{dir_input}/backup/{file_name}"

            # file must exist
            if not os.path.isfile(file_input):
                errmsg = f"{typeName} {entry[CONF_NAME]}: Executed InfluxDB backup, but '{file_input}' does not exist?"
                ErrorMsg(errmsg)
                LOGGER.error(errmsg)
                return

            shutil.move(file_input, f"{dir_output}/{file_name}")
            LOGGER.debug(
                "%s %s: Moved '%s' to '%s'",
                typeName,
                entry[CONF_NAME],
                file_input,
                dir_output,
            )

            # Set already moved, because it is inside the container, not in the temp directory
            alreadymoved = True

        elif entry[CONF_TYPE] == CONF_TYPE_INFLUXDB_EXPORT:

            file_input = f"{dir_input}/backup/influx-export.gz"

            # file must exist
            if not os.path.isfile(file_input):
                errmsg = f"{typeName} {entry[CONF_NAME]}: Executed InfluxDB export, but '{file_input}' does not exist?"
                ErrorMsg(errmsg)
                LOGGER.error(errmsg)
                return

            shutil.move(file_input, f"{dir_output}/{file_name}")
            LOGGER.debug(
                "%s %s: Moved '%s' to '%s'",
                typeName,
                entry[CONF_NAME],
                file_input,
                f"{dir_output}/{file_name}",
            )

            # Set already moved, because it is inside the container, not in the temp directory
            alreadymoved = True

    # All good, move it to the final directory, for InfluxDB this isn't needed
    if not alreadymoved:
        shutil.move(f"{dir_temp}/{file_name}", f"{dir_output}/{file_name}")
        LOGGER.debug(
            "%s %s: Moved '%s' to '%s'",
            typeName,
            entry[CONF_NAME],
            f"{dir_temp}/{file_name}",
            dir_output,
        )

        # *** ONLY works on LOCAL node, not on remote ***

        # Set permissions on output file
        if config[CONF_CONFIG][CONF_CHOWN]:
            try:
                chown = config[CONF_CONFIG][CONF_CHOWN].split(":")
                chown_uid = chown[0]
                chown_gid = -1
                if len(chown) >= 2:
                    chown_gid = chown[1]

                if chown_uid:
                    os.chown(
                        f"{dir_output}/{file_name}", int(chown_uid), int(chown_gid)
                    )
                    LOGGER.debug(
                        "%s %s: Chown '%s' with uid=%s and gid=%s",
                        typeName,
                        entry[CONF_NAME],
                        f"{dir_output}/{file_name}",
                        chown_uid,
                        chown_gid,
                    )

            except Exception as e:
                errmsg = f"{typeName} {entry[CONF_NAME]}: '{file_name}' FAILED chown. Exception={type(e).__name__} Msg={e}"
                ErrorMsg(errmsg)
                LOGGER.error(
                    errmsg, exc_info=True,
                )

        # *** ONLY works on LOCAL node, not on remote ***

    for transfer in config[CONF_CONFIG][CONF_TRANSFER]:

        remotehost = transfer[CONF_HOST]
        remoteport = transfer[CONF_PORT]
        remoteuser = transfer[CONF_USER]

        # Check if we should run it on this host or not
        if transfer[CONF_RUN_HOST] and hostname not in transfer[CONF_RUN_HOST]:
            LOGGER.debug(
                "%s %s: '%s' is not enabled on this run_host '%s'='%s'",
                typeName,
                entry[CONF_NAME],
                remotehost,
                transfer[CONF_RUN_HOST],
                hostname,
            )
            continue

        # ping the backup node
        rc = os.system("ping -w 3 -c 2 " + remotehost + " >/dev/null")

        if rc != 0:
            errmsg = f"{typeName} {entry[CONF_NAME]}: Cannot ping host '{remotehost}' RC={int(rc/256)}"
            ErrorMsg(errmsg)
            LOGGER.error(errmsg)
            continue

        LOGGER.debug("%s %s: Ping host '%s' OK", typeName, entry[CONF_NAME], remotehost)

        # make remote directory, possible it does not exist
        if transfer[CONF_TYPE] == CONF_SCP:

            retrycount = 0

            while retrycount <= transfer[CONF_RETRY]:

                retrylast = True if retrycount == transfer[CONF_RETRY] else False

                # LOGGER.debug("%s %s: SCP to '%s:%s' with username '%s'", typeName, entry[CONF_NAME], remotehost, remoteport, remoteuser)
                client = paramiko.SSHClient()
                client.load_system_host_keys()
                # client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                # normally connect will establish a new session. Need to redo it when a failure happens
                client.connect(
                    remotehost,
                    port=remoteport,
                    username=remoteuser,
                    auth_timeout=5,
                    timeout=10,
                )

                LOGGER.debug(
                    "%s %s: SSH host '%s' OK", typeName, entry[CONF_NAME], remotehost
                )

                # make remote directory, possible it does not exist
                cmd = f"mkdir -p {dir_output_remote}"
                rc, stdout = remoteSSH(
                    client,
                    cmd,
                    remotehost=remotehost,
                    retrylast=retrylast,
                    retrycount=retrycount,
                )

                if not rc:
                    retrycount += 1
                    continue

                LOGGER.debug(
                    "%s %s: Remote directory '%s' OK",
                    typeName,
                    entry[CONF_NAME],
                    dir_output_remote,
                )

                # Current time
                now = datetime.datetime.now()

                # scp it to the backup node
                rc = remoteSCP(
                    client,
                    f"{dir_output}/{file_name}",
                    dir_output_remote,
                    remotehost=remotehost,
                    retrylast=retrylast,
                    retrycount=retrycount,
                )

                if not rc:
                    retrycount += 1
                    continue

                # Calculate how many seconds it took us to SCP
                later = datetime.datetime.now()
                diff = (later - now).total_seconds()
                fsize = os.stat(f"{dir_output}/{file_name}").st_size
                fsize = round(fsize / 1024, 1)
                unit = "kByte"

                # Change to MByte if needed
                if fsize > 1000:
                    fsize = round(fsize / 1024, 1)
                    unit = "MByte"

                LOGGER.debug(
                    "%s %s: SCP '%s' OK (%d seconds, %d %s)",
                    typeName,
                    entry[CONF_NAME],
                    f"{dir_output}/{file_name}",
                    diff,
                    fsize,
                    unit,
                )

                # check the backup node, if the file is correct. For now, just a ls -l
                cmd = f"ls -l {dir_output_remote}/{file_name}"
                rc, stdout = remoteSSH(client, cmd, remotehost=remotehost)
                if not rc:
                    retrycount += 1
                    continue

                LOGGER.debug(
                    "%s %s: Remote file '%s' OK",
                    typeName,
                    entry[CONF_NAME],
                    f"{dir_output_remote}/{file_name}",
                )

                client.close()

                # All successfull
                break

            # We get the following exception if SSH keys haven't been exchanged:
            # paramiko.ssh_exception.SSHException

    # Make it possible to restart scp/copy if it previously failed?


#################################################################
def doBackupType(typeName):
    """We go through our entries, and execute our task.
       Config is available as read-only global var."""

    # We could be fully disabled
    if config[CONF_CONFIG][typeName]:
        for entry in config[typeName]:

            # If we are in test mode, we need to do something else
            if args.get("mode", "") == "backup":
                if args[CONF_TYPE] == typeName and args[CONF_NAME] == entry[CONF_NAME]:
                    LOGGER.debug(
                        "Running backup test on %s '%s'", typeName, entry[CONF_NAME]
                    )
                    doBackupWrapper(typeName, entry)
            else:

                # If it is disabled, we skip it
                if not entry[CONF_ENABLED]:
                    LOGGER.debug("%s '%s' is not enabled", typeName, entry[CONF_NAME])
                    continue

                if args.get("mode", "") == "run_host":
                    if entry[CONF_RUN_HOST] and hostname not in entry[CONF_RUN_HOST]:
                        print(f"{typeName} {entry[CONF_NAME]} is DISABLED on this host")
                    else:
                        print(f"{typeName} {entry[CONF_NAME]} is enabled on this host")
                    continue

                if entry[CONF_RUN_HOST] and hostname not in entry[CONF_RUN_HOST]:
                    LOGGER.debug(
                        "%s '%s' is not enabled on this run_host '%s'='%s'",
                        typeName,
                        entry[CONF_NAME],
                        entry[CONF_RUN_HOST],
                        hostname,
                    )
                    continue

                # Check if we should execute today or not
                today = datetime.datetime.today().isoweekday()
                if today not in entry[CONF_WEEKDAY]:
                    LOGGER.debug(
                        "%s '%s' should not run today", typeName, entry[CONF_NAME]
                    )
                    continue

                doBackupWrapper(typeName, entry)

    else:
        LOGGER.debug("%s backup is fully disabled", typeName)


"""
# Backup policy:
# - Keep the last 7 days
# - Keep the Sunday (7) of the last 2 months
# - Keep the first Sunday of each month of the last 12 months
"""

#################################################################
def doRestoreType():
    """Restore a specific app/db/other to this node from the backup directory."""

    found = False
    entryFound = {}

    for entry in config[args[CONF_TYPE]]:
        if args[CONF_NAME] == entry[CONF_NAME]:
            entryFound = entry
            found = True
            break

    if not found:
        print(f"ERROR: Cannot find name '{args[CONF_NAME]}' in '{args[CONF_TYPE]}'")
        return

    # Define the input/output directories (reverse of the backup)
    dir_input = f"{config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]}/{args[CONF_TYPE]}/{entry[CONF_NAME]}"

    # If sourcedir is used, use that one
    if entry[CONF_SOURCEDIR]:
        # Check if it is an absolute one or not
        if entry[CONF_SOURCEDIR].startswith("/"):
            dir_output = entry[CONF_SOURCEDIR]
        else:
            dir_output = (
                f"{config[CONF_CONFIG][CONF_DIR][CONF_DOCKER]}/{entry[CONF_SOURCEDIR]}"
            )
    else:
        dir_output = f"{config[CONF_CONFIG][CONF_DIR][CONF_DOCKER]}/{entry[CONF_NAME]}"

    # Check if output directory exists, we should not overwrite
    if os.path.isdir(dir_output):
        sys.exit(
            f"ERROR: Output directory '{dir_output}' already exists, please remove it manually first"
        )

    # Find file to restore
    lof = sorted(
        filter(
            os.path.isfile, glob.glob(f"{dir_input}/{entry[CONF_NAME]}.????????-?.*")
        )
    )

    # We must find 1 or more filename
    if len(lof) == 0:
        sys.exit(
            f"ERROR: Cannot find file in directory '{dir_input}' with '{entry[CONF_NAME]}.????????-?.*'"
        )

    file_name = lof[-1]

    print(f"INFO: Using input file '{file_name}'")
    print(f"INFO: Using output directory '{dir_output}'")

    # Ask if we should continue or not
    answer = input("Continue [Y/n]")
    if answer not in ["", "Y", "y"]:
        sys.exit("INFO: Stopped ...")

    os.mkdir(dir_output)
    os.chdir(dir_output)

    print(f"INFO: Created output directory '{dir_output}'")
    print(f"INFO: Starting extraction ...")

    # Now it depends on the type
    if args[CONF_TYPE] in [CONF_APP, CONF_OTHER]:
        with tarfile.open(f"{file_name}", mode="r:gz") as archive:
            archive.extractall()
    # TarFile.extractall(path=".", members=None, *, numeric_owner=False)

    elif args[CONF_TYPE] == CONF_DB:
        print("Do nothing YET ...")


#################################################################
def _doCleanupAppDb(typeName, entry):
    """Cleanup routine."""

    # Can only cleanup locally
    dir_output = (
        f"{config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]}/{typeName}/{entry[CONF_NAME]}"
    )

    if not os.path.isdir(dir_output):
        errmsg = f"Directory '{dir_output}' does not exist"
        ErrorMsg(errmsg)
        LOGGER.error(errmsg)
        return

    # Determinate day/month/year
    expiry_type = CONF_EXPIRY_APP if typeName == CONF_APP else CONF_EXPIRY_DB
    day = (
        config[expiry_type][CONF_DAY]
        if entry[CONF_EXPIRY][CONF_DAY] == 0
        else entry[CONF_EXPIRY][CONF_DAY]
    )
    month = (
        config[expiry_type][CONF_MONTH]
        if entry[CONF_EXPIRY][CONF_MONTH] == 0
        else entry[CONF_EXPIRY][CONF_MONTH]
    )
    year = (
        config[expiry_type][CONF_YEAR]
        if entry[CONF_EXPIRY][CONF_YEAR] == 0
        else entry[CONF_EXPIRY][CONF_YEAR]
    )

    # Get the list of files into an array
    files = [
        file
        for file in os.listdir(dir_output)
        if os.path.isfile(os.path.join(dir_output, file))
    ]

    # Variable for files to-be-deleted
    removefiles = []

    if day == 0:
        LOGGER.warning(
            "%s %s: has day=0 configured, skipping expiry", typeName, entry[CONF_NAME]
        )
        return

    # First check if the list is empty/none
    if files is None:
        LOGGER.debug("%s %s: is empty", typeName, entry[CONF_NAME])
        return

    LOGGER.debug("%s %s: expiry started", typeName, entry[CONF_NAME])

    # We need to reverse it, to get an easier order
    for fname in sorted(files, reverse=True):

        # Build up full name, including path
        file_name = f"{dir_output}/{fname}"

        # Check if name is valid
        if not fname.startswith(entry[CONF_NAME]):
            LOGGER.warning(
                "%s %s: '%s' name is invalid (prefix)",
                typeName,
                entry[CONF_NAME],
                file_name,
            )
            continue

        if not re.search("\.\d{8}\-[1-7]\.", fname):
            LOGGER.warning(
                "%s %s: '%s' name is invalid (no date/time)",
                typeName,
                entry[CONF_NAME],
                file_name,
            )
            continue

        # First find all day backups
        if day > 0:
            LOGGER.debug(
                "%s %s: '%s' NOT expired (day, %d)",
                typeName,
                entry[CONF_NAME],
                file_name,
                day,
            )
            day -= 1
            continue

        # We only keep the first Sunday of the beginning of the month 20????0[1-7]-7
        if month > 0:
            if re.search("\.\d{6}0[1-7]\-7\.", fname):
                LOGGER.debug(
                    "%s %s: '%s' NOT expired (month, %d)",
                    typeName,
                    entry[CONF_NAME],
                    file_name,
                    month,
                )
                month -= 1
                continue

        # We keep first sunday of December. The current year should be covered by month and/or day
        if year > 0:
            if re.search("\.\d{4}120[1-7]\-7\.", fname):
                LOGGER.debug(
                    "%s %s: '%s' NOT expired (year, %d)",
                    typeName,
                    entry[CONF_NAME],
                    file_name,
                    year,
                )
                year -= 1
                continue

        # File should be removed
        removefiles.append(fname)

    # Check if we find year entrys, if not ... Exclude the most recent one just in case
    if year > 0:
        now = datetime.datetime.now()
        lastyear = now.year
        lastyear -= 1
        for fname in removefiles[:]:
            if re.search("\." + str(lastyear) + "\d{4}\-[1-7]\.", fname):
                file_name = f"{dir_output}/{fname}"
                LOGGER.debug(
                    "%s %s: '%s' should NOT be deleted (year)",
                    typeName,
                    entry[CONF_NAME],
                    file_name,
                )
                removefiles.remove(fname)
                break

    for fname in removefiles:
        file_name = f"{dir_output}/{fname}"
        try:
            os.remove(file_name)
            LOGGER.debug("%s %s: '%s' DELETED", typeName, entry[CONF_NAME], file_name)
        except Exception as e:
            errmsg = f"{typeName} {entry[CONF_NAME]}: '{file_name}' FAILED deletion. Exception={type(e).__name__} Msg={e}"
            ErrorMsg(errmsg)
            LOGGER.error(
                errmsg, exc_info=True,
            )


#################################################################
def _doCleanupImages():
    imageList = []

    inputname = (
        f"{config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]}/{CONF_IMAGE}/imagelist.txt"
    )
    if not os.path.exists(inputname):
        LOGGER.debug("Cleanup: '%s' does not exist", inputname)
        return

    with open(inputname, "r") as fh:
        Lines = fh.readlines()
        for line in Lines:
            imageList.append(line.strip())

    fileList = os.listdir(f"{config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]}/{CONF_IMAGE}")

    for entry in fileList:
        # It needs to be a .tar.gz file
        if entry.endswith(".tar.gz"):
            if entry in imageList:
                LOGGER.debug("Cleanup: image '%s' in imagelist.txt", entry)
            else:
                LOGGER.debug("Cleanup: image '%s' NOT in imagelist.txt - REMOVE", entry)
                os.remove(
                    f"{config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]}/{CONF_IMAGE}/{entry}"
                )


#################################################################
def doCleanup():
    """We go through our entries, and execute our cleanup task."""

    if not config[CONF_CONFIG][CONF_EXPIRY]:
        LOGGER.debug("Expiry is fully disabled")
        return

    # We could be fully disabled
    for entry in config[CONF_APP]:
        if args.get("mode", "") == "cleanup":
            if args[CONF_TYPE] == CONF_APP and args[CONF_NAME] == entry[CONF_NAME]:
                _doCleanupAppDb(CONF_APP, entry)
        else:
            # Check if we should execute today or not
            today = datetime.datetime.today().isoweekday()
            if today not in config[CONF_EXPIRY_APP][CONF_WEEKDAY]:
                LOGGER.debug("%s: No expiry today", CONF_EXPIRY_APP)
                break

            # If it is disabled, we skip it
            if not entry[CONF_ENABLED]:
                continue

            _doCleanupAppDb(CONF_APP, entry)

    for entry in config[CONF_DB]:
        if args.get("mode", "") == "cleanup":
            if args[CONF_TYPE] == CONF_DB and args[CONF_NAME] == entry[CONF_NAME]:
                _doCleanupAppDb(CONF_DB, entry)
        else:
            # Check if we should execute today or not
            today = datetime.datetime.today().isoweekday()
            if today not in config[CONF_EXPIRY_DB][CONF_WEEKDAY]:
                LOGGER.debug("%s: No expiry today", CONF_EXPIRY_DB)
                break

            # If it is disabled, we skip it
            if not entry[CONF_ENABLED]:
                continue
            _doCleanupAppDb(CONF_DB, entry)

    if config[CONF_IMAGE][CONF_CLEANUP]:

        if args.get("mode", "") == "cleanup":
            if args[CONF_TYPE] == CONF_IMAGE:
                _doCleanupImages()
        else:
            # Check if we should execute today or not
            today = datetime.datetime.today().isoweekday()
            if today not in config[CONF_EXPIRY_DB][CONF_WEEKDAY]:
                LOGGER.debug("expiry_image: No image cleanup today")
            else:
                _doCleanupImages()
    else:
        LOGGER.debug("Cleanup: Image cleanup disabled")


#################################################################
def displayHelp():

    help = """./backup.py [cmd] [arg1] [arg2] [argX]

cmd = backup, restore, image, cleanup, run_host

backup = Backups a specific type and application
restore = Restores a specific type and application
image = Backups images manually
cleanup = Run cleanup manually
run_host = Show which backups will be done on THIS hostname

Example:
./backup.py backup app dsmr
./backup.py backup db influxdb 
./backup.py backup other startrek

./backup.py image
./backup.py run_host
"""

    print(help)


#################################################################
def parseArg():
    """Arguments could be passed during testing a single entry."""

    args = {}

    # No arguments is fine too
    if len(sys.argv) == 1:
        return args

    # Expect: "backup <type> <containername>"

    if sys.argv[1].lower() in ["backup", "restore", "image", "cleanup", "run_host"]:

        args["mode"] = sys.argv[1].lower()

        if args["mode"] in ["backup", "restore", "cleanup"]:
            if len(sys.argv) != 4:
                displayHelp()
                sys.exit(
                    f"FATAL: Not enough arguments specified for '{args['mode']}', e.g. '{args['mode']} app dsmr'"
                )

            args[CONF_TYPE] = sys.argv[2].lower()
            if args[CONF_TYPE] not in [CONF_APP, CONF_DB, CONF_OTHER]:
                displayHelp()
                sys.exit(
                    f"FATAL: Invalid 'backup' argument '{args[CONF_TYPE]}', only {CONF_APP}, {CONF_DB} and {CONF_OTHER} are supported"
                )

            args[CONF_NAME] = sys.argv[3]

        return args

    # Anything else is wrong
    displayHelp()
    sys.exit("FATAL: Invalid argument(s) specified")


#################################################################
def _backupImage(name):
    """Backup the image."""

    # Replace bad characters
    oname = name.replace("/", "_").replace(":", "%")
    oname = oname + ".tar.gz"

    file_name = f"{config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]}/{CONF_IMAGE}/{oname}"

    dir_output_remote = f"{config[CONF_CONFIG][CONF_DIR][CONF_REMOTE]}/{CONF_IMAGE}"

    if os.path.exists(file_name):
        LOGGER.debug("image: '%s' already exists", file_name)
        return

    # Save date/time to know how long it took
    now = datetime.datetime.now()

    # We do a docker save, because the python library does not seem to support it easily

    cmd = f"docker save '{name}' | gzip -c >{file_name}"
    LOGGER.debug("image: Executing '%s'", cmd)

    rc = os.system(cmd)
    if rc == 0:
        # Calculate how many seconds it took us to save image
        later = datetime.datetime.now()
        diff = (later - now).total_seconds()
        fsize = os.stat(file_name).st_size
        fsize = round(fsize / 1024, 1)
        unit = "kByte"

        # Change to MByte if needed
        if fsize > 1000:
            fsize = round(fsize / 1024, 1)
            unit = "MByte"

        LOGGER.debug(
            "image: Created '%s' (%d seconds, %d %s)", file_name, diff, fsize, unit,
        )

    else:
        errmsg = f"image: Creating '{file_name}' failed with RC={int(rc/256)}"
        ErrorMsg(errmsg)
        LOGGER.error(errmsg)
        return

    # We support 1 or more remote backup hosts
    for transfer in config[CONF_CONFIG][CONF_TRANSFER]:

        remotehost = transfer[CONF_HOST]
        remoteport = transfer[CONF_PORT]
        remoteuser = transfer[CONF_USER]

        # Check if we should run it on this host or not
        if transfer[CONF_RUN_HOST] and hostname not in transfer[CONF_RUN_HOST]:
            LOGGER.debug(
                "image: '%s' is not enabled on this run_host '%s'='%s'",
                remotehost,
                transfer[CONF_RUN_HOST],
                hostname,
            )
            continue

        # ping the backup node
        rc = os.system("ping -w 3 -c 2 " + remotehost + " >/dev/null")

        if rc != 0:
            errmsg = f"image: Cannot ping host '{remotehost}' RC={int(rc/256)}"
            ErrorMsg(errmsg)
            LOGGER.error(errmsg)
            continue

        LOGGER.debug("image: Ping host '%s' OK", remotehost)

        # make remote directory, possible it does not exist
        if transfer[CONF_TYPE] == CONF_SCP:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            # client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                remotehost,
                port=remoteport,
                username=remoteuser,
                auth_timeout=5,
                timeout=10,
            )

            LOGGER.debug("image: SSH host '%s' OK", remotehost)

            # make remote directory, possible it does not exist
            cmd = f"mkdir -p {dir_output_remote}"
            rc, stdout = remoteSSH(client, cmd, remotehost=remotehost)

            if not rc:
                continue

            LOGGER.debug("image: Remote directory '%s' OK", dir_output_remote)

            # Current time
            now = datetime.datetime.now()

            # scp it to the backup node
            rc = remoteSCP(
                client, f"{file_name}", dir_output_remote, remotehost=remotehost
            )

            if not rc:
                continue

            # Calculate how many seconds it took us to SCP
            later = datetime.datetime.now()
            diff = (later - now).total_seconds()
            fsize = os.stat(f"{file_name}").st_size
            fsize = round(fsize / 1024, 1)
            unit = "kByte"

            # Change to MByte if needed
            if fsize > 1000:
                fsize = round(fsize / 1024, 1)
                unit = "MByte"

            LOGGER.debug(
                "image: SCP '%s' OK (%d seconds, %d %s)",
                f"{file_name}",
                diff,
                fsize,
                unit,
            )

            # check the backup node, if the file is correct. For now, just a ls -l
            cmd = f"ls -l {dir_output_remote}/{oname}"
            rc, stdout = remoteSSH(client, cmd, remotehost=remotehost)
            if not rc:
                continue

            LOGGER.debug(
                "image: Remote file '%s' OK", f"{dir_output_remote}/{oname}",
            )

            client.close()

        # We get the following exception if SSH keys haven't been exchanged:
        # paramiko.ssh_exception.SSHException


#################################################################
def doImages():
    """Backup the images of all containers."""

    if args.get("mode", "") != "cleanup":
        # If it is disabled, we skip it
        if not config[CONF_CONFIG][CONF_IMAGE]:
            return

        if args.get("mode", "") != "image":
            # Check if we should execute today or not
            today = datetime.datetime.today().isoweekday()
            if today not in config[CONF_IMAGE][CONF_WEEKDAY]:
                LOGGER.debug("image: No image backup today")
                return

    # We only support the local Docker API
    client = docker.from_env()

    # List of images processeed
    processimages = []
    listimages = []

    # List all containers, even the stopped ones
    for container in client.containers.list(all=True):

        for image in container.image.tags:
            if image not in processimages:
                LOGGER.debug("image: %s (container: %s)", image, container.name)
                _backupImage(image)
                processimages.append(image)

                # Replace bad characters
                oname = image.replace("/", "_").replace(":", "%")
                oname = oname + ".tar.gz"
                listimages.append(oname)

                # We only are interested in first image tag
                break

    listimages.sort()
    outputname = (
        f"{config[CONF_CONFIG][CONF_DIR][CONF_LOCAL]}/{CONF_IMAGE}/imagelist.txt"
    )

    with open(outputname, "w") as fh:
        for image in listimages:
            fh.write(f"{image}\n")

    # Do SCP to Pi's with the output file

    for transfer in config[CONF_CONFIG][CONF_TRANSFER]:

        # ping the backup node
        remotehost = transfer[CONF_HOST]
        remoteport = transfer[CONF_PORT]
        remoteuser = transfer[CONF_USER]

        # Check if we should run it on this host or not
        if transfer[CONF_RUN_HOST] and hostname not in transfer[CONF_RUN_HOST]:
            LOGGER.debug(
                "image: '%s' is not enabled on this run_host '%s'='%s'",
                remotehost,
                transfer[CONF_RUN_HOST],
                hostname,
            )
            continue

        rc = os.system("ping -w 3 -c 2 " + remotehost + " >/dev/null")

        if rc != 0:
            errmsg = f"{typeName} {entry[CONF_NAME]}: Cannot ping host '{remotehost}' RC={int(rc/256)}"
            ErrorMsg(errmsg)
            LOGGER.error(errmsg)
            continue

        LOGGER.debug("Image: Ping host '%s' OK", remotehost)

        # make remote directory, possible it does not exist
        if transfer[CONF_TYPE] == CONF_SCP:
            # LOGGER.debug("Image: SCP to '%s:%s' with username '%s'", remotehost, remoteport, remoteuser)
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            # client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                remotehost,
                port=remoteport,
                username=remoteuser,
                auth_timeout=5,
                timeout=10,
            )

            LOGGER.debug("Image: SSH host '%s' OK", remotehost)

            # scp it to the backup node
            rc = remoteSCP(
                client,
                outputname,
                f"{config[CONF_CONFIG][CONF_DIR][CONF_REMOTE]}/{CONF_IMAGE}",
                remotehost=remotehost,
            )

            if not rc:
                continue

            LOGGER.debug("Image: transferred '%s' successfully to remote", outputname)
            client.close()


#################################################################
# Main
#################################################################

# Only root can access certain things, so we need this
if not os.geteuid() == 0:
    sys.exit("ERROR: Only root can run this script\n")

# Get hostname of this node
hostname = socket.gethostname()

args = parseArg()

config = readConfig()

if args.get("mode", "") in ["backup", "run_host"]:
    doBackupType(CONF_APP)
    doBackupType(CONF_DB)
    doBackupType(CONF_OTHER)
elif args.get("mode", "") == "restore":
    doRestoreType()
elif args.get("mode", "") == "image":
    doImages()
elif args.get("mode", "") == "cleanup":
    doCleanup()
else:
    doBackupType(CONF_APP)
    doBackupType(CONF_DB)
    doBackupType(CONF_OTHER)
    doImages()
    doCleanup()

# Report error(s) via Telegram
reportError()

# End
