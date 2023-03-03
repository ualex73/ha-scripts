"""
AppDaemon script to update our TransIP Dynamic DNS

curl ipinfo.io/178.85.12.100/geo

"""

#################################################################
# Python modules
#################################################################
import appdaemon.plugins.hass.hassapi as hass
import base64
import dns.resolver
import requests
import json
import uuid
import voluptuous as vol

from OpenSSL import crypto

#################################################################
# Constants and variables
#################################################################
LOGGER = None

#################################################################
# Configuration
#################################################################

BASEURL = "https://api.transip.nl/v6/{}"
EXTERNALIPA = "https://icanhazip.com/"
EXTERNALIPB = "https://api6.ipify.org/"

HTTP_GET = "GET"
HTTP_PATCH = "PATCH"
HTTP_POST = "POST"
HTTP_PUT = "PUT"

# log levels
CRITICAL = "CRITICAL"
DEBUG = "DEBUG"
ERROR = "ERROR"
INFO = "INFO"
WARNING = "WARNING"

CONF_CLASS = "class"
CONF_MODULE = "module"
CONF_LOGLEVEL = "loglevel"
CONF_INTERVAL = "interval"
CONF_USERNAME = "username"
CONF_DOMAIN = "domain"
CONF_PRIVKEY = "privkey"
CONF_EXTERNALIP = "externalip"
CONF_DNS = "dns"
CONF_DNSENTRY = "dnsentry"
CONF_NAME = "name"
CONF_TYPE = "type"

DNSENTRY_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default="@"): str,
        vol.Optional(CONF_TYPE, default="A"): str,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MODULE): str,
        vol.Required(CONF_CLASS): str,
        vol.Optional(CONF_LOGLEVEL, default=INFO): vol.Any(
            CRITICAL, DEBUG, ERROR, INFO, WARNING, vol.Upper
        ),
        vol.Optional(CONF_INTERVAL, default=300): int,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_DOMAIN): str,
        vol.Optional(CONF_PRIVKEY, default="/privkey.pem"): str,
        vol.Optional(CONF_EXTERNALIP, default=EXTERNALIPA): str,
        vol.Optional(CONF_DNSENTRY, default={}): DNSENTRY_SCHEMA,
        vol.Required(CONF_DNS, default="8.8.8.8"): str,
    },
    extra=vol.ALLOW_EXTRA,
)

