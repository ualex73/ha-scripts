#!/usr/bin/env python3

"""
XXX
https://github.com/fschulze/check-tls-certs/blob/main/check_tls_certs.py
https://www.activestate.com/blog/how-to-manage-tls-certificate-expiration-with-python/
XXX

Install the following python libraries. This must happen as root (su root):

pip3 install paramiko==2.7.2
pip3 install python_telegram_bot==13.7
pip3 install pyOpenSSL==21.0.0
pip3 install scp==0.14.1
pip3 install voluptuous==0.12.2
pip3 install pyyaml==5.4.1
"""

import datetime
import glob
import logging
import OpenSSL
import os
import paramiko
import scp
import smtplib
import socket
import ssl
import sys
import telegram
import voluptuous as vol
import yaml

from logging.handlers import RotatingFileHandler

#################################################################
CRITICAL = "CRITICAL"
DEBUG = "DEBUG"
ERROR = "ERROR"
INFO = "INFO"
WARNING = "WARNING"

CONF_CHAT_ID = "chat_id"
CONF_CHECK = "check"
CONF_CONFIG = "config"
CONF_DATE = "date"
CONF_DAYINT = "dayint"
CONF_DAYS = "days"
CONF_DISABLE_NOTIFICATION = "disable_notification"
CONF_EMAIL = "email"
CONF_ENABLED = "enabled"
CONF_FILE = "file"
CONF_FILENAME = "filename"
CONF_HOST = "host"
CONF_HTTPS = "https"
CONF_LOGLEVEL = "loglevel"
CONF_MODE = "mode"
CONF_NAME = "name"
CONF_PASSWORD = "password"
CONF_PORT = "port"
CONF_RUN_HOST = "run_host"
CONF_TELEGRAM = "telegram"
CONF_TEMPLATE = "template"
CONF_TLS = "yes"
CONF_TRANSFER = "transfer"
CONF_TOKEN = "token"
CONF_TYPE = "type"
CONF_USER = "user"
CONF_WEEKDAY = "weekday"

ATTR_ALL = "all"
ATTR_BEFOREDATE = "beforedate"
ATTR_BEFOREDAYS = "beforedays"
ATTR_DAYINT = "dayint"
ATTR_DAYS = "days"
ATTR_EMAIL = "email"
ATTR_EXPDATE = "expdate"
ATTR_EXPDAYS = "expdays"
ATTR_MASTER = "master"
ATTR_MSG = "msg"
ATTR_NAME = "name"
ATTR_NONE = "none"
ATTR_SCP = "scp"
ATTR_SLAVE = "slave"
ATTR_NOTIFICATION = "notification"
ATTR_TYPE = "type"

#################################################################

CHECK_HTTPS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Optional(CONF_RUN_HOST, default=[]): list,
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=443): int,
        vol.Optional(CONF_DAYS, default=25): int,
        vol.Optional(CONF_DAYINT, default=5): int,
    }
)

CHECK_FILE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Optional(CONF_RUN_HOST, default=[]): list,
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_FILENAME): str,
        vol.Optional(CONF_DAYS, default=25): int,
        vol.Optional(CONF_DAYINT, default=5): int,
    }
)

CHECK_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_HTTPS, default=[]): vol.All(
            list, [vol.Any(CHECK_HTTPS_SCHEMA)]
        ),
        vol.Optional(CONF_FILE, default=[]): vol.All(
            list, [vol.Any(CHECK_FILE_SCHEMA)]
        ),
    }
)

EMAIL_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENABLED, default=True): bool,
        vol.Optional(CONF_USER, default=""): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
        vol.Optional(CONF_HOST, default=""): str,
        vol.Optional(CONF_PORT, default=587): int,
        vol.Optional(CONF_TLS, default=True): bool,
        vol.Optional(CONF_EMAIL, default=""): str,
        vol.Optional(CONF_TEMPLATE, default="%TEXT%"): str,
        vol.Optional(CONF_WEEKDAY, default=[7]): list,
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

MASTERSLAVE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TYPE, default=ATTR_SCP): vol.Any(ATTR_SCP),
        vol.Optional(CONF_HOST, default=""): str,
        vol.Optional(CONF_PORT, default=22): int,
        vol.Optional(CONF_USER, default=""): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
        vol.Optional(CONF_FILENAME, default=""): str,
    }
)

