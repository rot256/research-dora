set -e

for DELAY in 0 10 100; do
    sudo tc qdisc del dev lo root || true
    sudo tc qdisc add dev lo root handle 1:0 netem delay ${DELAY}msec
    ping -c 1 127.0.0.1

    RUSTFLAGS='-C target-cpu=native' JSON_OUTPUT=./ram_${DELAY}.json cargo test --release ram::tests::bench_net_ram -- --nocapture
done
