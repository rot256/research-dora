#!/bin/bash

set -e

PORT=7876

for DELAY in 0 10 100; do
    # set simulated network delay using traffic control:
    echo "Run benchmarks with delay: ${DELAY}ms"

    sudo tc qdisc del dev lo root || true
    sudo tc qdisc add dev lo root handle 1:0 netem delay ${DELAY}msec
    ping -c 1 127.0.0.1

    # simulate network conditions for particular port (source or destination)
    # sudo tc qdisc del dev lo root || true
    # sudo tc qdisc add dev lo handle 1: root htb
    # sudo tc class add dev lo parent 1: classid 1:1 htb rate 1gbit
    # sudo tc qdisc add dev lo parent 1:1 handle 10: netem delay ${DELAY}msec
    # sudo tc filter add dev lo protocol ip parent 1: prio 1 u32 match ip dport $PORT 0xffff flowid 1:1
    # sudo tc filter add dev lo protocol ip parent 1: prio 1 u32 match ip sport $PORT 0xffff flowid 1:1

    # run each benchmark with given delay
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
            --witness $d/private* 2> $d/${DELAY}_prover.out &

        pid_prv=$!

        # start verifier
        RUSTFLAGS='-C target-cpu=native' cargo run --release --bin dietmc_0p -- \
            --text \
            --lpn medium \
            --relation $d/relation* \
            --instance $d/public* \
            --connection-addr 127.0.0.1:${PORT} 2> $d/${DELAY}_verifier.out &
        pid_vrf=$!

        # wait for both to terminate
        wait $pid_prv
        wait $pid_vrf

        # print times
        grep "time circ exec:" $d/${DELAY}_prover.out
        grep "time circ exec:" $d/${DELAY}_verifier.out
    done

    sudo tc qdisc del dev lo root || true
done

echo "Benchmark complete."
