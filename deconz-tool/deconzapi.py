"""Python wrapper for DeCONZ API, to easily rename devices."""

"""
The DeCONZ data structure is flawed, it stores everything under lights and sensors. 
Power sockets are partially in lights and sensors (confusing).
"""

import datetime
import json
import logging
import requests
import dateutil

from dateutil.parser import parse as dateparse

_LOGGER = logging.getLogger(__name__)

BASEURL = "http://{}:{}/api/{}"
DEFAULT_TIMEOUT = 5

DECONZ_LIGHTS = "lights"
DECONZ_SENSORS = "sensors"

DECONZ_CATEGORY = "category"

DECONZ_LIST_SWITCH = ["On/Off plug-in unit"]
DECONZ_LIST_COVER = ["Window covering device"]
DECONZ_LIST_LIGHT = ["Color light"]
DECONZ_LIST_OTHER = ["Configuration tool"]
DECONZ_TYPE_SWITCH = "switch"
DECONZ_TYPE_COVER = "cover"
DECONZ_TYPE_LIGHT = "light"
DECONZ_TYPE_SENSOR = "sensor"
DECONZ_TYPE_OTHER = "other"
DECONZ_TYPE_UNKNOWN = "unknown"
DECONZ_TYPE_USEABLE = [
    DECONZ_TYPE_SWITCH,
    DECONZ_TYPE_COVER,
    DECONZ_TYPE_LIGHT,
    DECONZ_TYPE_SENSOR,
]

DECONZ_ATTR_SEQID = "seqid"  # Not part of DeCONZ API, but used internally by me
DECONZ_ATTR_ID = "id"
DECONZ_ATTR_UNIQUEID = "uniqueid"
DECONZ_ATTR_MANUFACTURERNAME = "manufacturername"
DECONZ_ATTR_MODEL = "model"
DECONZ_ATTR_MODELID = "modelid"
DECONZ_ATTR_NAME = "name"
DECONZ_ATTR_STATE = "state"
DECONZ_ATTR_ON = "on"
DECONZ_ATTR_REACHABLE = "reachable"
DECONZ_ATTR_SWVERSION = "swversion"
DECONZ_ATTR_TYPE = "type"
DECONZ_ATTR_CONFIG = "config"
DECONZ_ATTR_VALUES = "values"
DECONZ_ATTR_VALUESRAW = "valuesraw"
DECONZ_ATTR_LASTSEEN = "lastseen"
DECONZ_ATTR_LASTUPDATED = "lastupdated"
DECONZ_ATTR_BATTERY = "battery"
DECONZ_ATTR_ADDRESS = "address"

# DeCONZ sensor types
DECONZ_SENSOR_DAYLIGHT = "Daylight"
DECONZ_SENSOR_TYPES = [
    "Daylight",
    "ZHABattery",
    "ZHAConsumption",
    "ZHAHumidity",
    "ZHALightLevel",
    "ZHAOpenClose",
    "ZHAPower",
    "ZHAPresence",
    "ZHAPressure",
    "ZHASwitch",
    "ZHATemperature",
]

# DeCONZ sensor unit values
# lightlevel (lux) = round(10 ** (float(self.lightlevel - 1) / 10000), 1)
DECONZ_SENSOR_UNITS = {
    "battery": ["%", None],
    "buttonevent": ["", None],
    "consumption": ["kWh", 1000],
    "current": ["A", 1000],
    "dark": ["", None],
    "daylight": ["", None],
    "eventduration": ["", None],
    "humidity": ["%", 100],
    "lightlevel": ["lx", None],
    "lux": ["", None],
    "open": ["", None, "Close", "Open"],
    "power": ["W", None],
    "presence": ["", None, "Off", "On"],
    "pressure": ["hPa", None],
    "status": ["", None],
    "sunrise": ["", None],
    "sunset": ["", None],
    "temperature": ["C", 100],
    "voltage": ["V", None],
}

