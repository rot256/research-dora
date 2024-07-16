#!/bin/bash

# install buildutils iperf screen
sudo apt update -y
sudo apt install -y \
    build-essential \
    gcc \
    curl \
    git \
    iperf3 \
    screen \
    python3
    

# install rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
. "$HOME/.cargo/env"

# needed for screen to work
export TERM=xterm-xfree86

