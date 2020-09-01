#!/usr/bin/env python3

import getopt
import json
import logging
import os
import sys
import voluptuous as vol
import yaml

# from deconzapi import DeCONZAPI, DECONZ_TYPE_USEABLE, DECONZ_ATTR_TYPE
from deconzapi import *

#################################################################
# Manually get API information:
# curl -s http://HOST:PORT/api/APIKEY | jq .

#################################################################

CONFIGNAME = "deconz.yaml"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_APIKEY = "apikey"

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=3080): int,
        vol.Required(CONF_APIKEY): str,
    },
    extra=vol.ALLOW_EXTRA,
)

#################################################################
ARG_OPERATION = "operation"
ARG_OPTION1 = "option1"

OPERATION_CONFIG = "config"
OPERATION_DELETE = "delete"
OPERATION_LIST = "list"
OPERATION_OUTPUT = "output"
OPERATION_RENAME = "rename"

OPERATIONS = [OPERATION_CONFIG, OPERATION_LIST, OPERATION_OUTPUT, OPERATION_RENAME]

OPERATION_OUTPUT_TYPE = ["raw", "json"]
OPERATION_RENAME_TYPE = ["raw"]

HELP = """
Commands:
  list           - list all devices
  rename         - rename device
  config         - configure device
  output raw     - print devices in python format
  output json    - print devices in pretty JSON format
"""

#################################################################
logging.basicConfig(
    level=logging.ERROR, format="%(asctime)s %(levelname)s: %(message)s"
)
LOGGER = logging.getLogger(__name__)
# LOGGER.propagate = False

#################################################################
def parseArg(args):

    if len(sys.argv) == 1:
        print("INFO: No parameter supplied")
        print(HELP)
        sys.exit(1)

    # Get operation
    args[ARG_OPERATION] = sys.argv[1].lower()

    if args[ARG_OPERATION] not in OPERATIONS:
        print("ERROR: Invalid operation")
        print(HELP)
        sys.exit(1)

    if args[ARG_OPERATION] == OPERATION_OUTPUT:
        if len(sys.argv) < 3:
            print("ERROR: Not enough parameter")
            print(HELP)
            sys.exit(1)

        args[ARG_OPTION1] = sys.argv[2].lower()
        if args[ARG_OPTION1] not in OPERATION_OUTPUT_TYPE:
            print("ERROR: Invalid output option")
            print(HELP)
            sys.exit(1)

    if args[ARG_OPERATION] == OPERATION_RENAME:
        if len(sys.argv) >= 3:
            args[ARG_OPTION1] = sys.argv[2].lower()
            if args[ARG_OPTION1] not in OPERATION_OUTPUT_TYPE:
                print("ERROR: Invalid output option")
                print(HELP)
                sys.exit(1)
        else:
            args[ARG_OPTION1] = ""


#################################################################
def readConfig():

    config = None

    location = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))
    name = f"{location}/{CONFIGNAME}"

    try:
        with open(name, "r") as f:
            config = yaml.safe_load(f)
            config = CONFIG_SCHEMA(config)
            return config
    except Exception as e:
        LOGGER.error(
            "Exception=%s Msg=%s", type(e).__name__, str(e), exc_info=True,
        )

    return None


#################################################################
def commandList(devices):

    """
    model
    reachable
    lastupdated
    battery
    value(s)
    """

    hdr = f'{"Type":7} {"Model":40} {"Name":30} {"Address":20} {"Reach":5} {"Last Updated (UTC)":19} {"Values":20}'
    print(hdr)
    print("".rjust(len(hdr), "-"))

    for type in DECONZ_TYPE_USEABLE:
        for dev in devices:
            if dev[DECONZ_ATTR_TYPE] == type:
                # Concat values
                values = []
                if DECONZ_ATTR_ON in dev:
                    values.append("On" if dev[DECONZ_ATTR_ON] == True else "Off")
                for sensor in dev[DECONZ_SENSORS]:
                    for key, value in sensor[DECONZ_ATTR_VALUES].items():
                        values.append(value)

                print(
                    f'{type:7} {dev[DECONZ_ATTR_MODEL][:40]:40} {dev[DECONZ_ATTR_NAME][:30]:30} {", ".join(dev[DECONZ_ATTR_ADDRESS]):20} {str(dev[DECONZ_ATTR_REACHABLE])[:5]:5} {str(dev[DECONZ_ATTR_LASTUPDATED])[:19]:19} {", ".join(values)}'
                )


