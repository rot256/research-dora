#!/bin/sh

python3 parse_all.py results/aws/benchmark-ram-f61-rev results/aws/combined-ram-f61.json
python3 parse_all.py results/aws/benchmark-circ-f61-rev results/aws/combined-circ-f61.json
python3 parse_all.py results/aws/benchmark-circ-f128-rev results/aws/combined-circ-f128.json

python3 parse_all.py results/hetzner/benchmark-ram-f61-rev results/hetzner/combined-ram-f61.json
python3 parse_all.py results/hetzner/benchmark-circ-f61-rev results/hetzner/combined-circ-f61.json
python3 parse_all.py results/hetzner/benchmark-circ-f128-rev results/hetzner/combined-circ-f128.json
