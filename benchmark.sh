#!/bin/bash
 
for lr in 0% 5% # 0-25%
do
	if [ $1 == 'client' ] | [ $1 == 'standalone' ]
	then
	    echo ">>>>>>>>>>>Enable: $lr loss<<<<<<<<<<<<"
	    sudo tc qdisc add dev lo root netem loss $lr
	fi
	for test_num in 1 2 3 #4 5 
	do
		echo "Role:$1. IP:$2. Test: $test_num. Loss: $lr"	
		for task in x264 x265 RLVC DVC SPVC96
		do
			python3 eval.py --task $task --role $1 --server_ip $2 
			# sudo kill -9 `sudo lsof -t -i:8846`
		done
	done
	if [ $1 == 'client' ] | [ $1 == 'standalone' ]
	then
	    echo ">>>>>>>>>>>Disable: $lr loss<<<<<<<<<<<<"
	    sudo tc qdisc del dev lo root
	fi
done
