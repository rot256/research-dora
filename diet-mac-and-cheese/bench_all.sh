#!/bin/bash

set -e

python3 ./bench_ram.py benchmark-ram-f61-rev
python3 ./bench_circ.py benchmark-circ-f61-rev
python3 ./bench_circ.py benchmark-circ-f128-rev
