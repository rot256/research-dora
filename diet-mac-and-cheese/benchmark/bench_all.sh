#!/bin/bash

set -e

PORT=7703

for BW in 100 1000; do
	for DELAY in 10; do
	    # set simulated network delay using traffic control:
	    echo "Run benchmarks with delay: ${DELAY}ms"
		
	    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
		sudo tc qdisc del dev lo root || true
		sudo tc qdisc add dev lo root handle 1:0 netem delay ${DELAY}msec

	    elif [[ "$OSTYPE" == "darwin"* ]]; then
		# MacOS
		echo "Configure enumlated network conditions on MacOS"

		# cleanup
		sudo pfctl -E || true
		sudo dnctl -q flush || true
		sudo pfctl -f /etc/pf.conf || true
		killall iperf3-darwin || true

		# sanity check: run a network test
		echo "Before limits"
		iperf3-darwin -s -p $PORT >/dev/null || true &
		iperf3-darwin -c 127.0.0.1 -p $PORT -t 5
		killall iperf3-darwin

		# define what `pipe 1` should do to traffic
		echo "Apply limit"
		(cat /etc/pf.conf && echo "dummynet-anchor \"customRule\"" && echo "anchor \"customRule\"") | sudo pfctl -f -
		echo "dummynet in quick proto {udp,tcp,icmp} from any to any pipe 1" | sudo pfctl -a customRule -f -
		sudo dnctl pipe 1 config delay $DELAY bw ${BW}Mbit/s

		# sanity check: run a network test
		echo "After limits"
		iperf3-darwin -s -p $PORT >/dev/null || true &
		iperf3-darwin -c 127.0.0.1 -p $PORT -t 5
		killall iperf3-darwin
	    fi

	    ping -c 1 127.0.0.1

	    # run each benchmark with given network configuration
	    for d in benchmarks/* ; do
		echo "Running test: $d"

		# start prover
		RUSTFLAGS='-C target-cpu=native' cargo run --release --bin dietmc_0p -- \
		    --text \
		    --lpn medium \
		    --relation $d/relation* \
		    --instance $d/public* \
		    --connection-addr 127.0.0.1:${PORT} \
		    prover \
		    --witness $d/private* 2> $d/${DELAY}_${BW}_prover.out &

		pid_prv=$!

		# start verifier
		RUSTFLAGS='-C target-cpu=native' cargo run --release --bin dietmc_0p -- \
		    --text \
		    --lpn medium \
		    --relation $d/relation* \
		    --instance $d/public* \
		    --connection-addr 127.0.0.1:${PORT} 2> $d/${DELAY}_${BW}_verifier.out &
		pid_vrf=$!

		# wait for both to terminate
		wait $pid_prv
		wait $pid_vrf

		# print times
		grep "time circ exec:" $d/${DELAY}_prover.out
		grep "time circ exec:" $d/${DELAY}_verifier.out
	    done

	    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
		sudo tc qdisc del dev lo root || true
	    elif [[ "$OSTYPE" == "darwin"* ]]; then
		echo "Reset network conditions"
		sudo dnctl -q flush
		sudo pfctl -f /etc/pf.conf
	    fi
	done
done

echo "Benchmark complete."