# DeCONZ configurable items
DECONZ_CONFIG_DELAY = "delay"
# causes the sensor's led to blink when motion is detected
DECONZ_CONFIG_LEDINDICATION = "ledindication"
DECONZ_CONFIG_SENSITIVITY = "sensitivity"
DECONZ_CONFIG_SENSITIVITYMAX = "sensitivitymax"
# Makes the sensor more "agressive" - it won't go asleep while usertest is on
DECONZ_CONFIG_USERTEST = "usertest"
DECONZ_CONFIG_TYPES = [
    DECONZ_CONFIG_DELAY,
    DECONZ_CONFIG_LEDINDICATION,
    DECONZ_CONFIG_SENSITIVITY,
    DECONZ_CONFIG_SENSITIVITYMAX,
    DECONZ_CONFIG_USERTEST,
]

# Fix manufacturer names
DECONZ_FIX_MANUFACTURER = {
    "IKEA of Sweden": "IKEA",
    "dresden elektronik": "Dresden",
    "innr": "Innr",
    "LUMI": "Xiaomi",
    # "LUMI": "Xiaomi/Aqara",
}

DECONZ_FIX_MODELID = {
    "lumi.sensor_magnet.aq2": "Door Window",
    "lumi.sensor_ht": "Temperature/Humidity (Round)",
    "lumi.weather": "Temperature/Humidity (Square)",
    "lumi.sen_ill.mgl01": "Light Sensor",
}

HTTP_GET = "GET"
HTTP_POST = "POST"
HTTP_PUT = "PUT"


