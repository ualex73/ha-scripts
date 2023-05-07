#!/bin/bash

# Wrapper around cert.py, to prevent python lib errors

CNT=`pip3 list 2>/dev/null | egrep -i "^paramiko |^scp |^voluptuous |^pyyaml |^python-telegram-bot " | wc -l`

# Not enough libs, so install them
if [ $CNT -lt 5 ]; then
  echo "INFO: pip3 running, because libs are missing '$CNT' should be '6'"
  pip3 install paramiko==2.7.2
  pip3 install scp==0.14.1
  pip3 install voluptuous==0.12.2
  pip3 install pyyaml==5.4.1
  pip3 install python_telegram_bot==13.7
fi

/docker/script/cert/cert.py "$@"
RC=$?

if [ $RC -ne 0 ]; then
  echo "`date '+%Y-%m-%d %H:%M:%S'` ERROR: cert.py return RC=$RC"
else
  echo "`date '+%Y-%m-%d %H:%M:%S'` INFO: cert.py finished OK"
fi