#################################################################
# Main Class
#################################################################
class TransIP(hass.Hass):

    #############################################################
    def initialize(self):
        """Called on startup of this module"""

        self._requestcount = 0
        self._dnserror = 0
        self._externalerror = 0
        self._dnsip = None
        self._dnsipexpire = None
        self._externalip = None

        # Get our parameters/configuration. Need to use 'self._config', because 'self.config' is reserved for AppDaemon
        self._config = CONFIG_SCHEMA(self.args)

        # We define the LOGGER as flobal, because self.get_user_log is only available here
        global LOGGER
        logfile = "{}_log".format(self._config[CONF_MODULE])
        LOGGER = self.get_user_log(logfile)
        if LOGGER is None:
            self.log("No LOGGER '%s' found, default to main logfile", logfile)
            LOGGER = self.get_main_log()

        # set loglevel before we start logging anything
        self.set_log_level(self._config[CONF_LOGLEVEL])

        LOGGER.debug("Start: Initialize")

        LOGGER.debug("Config: %s", self._config)

        # load our private key
        self.loadPrivateKey()

        # Start loop in 1 second
        self.handle = self.run_in(self.run, 1)

        LOGGER.debug("End: Initialize")

    #############################################################
    def run(self, kwargs):

        """
        here we need to check if apiDnsGet works at startup
        this needs to be compared to our external ip at startup

        loop until we:
        check if our external ip has changed
        update dns entry, wait until change is propogated

        introduce a notify call?
        """

        try:
            self.getDnsIp()
        except Exception as ex:
            LOGGER.error("getDnsIp exception: %s", ex)

            # Set a scheduler callback for e.g. 300 seconds
            self.handle = self.run_in(self.run, self._config[CONF_INTERVAL])

            return

        # test test test

        # Check if we know our DNS entry already
        if self._dnsip is None:
            result = self.apiDnsGet()

            if not result:
                self._dnserror += 1

        # No reason to check externally if the TransIP doesn't work
        if not self._dnsip:
            LOGGER.error("TransIP DNS doesn't seem to work, stopping main loop")

            # Set a scheduler callback for e.g. 300 seconds
            self.handle = self.run_in(self.run, self._config[CONF_INTERVAL])
            return

        # Get our external IP address
        result = self.getExternalIP()
        if not result:
            self._externalerror += 1

        if not self._externalip:
            LOGGER.error("External IP doesn't seem to work, stopping main loop")

            # Set a scheduler callback for e.g. 300 seconds
            self.handle = self.run_in(self.run, self._config[CONF_INTERVAL])
            return

        # Ok, we got valid data, we can compare
        if self._dnsip != self._externalip:
            LOGGER.info(
                "TransIP DNS (%s) and external IP (%s) are different, updating DNS",
                self._dnsip,
                self._externalip,
            )

            # Make our changes via:
            result = self.apiDnsUpdate(self._externalip)
            LOGGER.info("Update Result=%s", result)

            # should we do a loop to doublecheck the change has been applied?
            # for now, lets empty the internal vars
            self._dnsip = None
            self._dnsipexpire = None
        else:
            LOGGER.debug(
                "TransIP DNS and external IP address are equal (%s)", self._dnsip
            )

        # Set a scheduler callback for e.g. 300 seconds
        self.handle = self.run_in(self.run, self._config[CONF_INTERVAL])

    #############################################################
    def loadPrivateKey(self):

        LOGGER.debug("Loading private key %s", self._config[CONF_PRIVKEY])

        key_file = open(self._config[CONF_PRIVKEY], "r")
        key = key_file.read()
        key_file.close()

        # with open("private.pem", "r") as f:
        #    key = f.read()
        #    f.close()

        if key.startswith("-----BEGIN "):
            self._pkey = crypto.load_privatekey(crypto.FILETYPE_PEM, key)
        else:
            self._pkey = crypto.load_pkcs12(key).get_privatekey()

        LOGGER.debug("Loaded private key successfully")

    #############################################################
    def getExternalIP(self):
        """Get our external IP address (IPv4) to compare against our DNS."""

        # Increment request counter for logging purpose
        self._requestcount += 1
        if self._requestcount > 99999:
            self._requestcount = 1

        try:
            LOGGER.debug(
                "REQ-C%d: Retrieving external IP from '%s'",
                self._requestcount,
                self._config[CONF_EXTERNALIP],
            )
            req = requests.request(HTTP_GET, self._config[CONF_EXTERNALIP], timeout=5)
        except Exception as e:
            LOGGER.error(
                "Failed to retrieve external IP address '{}'. {}: '{}'".format(
                    self._config[CONF_EXTERNALIP], type(e).__name__, str(e)
                )
            )
            self._externalip = None
            return False

        # copy our text and remove newlines
        text = req.text.rstrip()

        LOGGER.debug(
            "RES-C%d: Code=%d, data=%s", self._requestcount, req.status_code, text
        )

        # Check HTTP Code
        if req.status_code == 200:
            # All good, lets check IP address
            if self.isIPValid(text):
                LOGGER.debug("Successfully retrieved external IP %d", text)
                self._externalip = text
                return True
            else:
                LOGGER.error("Retrieved external IP looks invalid '%s'", text)
                self._externalip = None
                return False
        else:
            LOGGER.error(
                "Retrieval of external IP gave code=%d, %s", req.status_code, text
            )
            self._externalip = None
            return False

    #############################################################
    def getDnsIp(self):
        """Get our external IP address (IPv4) from e.g. google DNS."""

        resolver = dns.resolver.Resolver()
        resolver.nameservers = [self._config[CONF_DNS]]
        data = resolver.query(self._config[CONF_DOMAIN], "a")

        for entry in data:
            LOGGER.debug("DNS Return: %s", entry.to_text())

    #############################################################
    def _request(self, reqtype, urlsuffix, data=None, signature=None):
        """HTTPS request handler, it can be used to authenticate and other requests."""

        # Increment request counter for logging purpose
        self._requestcount += 1
        if self._requestcount > 99999:
            self._requestcount = 1

        # Set the proper HTTP headers
        if signature is not None:
            headers = {"Content-Type": "application/json", "Signature": signature}
        else:
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self._token,
            }

        # Build full URL for TransIP API
        url = BASEURL.format(urlsuffix)

        try:
            LOGGER.debug(
                "REQ-C%d: TransIP API (%s) '%s', data=%s",
                self._requestcount,
                reqtype,
                url,
                data,
            )
            req = requests.request(reqtype, url, headers=headers, data=data, timeout=5)
        except Exception as e:
            LOGGER.error(
                "Failed TransIP API '{}'. {}: '{}'".format(
                    url, type(e).__name__, str(e)
                )
            )
            return

        LOGGER.debug(
            "RES-C%d: Code=%d, data=%s", self._requestcount, req.status_code, req.text
        )

        # Check if we received a good response
        if req.status_code not in [200, 201, 204]:
            LOGGER.error("TransIP failed with code=%d, %s", req.status_code, req.text)
            return None

        # Note: a 204 doesn't contain data. Not sure it will be None or ""

        # Looks good, return data to caller for processing
        return req.text

    #############################################################
    def apiAuth(self):
        """Authenticate with TransIP and retrieve token."""

        LOGGER.debug("Going to authenticate with TransIP API")

        # Set token to blank, we will retrieve a new one
        self._token = None

        # Build up authentication. The nonce *always* needs to be unique, otherwise we get a 401
        auth = {
            "login": self._config[CONF_USERNAME],
            "nonce": uuid.uuid4().hex,
            "global_key": True,
        }

        # Convert it to a compressed json string. Also the exact same string is used for signing and POST data
        authstr = json.dumps(auth, separators=(",", ":"))

        sign = crypto.sign(self._pkey, authstr, "sha512")
        signbase64 = base64.b64encode(sign)

        signature = signbase64.decode()
        text = self._request(
            HTTP_POST, "auth", data=authstr, signature=signbase64.decode()
        )

        # Check if something went wrong or not
        if text is None:
            return False

        # Let's parse the JSON text
        try:
            data = json.loads(text)
        except Exception as e:
            LOGGER.error(
                "Faied to decode JSON '{}'. {}: '{}'".format(
                    text, type(e).__name__, str(e)
                )
            )
            return False

        # Last check if data is really valid
        if "token" not in data:
            LOGGER.error(
                "TransIP successfully authenticated, but no 'token' in the response '%s'",
                text,
            )
            return False

        LOGGER.debug("TransIP API authentication successful")

        # All good, lets store token
        self._token = data["token"]

        # Notify caller we retrieved a token successfully
        return True

    #############################################################
    def apiDnsGet(self):
        """Get the TransIP dns entry."""

        self._dnsip = None
        self._dnsipexpire = None

        # First authenticate
        if not self.apiAuth():
            return False

        text = self._request(
            HTTP_GET, "domains/{}/dns".format(self._config[CONF_DOMAIN])
        )

        # Don't do any processing if we hit an error
        if text is None:
            return False

        # Decode the json data
        try:
            data = json.loads(text)
        except Exception as e:
            LOGGER.error(
                "Faied to decode JSON '{}'. {}: '{}'".format(
                    text, type(e).__name__, str(e)
                )
            )
            return None

        if "dnsEntries" not in data:
            LOGGER.error("dnsGet is missing 'dnsEntries'. %s", text)
            return False

        # Now find our record
        for entry in data["dnsEntries"]:
            # LOGGER.error("--- %s", entry)
            if (
                self._config[CONF_DNSENTRY][CONF_NAME] == entry[CONF_NAME]
                and self._config[CONF_DNSENTRY][CONF_TYPE] == entry[CONF_TYPE]
            ):
                self._dnsip = entry["content"]
                self._dnsipexpire = entry["expire"]
                return True

        return False

    #############################################################
    def apiDnsUpdate(self, ip):
        """Update the specific DNS entry for our domain."""

        # First authenticate
        if not self.apiAuth():
            return False

        # do we need to add: "expire: 300?
        dns = {
            "dnsEntry": {
                CONF_NAME: self._config[CONF_DNSENTRY][CONF_NAME],
                CONF_TYPE: self._config[CONF_DNSENTRY][CONF_TYPE],
                "expire": self._dnsipexpire,
                "content": ip,
            }
        }
        dnsstr = json.dumps(dns, separators=(",", ":"))
        LOGGER.error("xxxx %s", dnsstr)

        text = self._request(
            HTTP_PATCH, "domains/{}/dns".format(self._config[CONF_DOMAIN]), data=dnsstr
        )

        if text is None:
            return False

        return True

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


"""
const type = {
        v4: {
                dnsServers: dnsServers.map(({v4: {servers, ...question}}) => ({
                        servers, question
                })),
                httpsUrls: [
                        'https://icanhazip.com/',
                        'https://api.ipify.org/'
                ]
        },
        v6: {
                dnsServers: dnsServers.map(({v6: {servers, ...question}}) => ({
                        servers, question
                })),
                httpsUrls: [
                        'https://icanhazip.com/',
                        'https://api6.ipify.org/'
                ]
        }
};
"""

#################################################################
# End
#################################################################