CONF_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_LOGLEVEL, default=DEBUG): vol.Any(
            CRITICAL, DEBUG, ERROR, INFO, WARNING, vol.Upper
        ),
        vol.Optional(CONF_TRANSFER, default={}): vol.Schema(MASTERSLAVE_SCHEMA),
        vol.Optional(CONF_EMAIL, default={}): vol.Schema(EMAIL_SCHEMA),
        vol.Optional(CONF_TELEGRAM, default={}): vol.Schema(TELEGRAM_SCHEMA),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CONFIG, default={}): CONF_SCHEMA,
        vol.Optional(CONF_CHECK, default={}): CHECK_SCHEMA,
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
class certificateClass:
    """Class for checking certificates and other features."""

    def __init__(self):
        """Create the object with required parameters."""

        # Mode: none, master or slave
        self._mode = ATTR_NONE

        # Create empty array to send as warning
        self._msg = []

        # Get hostname of this node
        self._hostname = socket.gethostname()

        # List of certificate files/https and their expiry
        self._data = {}
        self._dataSlave = {}
        self._data[CONF_DATE] = datetime.datetime.now()
        self._data[CONF_FILE] = {}
        self._data[CONF_HTTPS] = {}

        # Read the configuration
        self._readConfig()

    #############################################################
    def _readConfig(self):

        self._configName = f"{os.path.splitext(os.path.abspath(__file__))[0]}.yaml"
        self._config = None

        try:
            with open(self._configName, "r") as f:
                self._config = yaml.safe_load(f)
                self._config = CONFIG_SCHEMA(self._config)
        except Exception as e:
            errmsg = f"Exception={type(e).__name__} Msg={e}"
            LOGGER.error(errmsg, exc_info=True)
            sys.exit(1)

        # Setup logging, logfile and rotation
        logname = f"{os.path.splitext(os.path.abspath(__file__))[0]}.log"

        # Define maximum logfile as 1MByte. 1MByte should hold 3+ weeks of logging
        maxBytes = 1 * 1024 * 1024
        backupCount = 3
        logFormat = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
        logLevel = "DEBUG"

        LOGGER.propagate = False
        handlerFile = RotatingFileHandler(
            logname, maxBytes=maxBytes, backupCount=backupCount
        )
        handlerFile.setLevel(self._config[CONF_CONFIG][CONF_LOGLEVEL])
        handlerFile.setFormatter(logFormat)
        LOGGER.addHandler(handlerFile)

        # If run manually, also log to the console
        if os.isatty(sys.stdin.fileno()):
            handlerConsole = logging.StreamHandler(sys.stdout)
            handlerConsole.setLevel(logging.DEBUG)
            handlerConsole.setFormatter(logFormat)
            LOGGER.addHandler(handlerConsole)

        LOGGER.info("Using config file '%s'", self._configName)
        # LOGGER.debug("Config: %s", self._config)

        # Some basic checks
        if self._mode == ATTR_SLAVE:

            if not self._config[CONF_CONFIG][CONF_TRANSFER][CONF_FILENAME]:
                LOGGER.error("Config: Mode=Slave, but no filename specified")
                return

    #############################################################
    def _checkFile(self, entry):

        # First expand the filename to 1 or more file(s)
        lof = glob.glob(entry[CONF_FILENAME])

        # We require 1 or more files
        if len(lof) == 0:
            LOGGER.error(
                "file %s: File '%s' does not exist",
                entry[CONF_NAME],
                entry[CONF_FILENAME],
            )

        # Loop through the filelist
        for filename in lof:

            LOGGER.debug("file %s: Processing '%s'", entry[CONF_NAME], filename)

            # Read certificate file
            file = open(filename, "r")
            certData = file.read()
            file.close()

            # Try to get certificate information
            try:
                certInfo = OpenSSL.crypto.load_certificate(
                    OpenSSL.crypto.FILETYPE_PEM, certData
                )
            except Exception as e:
                errmsg = f"file {entry[CONF_NAME]}: Exception on file '{filename}'. Exception={type(e).__name__} Msg={e}"
                LOGGER.error(errmsg, exc_info=True)
                continue

            # Retrieve certificate dates
            dateNow = datetime.datetime.now()
            dateNotBefore = datetime.datetime.strptime(
                certInfo.get_notBefore().decode("ascii"), "%Y%m%d%H%M%SZ"
            )
            dateNotAfter = datetime.datetime.strptime(
                certInfo.get_notAfter().decode("ascii"), "%Y%m%d%H%M%SZ"
            )
            deltaNotBefore = (dateNow - dateNotBefore).days
            deltaNotAfter = (dateNotAfter - dateNow).days

            LOGGER.debug(
                "file %s: NotBefore: %s (%d days), NotAfter: %s (%d days)",
                entry[CONF_NAME],
                dateNotBefore,
                deltaNotBefore,
                dateNotAfter,
                deltaNotAfter,
            )

            # Add it to an internal dictionary, for later reporting
            self._data[CONF_FILE][filename] = {}
            self._data[CONF_FILE][filename][ATTR_NAME] = entry[CONF_NAME]
            self._data[CONF_FILE][filename][ATTR_DAYS] = entry[CONF_DAYS]
            self._data[CONF_FILE][filename][ATTR_DAYINT] = entry[CONF_DAYINT]
            self._data[CONF_FILE][filename][ATTR_EXPDATE] = dateNotAfter
            self._data[CONF_FILE][filename][ATTR_EXPDAYS] = deltaNotAfter
            self._data[CONF_FILE][filename][ATTR_BEFOREDATE] = dateNotBefore
            self._data[CONF_FILE][filename][ATTR_BEFOREDAYS] = deltaNotBefore

    #############################################################
    def checkFile(self):

        if CONF_CHECK not in self._config:
            return

        if CONF_FILE not in self._config[CONF_CHECK]:
            return

        for entry in self._config[CONF_CHECK][CONF_FILE]:

            if entry[CONF_RUN_HOST] and self._hostname not in entry[CONF_RUN_HOST]:
                LOGGER.debug(
                    "file %s: is not enabled on this run_host '%s'='%s'",
                    entry[CONF_NAME],
                    entry[CONF_RUN_HOST],
                    self._hostname,
                )
                continue

            try:
                self._checkFile(entry)
            except Exception as e:
                errmsg = f"file {entry[CONF_NAME]}: Exception. Exception={type(e).__name__} Msg={e}"
                LOGGER.error(errmsg, exc_info=True)

    #############################################################
    def _checkHttps(self, entry):

        LOGGER.debug(
            "https %s: Processing '%s:%s'",
            entry[CONF_NAME],
            entry[CONF_HOST],
            entry[CONF_PORT],
        )

        # Retrieve the server certificate in PEM format
        context = ssl.create_default_context()

        with socket.create_connection((entry[CONF_HOST], entry[CONF_PORT])) as sock:
            with context.wrap_socket(sock, server_hostname=entry[CONF_HOST]) as sslsock:

                der_cert = sslsock.getpeercert(True)

                # from binary DER format to PEM
                certData = ssl.DER_cert_to_PEM_cert(der_cert)

                # Try to get certificate information
                try:
                    certInfo = OpenSSL.crypto.load_certificate(
                        OpenSSL.crypto.FILETYPE_PEM, certData
                    )
                except Exception as e:
                    errmsg = f"https {entry[CONF_NAME]}: Exception on https '{entry[CONF_HOST]}:{entry[CONF_PORT]}'. Exception={type(e).__name__} Msg={e}"
                    LOGGER.error(errmsg, exc_info=True)
                    return

                # Retrieve certificate dates
                dateNow = datetime.datetime.now()
                dateNotBefore = datetime.datetime.strptime(
                    certInfo.get_notBefore().decode("ascii"), "%Y%m%d%H%M%SZ"
                )
                dateNotAfter = datetime.datetime.strptime(
                    certInfo.get_notAfter().decode("ascii"), "%Y%m%d%H%M%SZ"
                )
                deltaNotBefore = (dateNow - dateNotBefore).days
                deltaNotAfter = (dateNotAfter - dateNow).days

                LOGGER.debug(
                    "https %s: NotBefore: %s (%d days), NotAfter: %s (%d days)",
                    entry[CONF_NAME],
                    dateNotBefore,
                    deltaNotBefore,
                    dateNotAfter,
                    deltaNotAfter,
                )

                # Add it to an internal dictionary, for later reporting
                key = f"{entry[CONF_HOST]}:{entry[CONF_PORT]}"
                self._data[CONF_HTTPS][key] = {}
                self._data[CONF_HTTPS][key][ATTR_NAME] = entry[CONF_NAME]
                self._data[CONF_HTTPS][key][ATTR_DAYS] = entry[CONF_DAYS]
                self._data[CONF_HTTPS][key][ATTR_DAYINT] = entry[CONF_DAYINT]
                self._data[CONF_HTTPS][key][ATTR_EXPDATE] = dateNotAfter
                self._data[CONF_HTTPS][key][ATTR_EXPDAYS] = deltaNotAfter
                self._data[CONF_HTTPS][key][ATTR_BEFOREDATE] = dateNotBefore
                self._data[CONF_HTTPS][key][ATTR_BEFOREDAYS] = deltaNotBefore

    #############################################################
    def checkHttps(self):

        if CONF_CHECK not in self._config:
            return

        if CONF_HTTPS not in self._config[CONF_CHECK]:
            return

        for entry in self._config[CONF_CHECK][CONF_HTTPS]:

            if entry[CONF_RUN_HOST] and self._hostname not in entry[CONF_RUN_HOST]:
                LOGGER.debug(
                    "https %s: is not enabled on this run_host '%s'='%s'",
                    entry[CONF_NAME],
                    entry[CONF_RUN_HOST],
                    self._hostname,
                )
                continue

            try:
                self._checkHttps(entry)
            except Exception as e:
                errmsg = f"https {entry[CONF_NAME]}: Exception. Exception={type(e).__name__} Msg={e}"
                LOGGER.error(errmsg, exc_info=True)

    #############################################################
    def checkDoSlave(self):
        """Do some work for slave work, like write or pull file."""

        # If this is the slave, just write file and done
        if self._mode == ATTR_SLAVE:

            if not self._config[CONF_CONFIG][CONF_TRANSFER][CONF_FILENAME]:
                LOGGER.error("Transfer filename is not defined")
                return

            with open(
                self._config[CONF_CONFIG][CONF_TRANSFER][CONF_FILENAME], "w"
            ) as f:
                yaml.dump(self._data, f, default_flow_style=False)

            return

        # Pull the file from the slave
        if self._mode == ATTR_MASTER:

            self.remoteSCP()

            fileName = self._config[CONF_CONFIG][CONF_TRANSFER][CONF_FILENAME]
            if not os.path.isfile(fileName):
                msg = f"File '{fileName}' not found"
                self._msg.append(
                    {
                        ATTR_TYPE: ATTR_NOTIFICATION,
                        ATTR_MSG: "ERROR: " + msg,
                        ATTR_EXPDAYS: -1,
                    }
                )
                LOGGER.error(msg)
                return

            try:
                with open(fileName, "r") as f:
                    self._dataSlave = yaml.safe_load(f)
            except Exception as e:
                msg = f"File '{fileName}' has invalid yaml format"
                LOGGER.error(msg)
                self._msg.append(
                    {
                        ATTR_TYPE: ATTR_NOTIFICATION,
                        ATTR_MSG: "ERROR: " + msg,
                        ATTR_EXPDAYS: -1,
                    }
                )

                errmsg = f"{msg}. Exception={type(e).__name__} Msg={e}"
                LOGGER.error(errmsg, exc_info=True)

                self._dataSlave = {}
                return

            # Check date of file
            try:
                if (
                    self._dataSlave[CONF_DATE].date()
                    != datetime.datetime.today().date()
                ):
                    msg = f"File '{fileName}' has wrong date format. Today={datetime.datetime.today().date()}, Received={self._dataSlave[CONF_DATE].date()}"
                    LOGGER.error(msg)
                    self._msg.append(
                        {
                            ATTR_TYPE: ATTR_NOTIFICATION,
                            ATTR_MSG: "ERROR: " + msg,
                            ATTR_EXPDAYS: -1,
                        }
                    )

                    self._dataSlave = {}
                    return

            except Exception as e:
                msg = f"File '{fileName}' has invalid date field"
                LOGGER.error(msg)

                errmsg = f"{msg}. Exception={type(e).__name__} Msg={e}"
                LOGGER.error(errmsg, exc_info=True)

                self._dataSlave = {}
                return

    #############################################################
    def _checkData(self, type, key, entry):
        """..."""

        # Check if it is already expired
        if entry[ATTR_EXPDAYS] <= 0:
            msg = f"{type} '{key}' expired ({entry[ATTR_EXPDAYS]} days)"
            self._msg.append(
                {ATTR_TYPE: ATTR_NOTIFICATION, ATTR_MSG: msg, ATTR_EXPDAYS: 0}
            )
            return

        # Calculate future date, more human readable ;-)
        fdate = datetime.datetime.today().date() + datetime.timedelta(days=entry[ATTR_EXPDAYS])
        fdate = fdate.strftime('%Y-%m-%d')

        msg = f"{type} '{key}' will expire in {entry[ATTR_EXPDAYS]} days ({fdate})"

        expiry = False
        if entry[ATTR_EXPDAYS] == entry[ATTR_DAYS]:
            expiry = True

        if (
            entry[ATTR_EXPDAYS] < entry[ATTR_DAYS]
            and (entry[ATTR_EXPDAYS] % entry[ATTR_DAYINT]) == 0
        ):
            expiry = True

        if expiry:
            self._msg.append(
                {
                    ATTR_TYPE: ATTR_NOTIFICATION,
                    ATTR_MSG: msg,
                    ATTR_EXPDAYS: entry[ATTR_EXPDAYS],
                }
            )
        else:
            self._msg.append(
                {
                    ATTR_TYPE: ATTR_EMAIL,
                    ATTR_MSG: msg,
                    ATTR_EXPDAYS: entry[ATTR_EXPDAYS],
                }
            )

    #############################################################
    def checkData(self):
        """Process self._data. If we are the master, collect a possible slave information and report it."""

        # This must be a master, otherwise do not continue
        if not self._mode in [ATTR_NONE, ATTR_MASTER]:
            return

        for type in [CONF_FILE, CONF_HTTPS]:

            # process master data
            for key in self._data[type]:
                self._checkData(type, key, self._data[type][key])

            # process slave data, but could be completely empty
            if type in self._dataSlave:
                for key in self._dataSlave[type]:
                    self._checkData(type, key, self._dataSlave[type][key])

        # sort on expdays
        self._msg = sorted(self._msg, key=lambda i: i[ATTR_EXPDAYS])

        # Processed all data, lets dump it for debugging
        LOGGER.debug("All Msg Dump: %s", self._msg)

    #############################################################
    def checkEmail(self):
        """Send email."""

        # https://stackabuse.com/how-to-send-emails-with-gmail-using-python/

        # In slave mode, we should not do anything
        if self._mode == ATTR_SLAVE:
            return

        msgarr = []

        # Build up text for the email
        for entry in self._msg:
            if not entry[ATTR_MSG] in msgarr:
                msgarr.append(entry[ATTR_MSG])

        # Check if we should execute today or not
        today = datetime.datetime.today().isoweekday()
        if today not in self._config[CONF_CONFIG][CONF_EMAIL][CONF_WEEKDAY]:
            LOGGER.debug("Email should not run today")
            return

        # Needs to be enabled
        if not self._config[CONF_CONFIG][CONF_EMAIL][CONF_ENABLED]:
            LOGGER.debug("Email is disabled (%d entries)", len(msgarr))
            return

        # If nothing is to report, do not continue
        if len(msgarr) == 0:
            return

        LOGGER.debug("Email %d entries", len(msgarr))

        msgtext = "\n".join(msgarr)

        # Insert template and replace vars
        msgtext = (
            self._config[CONF_CONFIG][CONF_EMAIL][CONF_TEMPLATE]
            .replace("%TEXT%", msgtext)
            .rstrip()
        )

        # Other replacements
        msgtext = msgtext.replace(
            "%DATE%", datetime.datetime.today().strftime("%Y-%m-%d")
        )

        LOGGER.debug("Email msgtext: %s", msgtext.replace("\n", "\\n"))

        try:
            server = smtplib.SMTP(
                self._config[CONF_CONFIG][CONF_EMAIL][CONF_HOST],
                self._config[CONF_CONFIG][CONF_EMAIL][CONF_PORT],
            )
            server.ehlo()

            if self._config[CONF_CONFIG][CONF_EMAIL][CONF_TLS]:
                server.starttls()

            if self._config[CONF_CONFIG][CONF_EMAIL][CONF_USER]:
                server.login(
                    self._config[CONF_CONFIG][CONF_EMAIL][CONF_USER],
                    self._config[CONF_CONFIG][CONF_EMAIL][CONF_PASSWORD],
                )

            server.sendmail(
                self._config[CONF_CONFIG][CONF_EMAIL][CONF_USER],
                self._config[CONF_CONFIG][CONF_EMAIL][CONF_EMAIL],
                msgtext,
            )
            server.close()

            LOGGER.debug(
                "Email: Send email to '%s'",
                self._config[CONF_CONFIG][CONF_EMAIL][CONF_EMAIL],
            )

        except Exception as e:
            errmsg = f"Failed to send email. Exception={type(e).__name__} Msg={e}"
            errmsg = f"Exception={type(e).__name__} Msg={e}"
            LOGGER.error(errmsg, exc_info=True)

    #############################################################
    def checkTelegram(self):

        # In slave mode, we should not do anything
        if self._mode == ATTR_SLAVE:
            return

        msgarr = []

        # Build up text for the notification
        for entry in self._msg:
            if entry[ATTR_TYPE] in [ATTR_NOTIFICATION]:
                if not entry[ATTR_MSG] in msgarr:
                    msgarr.append(entry[ATTR_MSG])

        # Needs to be enabled
        if not self._config[CONF_CONFIG][CONF_TELEGRAM][CONF_ENABLED]:
            LOGGER.debug("Telegram is disabled (%d entries)", len(msgarr))
            return

        # If nothing is to report, do not continue
        if len(msgarr) == 0:
            return

        LOGGER.debug("Telegram %d entries", len(msgarr))

        msgtext = "\n".join(msgarr)

        if self._config[CONF_CONFIG][CONF_TELEGRAM][CONF_TOKEN] == "":
            LOGGER.error("Telegram '%s' is not configured", CONF_TOKEN)
            return

        if self._config[CONF_CONFIG][CONF_TELEGRAM][CONF_CHAT_ID] == 0:
            LOGGER.error("Telegram '%s' is not configured", CONF_CHAT_ID)
            return

        # msgtext = f"Backup: {ERRORS[CONF_COUNT]} error(s), Msg1={ERRORS[CONF_MSG][0]}"
        bot = telegram.Bot(self._config[CONF_CONFIG][CONF_TELEGRAM][CONF_TOKEN])
        bot.send_message(
            chat_id=self._config[CONF_CONFIG][CONF_TELEGRAM][CONF_CHAT_ID],
            disable_notification=self._config[CONF_CONFIG][CONF_TELEGRAM][
                CONF_DISABLE_NOTIFICATION
            ],
            text=msgtext,
        )

    #############################################################
    def parseArgs(self):

        # Nothing supplied, also fine with me
        if len(sys.argv) == 1:
            return

        argCount = 1
        while argCount < len(sys.argv):

            # we can run in master or slave mode
            if sys.argv[argCount] == "-m":
                argCount += 1
                if argCount < len(sys.argv):
                    if sys.argv[argCount].lower() in [
                        ATTR_NONE,
                        ATTR_MASTER,
                        ATTR_SLAVE,
                    ]:
                        self._mode = sys.argv[argCount].lower()
                    else:
                        LOGGER.error(
                            "Invalid argument for '-m %s'", sys.argv[argCount].lower()
                        )
                        sys.exit(1)

            argCount += 1

        LOGGER.info("Running in mode '%s'", self._mode)

    #############################################################
    def remoteSCP(self):

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        # client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        host = self._config[CONF_CONFIG][CONF_TRANSFER][CONF_HOST]
        port = self._config[CONF_CONFIG][CONF_TRANSFER][CONF_PORT]
        username = self._config[CONF_CONFIG][CONF_TRANSFER][CONF_USER]
        password = self._config[CONF_CONFIG][CONF_TRANSFER][CONF_PASSWORD]
        file = self._config[CONF_CONFIG][CONF_TRANSFER][CONF_FILENAME]

        # set to none if nothing is supplied, library requires "None"
        if not password:
            password = None

        LOGGER.debug("Downloading '%s' from host '%s'", file, host)

        try:
            # normally connect will establish a new session. Need to redo it when a failure happens
            client.connect(
                host,
                port=port,
                username=username,
                password=password,
                auth_timeout=5,
                timeout=10,
            )

            scpclient = scp.SCPClient(client.get_transport())

            scpclient.get(file, file, preserve_times=True)

        except Exception as e:
            errmsg = f"SCP failed for '{file}', host '{host}'. Exception={type(e).__name__} Msg={e}"
            LOGGER.error(errmsg, exc_info=True)


#################################################################
# Main
#################################################################
def main():

    # Only root can access certain things, so we need this
    if not os.geteuid() == 0:
        sys.exit("ERROR: Only root can run this script\n")

    cert = certificateClass()

    cert.parseArgs()
    cert.checkFile()
    cert.checkHttps()
    cert.checkDoSlave()
    cert.checkData()
    cert.checkEmail()
    cert.checkTelegram()


#################################################################
if __name__ == "__main__":
    main()

# End
