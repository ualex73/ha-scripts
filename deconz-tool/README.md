# Script for list, rename or config DeCONZ devices via API

This script can list all devices with its values, rename devices, configure device settings and dump API information in JSON format.

## Check-Health

### Requirements
- Pythone 3.6+
- Ubuntu 18.04+ (should work on other Linux flavors, but untested and unsupported)

### Installation

- Clone this git repository
- Configure "deconz.yaml", setup the hostname, port and API key

### Usage
To run the script, execute it as "root" as follows:

```
./deconz.py list
```

### Support

The script is delivered as-is, and in principle I do not do feature requests (unless it is useful for me too). If you want a feature added, I am open to merge a PR.

