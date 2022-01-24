#!/bin/bash

# impact of network: rebuffer,fps,start-up
# sudo tc qdisc add dev wlp68s0 root netem loss 20%
# for test_num in 1 2 3 
# do
# 	echo "Role:$1. IP:$2. Test: $test_num. Loss: $lr"	
# 	for task in SPVC64-N x264 x265 DVC RLVC
# 	do
# 		python3 eval.py --Q_option Slow --task $task --role $1 --server_ip $2 --client_ip $3
# 		# sudo kill -9 `sudo lsof -t -i:8846`
# 	done
# done
# sudo tc qdisc del dev wlp68s0 root

# -----------------------------------------------------------
# live
# rebuffer,fps
for dataset in UVG MCL-JCV Xiph HEVC
do
	echo "Role:$1. SIP:$2. CIP:$3. Data: $dataset"	
	for task in SPVC64-N x264 x265 DVC RLVC
	do
		python3 eval.py --Q_option Slow --task $task --role $1 --server_ip $2 --client_ip $3 --dataset $dataset
	done
done

# offline
# efficiency: on-going now
# speed
# for task in SPVC64-N
# do
# 	python3 eval.py --task $task --encoder_test --Q_option Slow
# done

# -----------------------------------------------------------
# impact of hardware
# python eval.py --task SPVC64-N,DVC,RLVC --encoder_test --Q_option Slow
# take the smaller one into account
# python eval.py --task x265,x264 --fps 1000 --Q_option Slow

# -----------------------------------------------------------
# eval scalability: use different models measure mean,std on UVG
# dynamic
# for task in SPVC64-N
# do
# 	for p_num in {1..30} 
# 	do
# 		python3 eval.py --task $task --encoder_test --fP $p_num --bP $p_num --Q_option Slow
# 	done
# done

# -----------------------------------------------------------
# error propagation
# python eval.py --task LSVC-A,DVC-pretrained,RLVC2 --mode static
# watch result

# -----------------------------------------------------------
# ablation
# efficiency:trivial
# speed
# python eval.py --task SPVC64-N,SPVC64-N-D,SPVC64-N-L,SPVC64-N-O,SPVC64-N-P, --encoder_test