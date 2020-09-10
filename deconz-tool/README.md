# Script for list, rename or config DeCONZ devices via API

This script can list all devices with its values, rename devices, configure device settings and dump API information in JSON format.

## Check-Health

### Requirements
- Pythone 3.6+
- Ubuntu 18.04+ (should work on other Linux flavors, but untested and unsupported)
- DeCONZ API 2.05.80

## Python modules (pip3)
- voluptuous 
- python_dateutil
- requests
- PyYAML

### Installation

- Clone this git repository
- Configure "deconz.yaml", setup the hostname, port and API key

### Usage

####  list devices
To run the script, execute it as follows:

```
./deconz.py list
```

The output should look like:
```
Type    Model                                    Name                           Address              Reach Last Updated (UTC)  Values
---------------------------------------------------------------------------------------------------------------------------------------------------
switch  Innr SP 120                              Living RingChime               L1, S2, S3           True  2020-09-01T08:45:51 On, 7.17kWh, 0.0A, 0W, 241V
cover   IKEA FYRTUR block-out roller blind       Kitchen Door Cover             L9, S27              True  2020-09-01T08:45.00 Off, 88%
light   IKEA TRADFRI bulb E27 CWS opal 600lm     Light 3B                       L3                   True  2020-09-01T08:46.00 Off
sensor  Philips SML001                           Toilet Motion                  S10, S12, S13        True  2020-09-01T08:46:29 Off, 19.8C, 1.0lx
sensor  Philips RWL021                           Living Front Curtain Remote    S11                  True  2020-09-01T08:45.00
sensor  Xiaomi Door Window                       Cellar Door                    S20                  True  2020-09-01T08:16:35 Close
sensor  Xiaomi Temperature/Humidity (Square)     Kitchen Fridge Small           S24, S25, S26        True  2020-09-01T08:40:57 7.69C, 69.63%, 1018hPa
```

#### rename device
To run the script, execute it as follows:

```
./deconz.py rename
```
The script will interactively ask which device to rename and what the name should be:
```
Nr. Type    Model                                    Name
-----------------------------------------------------------------------------------
...
 2. switch  Innr SP 120                              Living TV
...

Enter number or q: 2

Current name(s):
L2   Living TV
S4   Living TV Energy
S5   Living TV Power
Enter new name: Living TV2

New name(s):
L2   Living TV2
S4   Living TV2 Energy
S5   Living TV2 Power
Change? [Y/n]: Y
```


### Support

The script is delivered as-is, and in principle I do not do feature requests (unless it is useful for me too). If you want a feature added, I am open to merge a PR.