#################################################################
def commandOutput(type, devices):

    # 0=raw, 1=json
    if type == OPERATION_OUTPUT_TYPE[0]:
        # print raw python object, it isn't json format
        print(devices)
    elif type == OPERATION_OUTPUT_TYPE[1]:
        # print pretty json format
        print(json.dumps(devices, indent=4, sort_keys=True))


#################################################################
def commandRename(api, devices):
    """Rename devices, there is logic between switches and sub sensors."""

    output = []

    hdr = f'{"Nr":2}. {"Type":7} {"Model":40} {"Name":30}'
    output.append(hdr)
    output.append("".rjust(len(hdr), "-"))

    seqid = ["q"]

    for dev in devices:
        output.append(
            f"{dev[DECONZ_ATTR_SEQID]:>2}. {dev[DECONZ_ATTR_TYPE]:7} {dev[DECONZ_ATTR_MODEL][:40]:40} {dev[DECONZ_ATTR_NAME][:30]:30}"
        )
        seqid.append(str(dev[DECONZ_ATTR_SEQID]))

    while True:
        print("\n".join(output))
        r = input("Enter number or q: ")
        r = r.rstrip()

        # Check if we entered something valid
        if r in seqid:
            break
        print(f"\nERROR: Invalid input '{r}' given!\n")

    # if we got quit, terminate
    if r == "q":
        print("\nINFO: Quit\n")
        sys.exit(1)

    # Convert input to integer, should always work
    seqid = int(r)

    # Lets find our specific entry
    for dev in devices:
        if dev[DECONZ_ATTR_SEQID] == seqid:
            break

    # depending on the type, we need to do something
    # switch=light + all sensors with suffix
    # sensor=all senors (same name)

    print("\nCurrent name(s):")

    if dev[DECONZ_CATEGORY] == DECONZ_LIGHTS:
        print("L" + dev[DECONZ_ATTR_ID], " ", dev[DECONZ_ATTR_NAME])

    # Go through sensors
    for sensor in dev[DECONZ_SENSORS]:
        print("S" + sensor[DECONZ_ATTR_ID], " ", sensor[DECONZ_ATTR_NAME])

    newname = input("Enter new name: ")
    if newname == "":
        print("\nINFO: Quit\n")
        sys.exit(1)

    # Ok, we got something, print and ask for permission
    print("\nNew name(s):")

    if dev[DECONZ_CATEGORY] == DECONZ_LIGHTS:
        print("L" + dev[DECONZ_ATTR_ID], " ", newname)

    # Go through sensors
    for sensor in dev[DECONZ_SENSORS]:
        type = ""
        if dev[DECONZ_ATTR_TYPE] == DECONZ_TYPE_SWITCH:
            type = sensor[DECONZ_ATTR_TYPE].replace("ZHA", " ")
            if type == " Consumption":
                type = " Energy"

        print("S" + sensor[DECONZ_ATTR_ID], " ", newname + type)

    while True:
        r = input("Change? [Y/n]: ")

        if r in ["Y", "y", ""]:
            break
        elif r in ["N", "n"]:
            print("\nINFO: Quit\n")
            sys.exit(1)

    if dev[DECONZ_CATEGORY] == DECONZ_LIGHTS:
        r = api.modify_light_name(dev[DECONZ_ATTR_ID], newname)
        print("Renamed Switch L" + dev[DECONZ_ATTR_ID], "=", r)

    # Go through sensors
    for sensor in dev[DECONZ_SENSORS]:
        type = ""
        if dev[DECONZ_ATTR_TYPE] == DECONZ_TYPE_SWITCH:
            type = sensor[DECONZ_ATTR_TYPE].replace("ZHA", " ")
            if type == " Consumption":
                type = " Energy"

        r = api.modify_sensor_name(sensor[DECONZ_ATTR_ID], newname + type)
        print("Renamed Switch S" + sensor[DECONZ_ATTR_ID], "=", r)

    # print(json.dumps(dev, indent=4, sort_keys=True))

    """
    ZHAConsumption -> Energy
    ZHAPower -> Power

    first gather list of devices to show
    show a list of devices, then do input() to pick one?
    if switch == rename also sub sensors + type
    if sensor == rename all sensors (same name)
    if other == don't know yet? 
    """


