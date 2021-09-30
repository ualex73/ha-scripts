#!/bin/bash

# Wrapper around backup.py, to prevent python lib errors

CNT=`pip3 list 2>/dev/null | egrep -i "^docker |^paramiko |^scp |^voluptuous |^pyyaml |^python-telegram-bot " | wc -l`

# Not enough libs, so install them
if [ $CNT -lt 6 ]; then
  echo "INFO: pip3 running, because libs are missing '$CNT' should be '6'"
  pip3 install paramiko==2.7.2
  pip3 install scp==0.14.1
  pip3 install docker==5.0.2
  pip3 install voluptuous==0.12.2
  pip3 install pyyaml==5.4.1
  pip3 install python_telegram_bot==13.7
fi

/docker/script/backup/backup.py
RC=$?

if [ $RC -ne 0 ]; then
  echo "`date '+%Y-%m-%d %H:%M:%S'` ERROR: backup.py return RC=$RC"
else
  echo "`date '+%Y-%m-%d %H:%M:%S'` INFO: backup.py finished OK"
fi
