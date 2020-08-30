#!/usr/bin/env python3

import datetime
import deconzapi
import docker
import logging
import os
import requests
import sh
import subprocess
import sys
import telegram
import voluptuous as vol
import yaml

from logging.handlers import RotatingFileHandler
from nsenter import Namespace

"""
requirements.txt:
docker==4.2.0
nsenter==0.2
python_telegram_bot==12.7
pyyaml==5.3.1
requests==2.23.0
sh==1.13.1
voluptuous==0.11.7

To install it under crontab, we need to do the following:
sudo /bin/bash
su -
pip3 install -r check-health-requirements.txt

data
----
docker-host:
  <name>:
    <container(s)>:
      count: <int>
      msg: <str>
      alarm: <date>
      clear: <date>
deconz:
  ...

"""

#################################################################
# Constants
#################################################################
CRITICAL = "CRITICAL"
DEBUG = "DEBUG"
ERROR = "ERROR"
INFO = "INFO"
WARNING = "WARNING"

CONF_ALARMCOUNT = "alarmcount"
CONF_APIKEY = "apikey"
CONF_CHAT_ID = "chat_id"
CONF_CLIENTS = "clients"
CONF_CODE = "code"
CONF_CONFIG = "config"
CONF_CONTAINER = "container"
CONF_CONTAINERS = "containers"
CONF_DATAFILE = "datafile"
CONF_DISABLE_NOTIFICATION = "disable_notification"
CONF_DNS = "dns"
CONF_ENABLED = "enabled"
CONF_HOST = "host"
CONF_HOSTS = "hosts"
CONF_IGNORE = "ignore"
CONF_INTERVAL = "interval"
CONF_LOGLEVEL = "loglevel"
CONF_NAME = "name"
CONF_NOTIFY = "notify"
CONF_PORT = "port"
CONF_REQUEST = "request"
CONF_TELEGRAM = "telegram"
CONF_TIMEOUT = "timeout"
CONF_TOKEN = "token"
CONF_TYPE = "type"

ATTR_ALARM = "alarm"
ATTR_CLEAR = "clear"
ATTR_CONTAINERS = "containers"
ATTR_COUNT = "count"
ATTR_DECONZ = "deconz"
ATTR_DOCKERHOST = "docker-host"
ATTR_GET = "GET"
ATTR_HEAD = "HEAD"
ATTR_HOSTS = "hosts"
ATTR_HTTP = "http"
ATTR_MSG = "msg"
ATTR_NAME = "name"
ATTR_TELEGRAM = "telegram"
ATTR_TYPE = "type"

#################################################################
logging.basicConfig(
    level=logging.ERROR, format="%(asctime)s %(levelname)s: %(message)s"
)
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)
LOGGER.propagate = False

#################################################################
BASE_SCHEMA = vol.Schema({})

# CLIENTS_SCHEMA = BASE_SCHEMA.extend(
CLIENTS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CONTAINERS, default=[]): list,
        vol.Optional(CONF_HOSTS, default=[]): list,
    }
)

DOCKERHOST_SCHEMA = BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): ATTR_DOCKERHOST,
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Optional(CONF_ALARMCOUNT): int,
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_CONTAINER): str,
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT): vol.Any(int, list),
        vol.Optional(CONF_DNS, default=False): bool,
        vol.Required(CONF_CLIENTS): vol.All(dict, CLIENTS_SCHEMA),
    },
    extra=vol.ALLOW_EXTRA,
)

HTTP_SCHEMA = BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): ATTR_HTTP,
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Optional(CONF_ALARMCOUNT): int,
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_REQUEST, default=ATTR_GET): vol.Any(
            ATTR_GET, ATTR_HEAD, vol.Upper
        ),
        vol.Optional(CONF_CODE, default=200): vol.All(),
        vol.Optional(CONF_TIMEOUT, default=5): int,
    },
    extra=vol.ALLOW_EXTRA,
)

