#!/bin/bash

set -e

python3 ./bench_ram.py benchmark-ram-rev
python3 ./bench_circ.py benchmark-circ-rev
