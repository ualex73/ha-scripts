# Script for monitoring Docker TCP/IP persistent connections, HTTP endpoints and DeCONZ

This script can monitor connections inside Docker container(s), if the connections are persistent. For example AppDaemon, NodeRED will have a persistent connection to Home-Assistant and can be important to know if this connection is gone. It can also monitor HTTP endpoints like Home Assistant or Pi-Hole API. The DeCONZ API can be monitor to check if a device has stopped sending updates to the DeCONZ API (lastseen/lastupdated is then 240 minutes or older).

## Check-Health

### Requirements
- Pythone 3.6+
- Ubuntu 18.04+ (should work on other Linux flavors, but untested and unsupported)

### Installation

- Clone this git repository
- Install the required dependencies with "pip3 install -r check-health-requirements.txt"
- Select an example file and rename/copy it to "check-health.yaml"
- Configure "check-health.yaml", setup the hostname, API key and telegram token/chatid
- Setup of the telegram bot isn't documented, this is assumed you know how to do this (telegram is the only option to notify)

### Usage
To run the script, execute it as "root" as follows:
```
./check-health.py
```

It can be added to the "root" crontab entry as follows:
```
* * * * * /this-is-a-folder/check-health.py >>/this-is-a-folder/check-health.stdout 2>&1
```


### Output
The script creates a file called "check-health.data.yaml", where it keeps track of the current state. If the faulty state is persisent for 2 attempts, it will send out a telegram message. 

### Support

The script is delivered as-is, and in principle I do not do feature requests (unless it is useful for me too). If you want a feature added, I am open to merge a PR.