#################################################################
def commandConfig(api, devices):
    """Configure options of devices, normally sensors like Philips Motion."""

    # We create a new list of devices, because we are only interested
    # in devices with a config
    newdevices = []
    seqid = 0

    # Make a new list of sensors with configuration options
    for dev in devices:
        for sensor in dev[DECONZ_SENSORS]:
            if len(sensor[DECONZ_ATTR_CONFIG]) > 0:
                # add new seqid to our sensor
                seqid += 1
                sensor[DECONZ_ATTR_SEQID] = seqid
                # also add type/model, it overrules some other data!
                # Should maybe make this 'better'?
                sensor[DECONZ_ATTR_TYPE] = dev[DECONZ_ATTR_TYPE]
                sensor[DECONZ_ATTR_MODEL] = dev[DECONZ_ATTR_MODEL]

                newdevices.append(sensor)

    output = []

    hdr = f'{"Nr":2}. {"Type":7} {"Model":40} {"Name":30} {"Config":50}'
    output.append(hdr)
    output.append("".rjust(len(hdr), "-"))

    seqid = ["q"]

    # Check sensors for configuration options
    for dev in newdevices:
        clist = []
        # list config values
        for config in dev[DECONZ_ATTR_CONFIG]:
            # do not report sensitivitymax, because that is part of sensitivity
            if config not in [DECONZ_CONFIG_SENSITIVITYMAX]:
                clist.append(config)
        # print(dev)
        output.append(
            f'{dev[DECONZ_ATTR_SEQID]:>2}. {dev[DECONZ_ATTR_TYPE]:7} {dev[DECONZ_ATTR_MODEL][:40]:40} {dev[DECONZ_ATTR_NAME][:30]:30} {", ".join(clist)}'
        )
        seqid.append(str(dev[DECONZ_ATTR_SEQID]))

    while True:
        print("\n".join(output))
        r = input("Enter number or q: ")
        r = r.rstrip()

        # Check if we entered something valid
        if r in seqid:
            break
        print(f"\nERROR: Invalid input '{r}' given!\n")

    # if we got quit, terminate
    if r == "q":
        print("\nINFO: Quit\n")
        sys.exit(1)

    # Lets find our choice from the list
    for dev in newdevices:
        if str(dev[DECONZ_ATTR_SEQID]) == r:
            break

    # dev is the one we work with
    configlist = []
    id = 0
    seqid = ["q"]

    output = []

    hdr = f'{"Nr":2}. {"Name":20} {"Value":20}'
    output.append(hdr)
    output.append("".rjust(len(hdr), "-"))

    # sens max is a special variable
    sensitivitymax = ""

    for config in dev[DECONZ_ATTR_CONFIG]:

        if config in [DECONZ_CONFIG_SENSITIVITYMAX]:
            sensitivitymax = str(dev[DECONZ_ATTR_CONFIG][config])
        else:
            centry = {}
            id += 1
            centry[DECONZ_ATTR_SEQID] = id
            centry[DECONZ_ATTR_TYPE] = config
            centry[DECONZ_ATTR_VALUES] = dev[DECONZ_ATTR_CONFIG][config]
            configlist.append(centry)
            seqid.append(str(id))

            # Currently we support int and bool
            if type(centry[DECONZ_ATTR_VALUES]) not in [bool, int]:
                print(
                    "ERROR: unsupported type %s (%s) ".format(
                        type(centry[DECONZ_ATTR_VALUES]), centry
                    )
                )
                sys.exit(1)

    # Only here we can create the ouput, because of sensitivitymax
    for config in configlist:

        # Currently we support int and bool
        if type(centry[DECONZ_ATTR_VALUES]) is bool:
            val = f"{config[DECONZ_ATTR_VALUES]!s}"
        elif type(centry[DECONZ_ATTR_VALUES]) is int:
            val = str(config[DECONZ_ATTR_VALUES])
        else:
            val = ""

        if config[DECONZ_ATTR_TYPE] == DECONZ_CONFIG_SENSITIVITY:
            val += f" (max: {sensitivitymax})"

        output.append(
            f"{config[DECONZ_ATTR_SEQID]:>2}. {config[DECONZ_ATTR_TYPE]:20} {val:20}"
        )

    while True:
        print("\n".join(output))
        r = input("Enter number or q: ")
        r = r.rstrip()

        # Check if we entered something valid
        if r in seqid:
            break
        print(f"\nERROR: Invalid input '{r}' given!\n")

    # if we got quit, terminate
    if r == "q":
        print("\nINFO: Quit\n")
        sys.exit(1)

    # Find the to-be-modified entry
    seqid = int(r)

    for config in configlist:
        if config[DECONZ_ATTR_SEQID] == seqid:
            break

    # We need to modify the value. Only integer and boolean supported
    while True:
        r = input("Enter new value: ")
        r = r.rstrip()

        if isinstance(config[DECONZ_ATTR_VALUES], bool):
            if r.lower() in ["false", "0"]:
                value = False
                break
            elif r.lower() in ["true", "1"]:
                value = True
                break
        elif isinstance(config[DECONZ_ATTR_VALUES], int):
            value = int(r)
            break

    r = api.modify_sensor_config(dev[DECONZ_ATTR_ID], config[DECONZ_ATTR_TYPE], value)

    if r is not None:
        # Response is an array
        print("INFO: Config change - {}".format(r))
    else:
        print("ERROR: Response is empty?")