DECONZ_SCHEMA = BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): ATTR_DECONZ,
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Optional(CONF_ALARMCOUNT): int,
        vol.Optional(CONF_NAME, default="DeCONZ"): str,
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=3080): int,
        vol.Required(CONF_APIKEY): str,
        vol.Optional(CONF_TIMEOUT, default=360): int,
        vol.Optional(CONF_IGNORE, default=[]): list,
    },
    extra=vol.ALLOW_EXTRA,
)

TELEGRAM_SCHEMA = BASE_SCHEMA.extend(
    {
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Required(CONF_TOKEN): str,
        vol.Required(CONF_CHAT_ID): int,
        vol.Optional(CONF_DISABLE_NOTIFICATION, default=False): bool,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_INTERVAL, default=60): int,
        vol.Optional(CONF_ALARMCOUNT, default=2): int,
        vol.Required(CONF_NOTIFY): str,
        vol.Optional(CONF_LOGLEVEL, default=DEBUG): vol.Any(
            CRITICAL, DEBUG, ERROR, INFO, WARNING, vol.Upper
        ),
        vol.Optional(CONF_CONFIG, default={}): vol.All(
            list, [vol.Any(DOCKERHOST_SCHEMA, HTTP_SCHEMA, DECONZ_SCHEMA)]
        ),
        vol.Optional(CONF_TELEGRAM, default={}): vol.Schema(TELEGRAM_SCHEMA),
    },
    extra=vol.ALLOW_EXTRA,
)

