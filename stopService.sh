#!/bin/bash

##
# Script to cleanup the hanging server process, and logs.
#

# This command does four things
# 1) Get the running process information
# 2) Gets only python process
# 3) Excludes the output which will show grep in it
# 4) List python process id

PID=`ps aux | grep Python | grep -v grep | awk '{print $2}'`

# Loop for process ids to kill python processes.
for pid in $PID
do 
	kill -9 $pid
done