#################################################################
def Main():

    configInfo = readConfig()

    args = {}
    parseArg(args)

    LOGGER.debug("Args: %s", args)

    # Get DeCONZ API
    api = DeCONZAPI(
        configInfo[CONF_HOST], configInfo[CONF_PORT], configInfo[CONF_APIKEY]
    )

    # Get all devices, internally formatted
    devices = api.get_all_devices()

    if devices is None:
        print("ERROR: DeCONZ API returned None?")

    if args[ARG_OPERATION] == OPERATION_LIST:
        commandList(devices)

    if args[ARG_OPERATION] == OPERATION_OUTPUT:
        commandOutput(args[ARG_OPTION1], devices)

    if args[ARG_OPERATION] == OPERATION_RENAME:
        commandRename(api, devices)

    if args[ARG_OPERATION] == OPERATION_CONFIG:
        commandConfig(api, devices)

    """
    if ARGS["operation"] == "LIST":
        if "lights" in config:
            deconzlights = await Light_GetInfo(config["lights"], config["sensors"])
            await Light_Print(deconzlights)
        else:
            raise Exception("Can not find 'lights' in DeCONZ configuration")

    elif ARGS["operation"] == "MODIFY":

        if ARGS["field"] == "NAME":
            deconzlights = await Light_GetInfo(config["lights"], config["sensors"])
            await Light_Modify_Name(api, deconzlights, ARGS["id"], ARGS["value"])
        else:
            print("ERROR: Modify, unknown field")
            sys.exit(1)

    deconzapi.DECONZ_TYPE_USEABLE
    make modify user-input, it isn't something we use regularly?
    https://www.w3schools.com/python/ref_func_input.asp
    """


#################################################################
if __name__ == "__main__":
    Main()

# End