#################################################################
class HealthCheck:
    """Class of all our health checks."""

    def __init__(self):
        """Create the object with required parameters."""

        # Read the configuration
        self._readConfig()

        # Try to read data from the (temporary) file
        self._readData()

        # Define msg list, of information to send to me
        self._msg = []

        # Validate our configuration via voluptuous
        self._config = CONFIG_SCHEMA(self._config)

        # Set logging
        # Setup logging, logfile and rotation
        logname = __file__
        logname = logname.replace(".py", "")
        logname += ".log"
        maxBytes = 10 * 1024 * 1024
        backupCount = 3

        handler = RotatingFileHandler(
            logname, maxBytes=maxBytes, backupCount=backupCount
        )
        handler.setLevel(self._config[CONF_LOGLEVEL])
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
        )
        LOGGER.addHandler(handler)

    #############################################################
    def _readConfig(self):

        # If we get an argument, take first one as filename of our configuration file
        if len(sys.argv) > 1:
            configname = sys.argv[1]
        else:
            configname = "{}.yaml".format(
                os.path.splitext(os.path.abspath(__file__))[0]
            )

        try:
            with open(configname, "r") as f:
                self._config = yaml.safe_load(f)
        except FileNotFoundError:
            sys.exit("ERROR: No configuration file '{}' found".format(configname))

    #############################################################
    def _readData(self):

        if CONF_DATAFILE in self._config:
            self._datafile = self._config[CONF_DATAFILE]
        else:
            self._datafile = __file__
            self._datafile = self._datafile.replace(".py", "")
            self._datafile += ".data.yaml"

        try:
            with open(self._datafile, "r") as f:
                self._data = yaml.safe_load(f)
        except FileNotFoundError:
            LOGGER.info("No datafile '%s' found, using defaults", self._datafile)
            self._data = {}

    #############################################################
    def _writeData(self):
        """Write data file."""

        LOGGER.debug("Writing data file (%s)", self._datafile)

        # No error check yet ...
        with open(self._datafile, "w") as f:
            yaml.dump(self._data, f, default_flow_style=False)

    #############################################################
    def _handleMsg(self, alarm, type, subtype, name, entry, msg):
        """Handle Msg."""

        # Setup our structure
        self._data[type] = self._data.get(type, {})
        self._data[type][name] = self._data[type].get(name, {})
        self._data[type][name][entry] = self._data[type][name].get(entry, {})

        # shorthand and check if subtype exists or not
        if subtype != "":
            self._data[type][name][entry][subtype] = {}
            data = self._data[type][name][entry][subtype]
        else:
            data = self._data[type][name][entry]

        data[ATTR_COUNT] = self._data[type][name][entry].get(ATTR_COUNT, 0)
        data[ATTR_MSG] = self._data[type][name][entry].get(ATTR_MSG, "")

        # This is a clear alarm
        if alarm == ATTR_CLEAR:
            if data[ATTR_COUNT] >= self._config[CONF_ALARMCOUNT]:
                LOGGER.debug("Adding clear msg to the queue '%s'", msg)
                self._msg.append(entry)
                # Record the time when this happened
                data[ATTR_CLEAR] = datetime.datetime.now()

            data[ATTR_COUNT] = 0
            data[ATTR_MSG] = ""

        # A real alarm, check the counter
        if alarm == ATTR_ALARM:
            data[ATTR_COUNT] += 1
            data[ATTR_MSG] = msg

            if data[ATTR_COUNT] == 1:
                data[ATTR_ALARM] = datetime.datetime.now()

            if data[ATTR_COUNT] == self._config[CONF_ALARMCOUNT]:
                LOGGER.debug("Adding alarm msg to the queue '%s'", msg)

                # add all information we got, we can use it later in the notification
                entry = {}
                entry[ATTR_TYPE] = type
                entry[ATTR_NAME] = name
                entry[ATTR_ALARM] = alarm
                entry[ATTR_MSG] = msg
                self._msg.append(entry)
            else:
                LOGGER.debug(
                    "%s: Alarm ignored, counter is %d and not equal to %d",
                    type,
                    data[ATTR_COUNT],
                    self._config[CONF_ALARMCOUNT],
                )

    #############################################################
    def _dockerHost(self, config):
        """
        Function to check if container/external IP have connections
        open to our main container. This container is running in
        "network=host" like "hass" and "mosquitto".
        """

        # Check configuration
        for conf in [CONF_NAME, CONF_HOST, CONF_PORT, CONF_CLIENTS]:
            if conf not in config:
                LOGGER.error(
                    "%s: Invalid config, missing '%s' in config=%s",
                    ATTR_DOCKERHOST,
                    conf,
                    str(config),
                )
                return

        if not config[CONF_ENABLED]:
            LOGGER.debug("%s: %s is not enabled", ATTR_DOCKERHOST, config[CONF_NAME])
            return

        # Just report it in debug mode
        LOGGER.debug("%s: %s is enabled", ATTR_DOCKERHOST, config[CONF_NAME])
        LOGGER.debug("%s: config=%s", ATTR_DOCKERHOST, str(config))

        # Get our docker client
        client = docker.from_env()

        # Check if main docker container exist and is running
        try:
            container = client.containers.get(config[CONF_CONTAINER])
        except docker.errors.NotFound:
            # Container doesn't exit, so we shouldn't continue
            LOGGER.error(
                "%s: %s primary container %s does not exist",
                ATTR_DOCKERHOST,
                config[CONF_NAME],
                config[CONF_CONTAINER],
            )
            # Add to error list
            msg = "Container {} does not exist".format(config[CONF_CONTAINER])
            self._handleMsg(
                ATTR_ALARM,
                ATTR_DOCKERHOST,
                ATTR_CONTAINERS,
                config[CONF_NAME],
                config[CONF_CONTAINER],
                msg,
            )
            return

        # The container needs to be running, otherwise no connectivity can be there
        if container.status != "running":
            LOGGER.error(
                "%s: %s primary container %s not running",
                ATTR_DOCKERHOST,
                config[CONF_NAME],
                config[CONF_CONTAINER],
            )
            # Add to error list
            msg = "Container {} not running".format(config[CONF_CONTAINER])
            self._handleMsg(
                ATTR_ALARM,
                ATTR_DOCKERHOST,
                ATTR_CONTAINERS,
                config[CONF_NAME],
                config[CONF_CONTAINER],
                msg,
            )
            return

        pid = container.attrs["State"]["Pid"]
        LOGGER.debug(
            "%s: %s is running with pid=%d",
            ATTR_DOCKERHOST,
            config[CONF_CONTAINER],
            pid,
        )

        # Clear possible error with primary container
        msg = "Container {} alarm cleared".format(config[CONF_CONTAINER])
        self._handleMsg(
            ATTR_CLEAR,
            ATTR_DOCKERHOST,
            ATTR_CONTAINERS,
            config[CONF_NAME],
            config[CONF_CONTAINER],
            msg,
        )

        # Configure errorfound to False
        errorfound = False

        # Go through list of containers connected to primary
        if CONF_CONTAINERS in config[CONF_CLIENTS]:

            host = config[CONF_HOST]
            if self.isIPValid(config[CONF_HOST]):
                host = config[CONF_HOST].replace(".", "\.")

            # We support multiple port(s)
            checklist = []
            if type(config[CONF_PORT]).__name__ == "list":
                for port in config[CONF_PORT]:
                    checklist.append(
                        (".*:.*\s*" + host + ":" + str(port) + "\s*ESTABLISHED$")
                    )
            else:
                checklist.append(
                    (
                        ".*:.*\s*"
                        + host
                        + ":"
                        + str(config[CONF_PORT])
                        + "\s*ESTABLISHED$"
                    )
                )

            checkfor = "|".join(checklist)

            LOGGER.debug("%s: Connection string '%s'", ATTR_DOCKERHOST, checkfor)

            for name in config[CONF_CLIENTS][CONF_CONTAINERS]:

                # Check if client container exist and is running
                try:
                    container = client.containers.get(name)
                except docker.errors.NotFound:
                    # Container doesn't exit, so we shouldn't continue
                    LOGGER.error(
                        "%s: %s client container %s does not exist",
                        ATTR_DOCKERHOST,
                        config[CONF_NAME],
                        name,
                    )
                    # Add to error list
                    msg = "Container {} does not exist".format(name)
                    self._handleMsg(
                        ATTR_ALARM,
                        ATTR_DOCKERHOST,
                        ATTR_CONTAINERS,
                        config[CONF_NAME],
                        name,
                        msg,
                    )
                    errorfound = True
                    continue

                # The container needs to be running, otherwise no connectivity can be there
                if container.status != "running":
                    LOGGER.error(
                        "%s: %s client container %s not running",
                        ATTR_DOCKERHOST,
                        config[CONF_NAME],
                        name,
                    )
                    # Add to error list
                    msg = "Container {} not running".format(name)
                    self._handleMsg(
                        ATTR_ALARM,
                        ATTR_DOCKERHOST,
                        ATTR_CONTAINERS,
                        config[CONF_NAME],
                        name,
                        msg,
                    )
                    errorfound = True
                    continue

                pid = container.attrs["State"]["Pid"]
                LOGGER.debug(
                    "%s: %s is running with pid=%d", ATTR_DOCKERHOST, name, pid
                )

                # Check if we have connectivity, we go in their namespace
                # With docker this is *only* possible through namespace and shell,
                # there doesn't seem to be a simple python option
                with Namespace(pid, "net"):
                    try:
                        netstatparam = "-a" if config[CONF_DNS] else "-na"
                        outp = sh.egrep(
                            sh.netstat(netstatparam, _tty_out=False), checkfor
                        )
                    except sh.ErrorReturnCode_1:
                        # Not found, so no connection
                        LOGGER.error(
                            "%s: container %s not connected %s",
                            ATTR_DOCKERHOST,
                            name,
                            config[CONF_NAME],
                        )

                        msg = "Container {} not connected to {}".format(
                            config[CONF_CONTAINER], config[CONF_NAME]
                        )
                        self._handleMsg(
                            ATTR_ALARM,
                            ATTR_DOCKERHOST,
                            ATTR_CONTAINERS,
                            config[CONF_NAME],
                            name,
                            msg,
                        )
                        errorfound = True
                        continue

                    except sh.ErrorReturnCode as e:
                        # Not good, shouldn't happen
                        LOGGER.error(
                            "%s: container %s returned an error with checkfor='%s'. msg='%s'",
                            ATTR_DOCKERHOST,
                            name,
                            checkfor,
                            str(e),
                        )

                        msg = "Container {} not connected to {} (RC>1)".format(
                            config[CONF_CONTAINER], config[CONF_NAME]
                        )
                        self._handleMsg(
                            ATTR_ALARM,
                            ATTR_DOCKERHOST,
                            ATTR_CONTAINERS,
                            config[CONF_NAME],
                            name,
                            msg,
                        )
                        errorfound = True
                        continue

                    # RC=0, should be good
                    #if outp.count("\n") > 1:
                    #    LOGGER.error(
                    #        "%s: container %s returned more then 1 line '%s'",
                    #        ATTR_DOCKERHOST,
                    #        name,
                    #        outp,
                    #    )

                    LOGGER.debug(
                        "%s: container %s connected to %s",
                        ATTR_DOCKERHOST,
                        name,
                        config[CONF_NAME],
                    )

                # Clear possible error with primary container
                msg = "Container {} alarm cleared".format(name)
                self._handleMsg(
                    ATTR_CLEAR,
                    ATTR_DOCKERHOST,
                    ATTR_CONTAINERS,
                    config[CONF_NAME],
                    name,
                    msg,
                )

        # Check the hosts (external IPs)
        if CONF_HOSTS in config[CONF_CLIENTS]:

            host = config[CONF_HOST]
            if self.isIPValid(config[CONF_HOST]):
                host = config[CONF_HOST].replace(".", "\.")

            # We support multiple port(s)
            checklist = []
            if type(config[CONF_PORT]).__name__ == "list":
                for port in config[CONF_PORT]:
                    checklist.append(
                        "\s*" + host + ":" + str(port) + "\s*{}:.*\s*ESTABLISHED$"
                    )
            else:
                checklist.append(
                    "\s*"
                    + host
                    + ":"
                    + str(config[CONF_PORT])
                    + "\s*{}:.*\s*ESTABLISHED$"
                )

            checkfor = "|".join(checklist)

            checkfor = (
                "\s*" + host + ":" + str(config[CONF_PORT]) + "\s*{}:.*\s*ESTABLISHED$"
            )

            for name in config[CONF_CLIENTS][CONF_HOSTS]:

                try:
                    netstatparam = "-a" if config[CONF_DNS] else "-na"
                    host = name
                    if self.isIPValid(name):
                        host = name.replace(".", "\.")

                    LOGGER.debug(
                        "%s: Connection string '%s'",
                        ATTR_DOCKERHOST,
                        checkfor.format(host),
                    )
                    outp = sh.egrep(
                        sh.netstat(netstatparam, _tty_out=False), checkfor.format(host)
                    )
                except sh.ErrorReturnCode_1:
                    # Not found, so no connection
                    LOGGER.error(
                        "%s: host %s not connected %s",
                        ATTR_DOCKERHOST,
                        name,
                        config[CONF_NAME],
                    )

                    msg = "Host {} not connected to {}".format(name, config[CONF_NAME])
                    self._handleMsg(
                        ATTR_ALARM,
                        ATTR_DOCKERHOST,
                        ATTR_HOSTS,
                        config[CONF_NAME],
                        name,
                        msg,
                    )
                    errorfound = True
                    continue

                except sh.ErrorReturnCode as e:
                    # Not good, shouldn't happen
                    LOGGER.error(
                        "%s: host %s returned an error with checkfor='%s'. msg='%s'",
                        ATTR_DOCKERHOST,
                        name,
                        checkfor.format(host),
                        str(e),
                    )

                    msg = "Host {} not connected to {} (RC>1)".format(
                        name, config[CONF_NAME]
                    )
                    self._handleMsg(
                        ATTR_ALARM,
                        ATTR_DOCKERHOST,
                        ATTR_HOSTS,
                        config[CONF_NAME],
                        name,
                        msg,
                    )
                    errorfound = True
                    continue

                # RC=0, should be good
                if outp.count("\n") > 1:
                    LOGGER.error(
                        "%s: host %s returned more then 1 line '%s'",
                        ATTR_DOCKERHOST,
                        name,
                        outp,
                    )

                LOGGER.debug(
                    "%s: host %s connected to %s",
                    ATTR_DOCKERHOST,
                    name,
                    config[CONF_NAME],
                )

                # Clear possible error with primary container
                msg = "Host {} alarm cleared".format(name)
                self._handleMsg(
                    ATTR_CLEAR,
                    ATTR_DOCKERHOST,
                    ATTR_HOSTS,
                    config[CONF_NAME],
                    name,
                    msg,
                )

        # Configure errorfound to False
        if not errorfound:
            LOGGER.debug("%s: OK", ATTR_DOCKERHOST)

    #############################################################
    def dockerHost(self):
        """Check all docker-host entries."""
        for entry in self._config[CONF_CONFIG]:
            if entry[CONF_TYPE] == ATTR_DOCKERHOST:
                self._dockerHost(entry)

        self._writeData()

    #############################################################
    def _checkHttp(self, config):
        """Check for HTTP or HTTPS."""

        if not config[CONF_ENABLED]:
            LOGGER.debug("%s: %s is not enabled", ATTR_HTTP, config[CONF_NAME])
            return

        try:
            LOGGER.debug(
                "%s: Checking URL (%s) %s",
                ATTR_HTTP,
                config[CONF_REQUEST],
                config[CONF_HOST],
            )
            req = requests.request(
                config[CONF_REQUEST], config[CONF_HOST], timeout=config[CONF_TIMEOUT]
            )

        # requests.exceptions.InvalidURL
        # requests.exceptions.ConnectionError
        except Exception as e:
            LOGGER.error("%s: Exception=%s Msg=%s", ATTR_HTTP, type(e).__name__, str(e))

            # Raise alarm
            msg = "{} not reachable".format(config[CONF_HOST])
            self._handleMsg(
                ATTR_ALARM, ATTR_HTTP, "", config[CONF_NAME], config[CONF_HOST], msg
            )

            return

        # Check if code matches the allowed one/list
        if req.status_code != config[CONF_CODE]:
            LOGGER.error("%s: Not allowed code=%d", ATTR_HOST, req.status_code)
            # Raise alarm
            msg = "{} returned code=%d".format(config[CONF_HOST], req.status_code)
            self._handleMsg(
                ATTR_ALARM, ATTR_HTTP, "", config[CONF_NAME], config[CONF_HOST], msg
            )
            return

        # No error, lets check the response code
        LOGGER.debug("%s: Allowed code=%d (OK)", ATTR_HTTP, req.status_code)

        # Clear possible error with primary container
        msg = "Check {} alarm cleared".format(config[CONF_HOST])
        self._handleMsg(
            ATTR_CLEAR, ATTR_HTTP, "", config[CONF_NAME], config[CONF_HOST], msg
        )

    #############################################################
    def checkHttp(self):
        """Check all http entries."""

        for entry in self._config[CONF_CONFIG]:
            if entry[CONF_TYPE] == ATTR_HTTP:
                self._checkHttp(entry)

        self._writeData()

    #############################################################
    def _checkDeCONZ(self, config):
        """Check for DeCONZ lastupdated information."""

        if not config[CONF_ENABLED]:
            LOGGER.debug("%s: %s is not enabled", ATTR_DECONZ, config[CONF_NAME])
            return

        try:
            LOGGER.debug(
                "%s: Checking DeCONZ %s:%s",
                ATTR_DECONZ,
                config[CONF_HOST],
                config[CONF_PORT],
            )

            api = deconzapi.DeCONZAPI(
                config[CONF_HOST], config[CONF_PORT], config[CONF_APIKEY]
            )
            devices = api.get_all_devices()

        except Exception as e:
            LOGGER.error("%s: Exception=%s Msg=%s", ATTR_HTTP, type(e).__name__, str(e))

            # Raise alarm
            msg = "DeCONZ {} error".format(config[CONF_HOST])
            self._handleMsg(
                ATTR_ALARM, ATTR_DECONZ, "", config[CONF_NAME], config[CONF_HOST], msg
            )

            return

        # Handle API issue
        if devices is None:
            LOGGER.error("%d: Returned None?", ATTR_DECONZ)
            return

        if len(devices) == 0:
            LOGGER.error("%s: Returned 0 devices", ATTR_DECONZ)
            return
        else:
            # Report device count
            LOGGER.debug("%s: %d device(s) retrieved", ATTR_DECONZ, len(devices))

        # Loop through devices
        for dev in devices:

            # Check if we should ignore this one
            if dev[deconzapi.DECONZ_ATTR_NAME] in config[CONF_IGNORE]:
                LOGGER.debug(
                    "%s: Ignored device name %s (%s:%s)",
                    ATTR_DECONZ,
                    dev[deconzapi.DECONZ_ATTR_NAME],
                    dev[deconzapi.DECONZ_CATEGORY],
                    dev[deconzapi.DECONZ_ATTR_TYPE],
                )
                continue

            # Only process useable devices, ignore e.g. Dresden/Conbee fake ones
            if dev[deconzapi.DECONZ_ATTR_TYPE] not in deconzapi.DECONZ_TYPE_USEABLE:
                LOGGER.debug(
                    "%s: Ignored device type %s (%s:%s)",
                    ATTR_DECONZ,
                    dev[deconzapi.DECONZ_ATTR_NAME],
                    dev[deconzapi.DECONZ_CATEGORY],
                    dev[deconzapi.DECONZ_ATTR_TYPE],
                )
                continue

            lastupdated = dev.get(deconzapi.DECONZ_ATTR_LASTUPDATED, None)
            if lastupdated is None:
                LOGGER.warn(
                    "%s: Device %s (%s:%s) has no lastupdated value (reachable=%s)",
                    ATTR_DECONZ,
                    dev[deconzapi.DECONZ_ATTR_NAME],
                    dev[deconzapi.DECONZ_CATEGORY],
                    dev[deconzapi.DECONZ_ATTR_TYPE],
                    dev[deconzapi.DECONZ_ATTR_REACHABLE],
                )
                continue

            # Get lastupdated from device, but it is always in UTC format
            # Fix a new 'feature' in 2.05.79, it adds milliseconds to lastupdated
            lastupdated = lastupdated[:19]
            # Fix 2.05.80 feature when no seconds are supplied
            lastupdated = lastupdated.replace(".", ":")
            lastupdated = datetime.datetime.strptime(lastupdated, "%Y-%m-%dT%H:%M:%S")
            delta = round(((datetime.datetime.utcnow() - lastupdated).seconds) / 60, 2)

            if delta > config[CONF_TIMEOUT]:
                LOGGER.error(
                    "%s: Device %d (%s:%s) last update is %d minute(s) ago (reachable=%s)",
                    ATTR_DECONZ,
                    dev[deconzapi.DECONZ_ATTR_NAME],
                    dev[deconzapi.DECONZ_CATEGORY],
                    dev[deconzapi.DECONZ_ATTR_TYPE],
                    delta,
                    dev[deconzapi.DECONZ_ATTR_REACHABLE],
                )

                # Raise alarm
                msg = "DeCONZ {} last updated is {} minutes ago".format(
                    dev[deconzapi.DECONZ_ATTR_NAME], int(delta)
                )
                self._handleMsg(
                    ATTR_ALARM,
                    ATTR_DECONZ,
                    "",
                    config[CONF_NAME],
                    dev[deconzapi.DECONZ_ATTR_NAME],
                    msg,
                )
                continue

            LOGGER.debug(
                "%s: Device %s (%s:%s) last updated is %d minute(s) ago (reachable=%s)",
                ATTR_DECONZ,
                dev[deconzapi.DECONZ_ATTR_NAME],
                dev[deconzapi.DECONZ_CATEGORY],
                dev[deconzapi.DECONZ_ATTR_TYPE],
                delta,
                dev[deconzapi.DECONZ_ATTR_REACHABLE],
            )

            # Clear possible DeCONZ error
            msg = "Check {} alarm cleared".format(config[CONF_HOST])
            self._handleMsg(
                ATTR_CLEAR,
                ATTR_DECONZ,
                "",
                config[CONF_NAME],
                dev[deconzapi.DECONZ_ATTR_NAME],
                msg,
            )

    #############################################################
    def checkDeCONZ(self):
        """Check all DeCONZ entries."""

        for entry in self._config[CONF_CONFIG]:
            if entry[CONF_TYPE] == ATTR_DECONZ:
                self._checkDeCONZ(entry)

        self._writeData()

    #############################################################
    def sendMsg(self):
        """
        Function to send all alarms via Telegram/etc
        It can be called 1 or multiple times
        """

        if len(self._msg) == 0:
            return

        LOGGER.debug("%d message(s) in the send queue", len(self._msg))

        msg = []
        for entry in self._msg:
            msg.append(entry[ATTR_MSG])

        # Send the msg(s)
        msgtext = ",\n".join(msg)

        if self._config[CONF_NOTIFY] == ATTR_TELEGRAM:
            bot = telegram.Bot(self._config[CONF_TELEGRAM][CONF_TOKEN])
            bot.send_message(
                chat_id=self._config[CONF_TELEGRAM][CONF_CHAT_ID],
                disable_notification=self._config[CONF_TELEGRAM][
                    CONF_DISABLE_NOTIFICATION
                ],
                text=msgtext,
            )

        """
markdown:
bot.send_message(chat_id=chat_id,
                 text="*bold* _italic_ `fixed width font` [link](http://google.com)\.",
                 parse_mode=telegram.ParseMode.MARKDOWN_V2)

html:
bot.send_message(chat_id=chat_id,
                 text='<b>bold</b> <i>italic</i> <a href="http://google.com">link</a>.',
                 parse_mode=telegram.ParseMode.HTML)
        """

        # Clear the send msg queue
        self._msg = []

    #############################################################
    @staticmethod
    def isIPValid(IP):
        def isIPv4(s):
            try:
                return str(int(s)) == s and 0 <= int(s) <= 255
            except:
                return False

        def isIPv6(s):
            if len(s) > 4:
                return False
            try:
                return int(s, 16) >= 0 and s[0] != "-"
            except:
                return False

        if IP.count(".") == 3 and all(isIPv4(i) for i in IP.split(".")):
            return True
        if IP.count(":") == 7 and all(isIPv6(i) for i in IP.split(":")):
            return True
        return False


#################################################################
# Main
#################################################################


def main():

    # Only root can access certain things, so we need this
    if not os.geteuid() == 0:
        sys.exit("ERROR: Only root can run this script\n")

    check = HealthCheck()

    # do interval look here?
    check.dockerHost()
    check.checkHttp()
    check.checkDeCONZ()

    # test telegram
    check.sendMsg()


# LOGGER.propagate = False

if __name__ == "__main__":
    main()

# End