class DeCONZAPI:
    """API Wrapper for the DeCONZ API."""

    def __init__(self, host, port, apikey, timeout=DEFAULT_TIMEOUT):
        """Create the object with required parameters."""
        self._host = host
        self._port = port
        self._apikey = apikey
        self._timeout = timeout
        self._url = BASEURL.format(self._host, self._port, self._apikey)
        self._requestcount = 0
        self._seqid = 0

    def _request(self, reqtype, urlsuffix=None, data=None):
        """HTTP request handler."""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        if urlsuffix is None:
            url = self._url
        else:
            url = "{}/{}".format(self._url, urlsuffix)

        self._requestcount += 1
        if self._requestcount > 9999:
            self._requestcount = 1

        _LOGGER.debug(
            "REQ-C%d: API=%s, type=%s, data=%s",
            self._requestcount,
            url,
            reqtype,
            json.dumps(data),
        )

        # Convert to JSON if data is supplied
        if data is not None:
            data = json.dumps(data)

        resp = requests.request(
            reqtype, url, headers=headers, data=data, timeout=self._timeout
        )

        if resp.status_code in [200]:
            _LOGGER.debug(
                "RES-C%d: API=%s, type=%s, HTTPCode=%s, Data=%s",
                self._requestcount,
                url,
                reqtype,
                resp.status_code,
                resp.text,
            )

            try:
                jsondata = json.loads(resp.text)
            except json.decoder.JSONDecodeError:
                _LOGGER.error(
                    "RES-C%d: API=%s, type=%s, INVALID JSON=%s",
                    self._requestcount,
                    url,
                    reqtype,
                    resp.text,
                )
                jsondata = None

            return jsondata
        elif resp.status_code in [403]:
            _LOGGER.error(
                "RES-C%d: API=%s, type=%s, HTTPCode=%s (Authentication Failed), Data=%s",
                self._requestcount,
                url,
                reqtype,
                resp.status_code,
                resp.text,
            )
            raise Exception("DeCONZ: Invalid DeCONZ API key")

        else:
            _LOGGER.error(
                "RES-C%d: API=%s, type=%s, HTTPCode=%s, Data=%s",
                self._requestcount,
                url,
                reqtype,
                resp.status_code,
                resp.text,
            )

            raise Exception("DeCONZ: Unknown Error (%d)", resp.status_code)

    #############################################################
    def get_all_raw(self):
        """Retrieve all information from the DeCONZ API."""

        result = self._request(HTTP_GET, "")
        if result is None:
            _LOGGER.error("DeCONZ: %s all did not return data", HTTP_GET)

        return result

    #############################################################
    def get_light_raw(self, id=None):
        """Retrieve light(s) from the DeCONZ API."""

        if id is None:
            result = self._request(HTTP_GET, DECONZ_LIGHTS)
        else:
            result = self._request(HTTP_GET, "{}/{}".format(DECONZ_LIGHTS, id))

        if result is None:
            _LOGGER.error("DeCONZ: %s %s did not return data", HTTP_GET, DECONZ_LIGHTS)

        return result

    #############################################################
    def get_sensor_raw(self, id=None):
        """Retrieve the Sensor info."""

        if id is None:
            result = self._request(HTTP_GET, DECONZ_SENSORS)
        else:
            result = self._request(HTTP_GET, "{}/{}".format(DECONZ_SENSORS, id))

        if result is None:
            _LOGGER.error("DeCONZ: %s %s did not return data", HTTP_GET, DECONZ_SENSORS)

        return result

    #############################################################
    def modify_light(self, id, suffix, type, name):
        """Change the Light name."""

        result = self._request(
            HTTP_PUT, "{}/{}{}".format(DECONZ_LIGHTS, id, suffix), {type: name}
        )
        return result

    #############################################################
    def modify_sensor(self, id, suffix, type, name):
        """Change the Sensor name."""

        result = self._request(
            HTTP_PUT, "{}/{}{}".format(DECONZ_SENSORS, id, suffix), {type: name}
        )
        return result

    #############################################################
    def modify_light_name(self, id, name):
        """Helper for rename light name."""

        result = self.modify_light(id, "", "name", name)
        return result

    #############################################################
    def modify_sensor_name(self, id, name):
        """Helper for rename sensor name."""

        result = self.modify_sensor(id, "", "name", name)
        return result

    #############################################################
    def modify_light_config(self, id, name, value):
        """Helper for modify light config."""

        result = self.modify_light(id, "/config", name, value)
        return result

    #############################################################
    def modify_sensor_config(self, id, name, value):
        """Helper for modify sensor config."""

        result = self.modify_sensor(id, "/config", name, value)
        return result

    #############################################################
    def get_all_devices(self):
        """Retrieve all information from the DeCONZ API and map to our internal format."""

        deconzdata = self.get_all_raw()

        if deconzdata is None:
            return None

        """
        Lights NEVER have a "lastupdated" attribute, where sensors always seem to have them. Lights use "lastseen"
        """

        outpdata = []
        self._seqid = 0

        # We should have always this light entry
        if DECONZ_LIGHTS in deconzdata:
            for id, entry in deconzdata[DECONZ_LIGHTS].items():

                ientry = {}

                # the uniqueid should/has to be 26 length
                if len(entry[DECONZ_ATTR_UNIQUEID]) != 26:
                    _LOGGER.error(
                        "%s entry has a wrong %s '%s'",
                        DECONZ_LIGHTS,
                        DECONZ_ATTR_UNIQUEID,
                        entry[DECONZ_ATTR_UNIQUEID],
                    )

                # Map type
                if entry[DECONZ_ATTR_TYPE] in DECONZ_LIST_SWITCH:
                    ientry[DECONZ_ATTR_TYPE] = DECONZ_TYPE_SWITCH
                elif entry[DECONZ_ATTR_TYPE] in DECONZ_LIST_LIGHT:
                    ientry[DECONZ_ATTR_TYPE] = DECONZ_TYPE_LIGHT
                elif entry[DECONZ_ATTR_TYPE] in DECONZ_LIST_COVER:
                    ientry[DECONZ_ATTR_TYPE] = DECONZ_TYPE_COVER
                elif entry[DECONZ_ATTR_TYPE] in DECONZ_LIST_OTHER:
                    ientry[DECONZ_ATTR_TYPE] = DECONZ_TYPE_OTHER
                else:
                    ientry[DECONZ_ATTR_TYPE] = DECONZ_TYPE_UNKNOWN

                self._seqid += 1
                ientry[DECONZ_ATTR_SEQID] = self._seqid
                ientry[DECONZ_CATEGORY] = DECONZ_LIGHTS
                ientry[DECONZ_ATTR_ID] = id
                ientry[DECONZ_ATTR_UNIQUEID] = entry[DECONZ_ATTR_UNIQUEID]
                ientry[DECONZ_ATTR_ADDRESS] = ["L{}".format(id)]
                ientry[DECONZ_ATTR_NAME] = entry[DECONZ_ATTR_NAME]
                ientry[DECONZ_ATTR_LASTUPDATED] = None
                ientry[DECONZ_ATTR_BATTERY] = None

                # Put lastseen into lastupdated
                if DECONZ_ATTR_LASTSEEN in entry:
                    # Fix inconsistencies in timestamp information. Latest API seem to report with and without milliseconds
                    entry[DECONZ_ATTR_LASTSEEN] = entry[DECONZ_ATTR_LASTSEEN].replace(
                        "Z", ".000"
                    )

                    # We put lastupdated in our main entry
                    if ientry[DECONZ_ATTR_LASTUPDATED] is None:
                        ientry[DECONZ_ATTR_LASTUPDATED] = entry[DECONZ_ATTR_LASTSEEN]
                    elif entry[DECONZ_ATTR_LASTSEEN] > ientry[DECONZ_ATTR_LASTUPDATED]:
                        ientry[DECONZ_ATTR_LASTUPDATED] = entry[DECONZ_ATTR_LASTSEEN]

                ientry[DECONZ_ATTR_MODEL] = "{} {}".format(
                    DECONZ_FIX_MANUFACTURER.get(
                        entry[DECONZ_ATTR_MANUFACTURERNAME],
                        entry[DECONZ_ATTR_MANUFACTURERNAME],
                    ),
                    DECONZ_FIX_MODELID.get(
                        entry[DECONZ_ATTR_MODELID], entry[DECONZ_ATTR_MODELID]
                    ),
                )

                if DECONZ_ATTR_SWVERSION in entry:
                    ientry[DECONZ_ATTR_SWVERSION] = entry[DECONZ_ATTR_SWVERSION]
                else:
                    if DECONZ_ATTR_SWVERSION not in ientry:
                        ientry[DECONZ_ATTR_SWVERSION] = "Unknown"

                ientry[DECONZ_ATTR_REACHABLE] = entry[DECONZ_ATTR_STATE][
                    DECONZ_ATTR_REACHABLE
                ]
                ientry[DECONZ_ATTR_ON] = entry[DECONZ_ATTR_STATE].get(
                    DECONZ_ATTR_ON, None
                )

                # Add empty variable for possible sensors
                ientry[DECONZ_SENSORS] = []

                # Add entry to the output
                outpdata.append(ientry)
        else:
            _LOGGER.error("DeCONZ: data missing key '%s'?", DECONZ_LIGHTS)

        # We should have always this sensors entry
        if DECONZ_SENSORS in deconzdata:
            for id, entry in deconzdata[DECONZ_SENSORS].items():

                ientry = None

                # Lets try to find the main entry for this specific sensor, we will put it as a child
                for x in outpdata:
                    if entry[DECONZ_ATTR_UNIQUEID].find(x[DECONZ_ATTR_UNIQUEID]) == 0:
                        ientry = x
                        break

                # Entry doesn't exist yet, so we create the main information for this sensor first
                if ientry is None:
                    ientry = {}

                    self._seqid += 1
                    ientry[DECONZ_ATTR_SEQID] = self._seqid
                    ientry[DECONZ_ATTR_TYPE] = DECONZ_TYPE_SENSOR
                    ientry[DECONZ_CATEGORY] = DECONZ_SENSORS
                    ientry[DECONZ_ATTR_UNIQUEID] = entry[DECONZ_ATTR_UNIQUEID][0:26]
                    ientry[DECONZ_ATTR_ADDRESS] = ["S{}".format(id)]
                    ientry[DECONZ_ATTR_NAME] = entry[DECONZ_ATTR_NAME]
                    ientry[DECONZ_ATTR_LASTUPDATED] = None
                    ientry[DECONZ_ATTR_BATTERY] = None

                    ientry[DECONZ_ATTR_MODEL] = "{} {}".format(
                        DECONZ_FIX_MANUFACTURER.get(
                            entry[DECONZ_ATTR_MANUFACTURERNAME],
                            entry[DECONZ_ATTR_MANUFACTURERNAME],
                        ),
                        DECONZ_FIX_MODELID.get(
                            entry[DECONZ_ATTR_MODELID], entry[DECONZ_ATTR_MODELID]
                        ),
                    )

                    if DECONZ_ATTR_SWVERSION in entry:
                        ientry[DECONZ_ATTR_SWVERSION] = entry[DECONZ_ATTR_SWVERSION]
                    else:
                        if DECONZ_ATTR_SWVERSION not in ientry:
                            ientry[DECONZ_ATTR_SWVERSION] = "Unknown"

                    ientry[DECONZ_ATTR_REACHABLE] = entry[DECONZ_ATTR_CONFIG].get(
                        DECONZ_ATTR_REACHABLE, None
                    )
                    ientry[DECONZ_SENSORS] = []

                    outpdata.append(ientry)
                else:
                    ientry[DECONZ_ATTR_ADDRESS].append("S{}".format(id))

                # Now gather sensor information and append it

                # type ZHA type need to exist in our list
                if entry[DECONZ_ATTR_TYPE] not in DECONZ_SENSOR_TYPES:
                    _LOGGER.error(
                        "Invalid sensor type '%s' in entry=%s",
                        entry[DECONZ_ATTR_TYPE],
                        entry,
                    )
                    continue

                # the uniqueid should/has to be 26 or 31 length
                if len(entry[DECONZ_ATTR_UNIQUEID]) not in [26, 31]:
                    _LOGGER.error(
                        "%s entry has a wrong %s '%s'",
                        DECONZ_SENSORS,
                        DECONZ_ATTR_UNIQUEID,
                        entry[DECONZ_ATTR_UNIQUEID],
                    )
                    continue

                sentry = {}
                sentry[DECONZ_ATTR_TYPE] = entry[DECONZ_ATTR_TYPE]
                sentry[DECONZ_CATEGORY] = DECONZ_SENSORS
                sentry[DECONZ_ATTR_ID] = id
                sentry[DECONZ_ATTR_NAME] = entry[DECONZ_ATTR_NAME]
                sentry[DECONZ_ATTR_UNIQUEID] = entry[DECONZ_ATTR_UNIQUEID]
                sentry[DECONZ_ATTR_CONFIG] = {}
                sentry[DECONZ_ATTR_VALUES] = {}
                sentry[DECONZ_ATTR_VALUESRAW] = {}

                # Find the main sensor entry, that one will exclude
                # config items in the sub sensor(s)
                if len(ientry[DECONZ_SENSORS]) > 0:
                    pentry = ientry[DECONZ_SENSORS][0]
                else:
                    # add a dummy config entry, for our main entry
                    pentry = {DECONZ_ATTR_CONFIG: {}}

                # Copy "config" information into "config"
                for name, value in entry[DECONZ_ATTR_CONFIG].items():

                    if (
                        name == DECONZ_ATTR_BATTERY
                        and name not in pentry[DECONZ_ATTR_CONFIG]
                    ):
                        if (ientry[DECONZ_ATTR_BATTERY] is not None) and (
                            ientry[DECONZ_ATTR_BATTERY] != value
                        ):
                            _LOGGER.error(
                                "%s entryid %s %s does not match parent",
                                DECONZ_SENSORS,
                                id,
                                DECONZ_ATTR_BATTERY,
                            )
                        ientry[DECONZ_ATTR_BATTERY] = value

                    if (
                        name in DECONZ_CONFIG_TYPES
                        and name not in pentry[DECONZ_ATTR_CONFIG]
                    ):
                        sentry[DECONZ_ATTR_CONFIG][name] = value

                # Copy lastseen if available
                if DECONZ_ATTR_LASTSEEN in entry:
                    # Fix inconsistencies in timestamp information. Latest API seem to report with and without milliseconds
                    if entry[DECONZ_ATTR_LASTSEEN] is None:
                        entry[DECONZ_ATTR_LASTSEEN] = ""
                    else:
                        entry[DECONZ_ATTR_LASTSEEN] = entry[DECONZ_ATTR_LASTSEEN].replace( "Z", ".000")

                    # We put lastupdated in our main entry
                    if ientry[DECONZ_ATTR_LASTUPDATED] is None:
                        ientry[DECONZ_ATTR_LASTUPDATED] = entry[DECONZ_ATTR_LASTSEEN]
                    elif entry[DECONZ_ATTR_LASTSEEN] > ientry[DECONZ_ATTR_LASTUPDATED]:
                        ientry[DECONZ_ATTR_LASTUPDATED] = entry[DECONZ_ATTR_LASTSEEN]

                # Copy "state" information into "values", ignore lastupdated
                for name, value in entry[DECONZ_ATTR_STATE].items():

                    # We put lastupdated in our main entry
                    if name == DECONZ_ATTR_LASTUPDATED:
                        # 2020-04-19T17:09:33
                        # lu = datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S').isoformat()

                        if ientry[DECONZ_ATTR_LASTUPDATED] is None:
                            ientry[DECONZ_ATTR_LASTUPDATED] = value
                        elif value > ientry[DECONZ_ATTR_LASTUPDATED]:
                            ientry[DECONZ_ATTR_LASTUPDATED] = value
                        continue

                    # Convert possible value units in readable format
                    if name in DECONZ_SENSOR_UNITS:

                        # Only add it, if we known it - preventing weird values
                        if (
                            DECONZ_SENSOR_UNITS[name][0] != ""
                            or DECONZ_SENSOR_UNITS[name][1] is not None
                            or len(DECONZ_SENSOR_UNITS[name]) != 2
                        ):
                            # Special case for lightlevel to lux
                            if name == "lightlevel":
                                cvalue = round(10 ** (float(value - 1) / 10000), 1)
                            else:
                                cvalue = value

                            if DECONZ_SENSOR_UNITS[name][1] is not None:
                                try:
                                    cvalue = value / DECONZ_SENSOR_UNITS[name][1]
                                except Exception as e:
                                    print(
                                        "ERROR: {} - {}. Exception={} Msg={}".format(
                                            str(entry), name, type(e).__name__, str(e)
                                        )
                                    )

                            sentry[DECONZ_ATTR_VALUES][name] = (
                                str(cvalue) + DECONZ_SENSOR_UNITS[name][0]
                            )

                            # Exception for values which are true/false
                            if len(DECONZ_SENSOR_UNITS[name]) == 4:
                                sentry[DECONZ_ATTR_VALUES][name] = (
                                    DECONZ_SENSOR_UNITS[name][3]
                                    if value
                                    else DECONZ_SENSOR_UNITS[name][2]
                                )
                    else:
                        _LOGGER.warning("Unit '%s' is missing in sensor unit list", name)
                        # sentry[DECONZ_ATTR_VALUES][name] = str(value)

                    # Put the value also as raw, as is retrieved from API
                    sentry[DECONZ_ATTR_VALUESRAW][name] = value

                # Reachable should always be the same as the parent. Does not work
                # with daylight sensor
                if (
                    entry[DECONZ_ATTR_CONFIG].get(DECONZ_ATTR_REACHABLE, None)
                    != ientry[DECONZ_ATTR_REACHABLE]
                ) and entry[DECONZ_ATTR_TYPE] != DECONZ_SENSOR_DAYLIGHT:
                    _LOGGER.error(
                        "%s entryid %s %s does not match parent",
                        DECONZ_SENSORS,
                        id,
                        DECONZ_ATTR_REACHABLE,
                    )

                ientry[DECONZ_SENSORS].append(sentry)

        else:
            _LOGGER.error("DeCONZ: data missing key '%s'?", DECONZ_SENSORS)

        return outpdata


# End
