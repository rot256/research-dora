import os
import time
import math
import json
import random
import platform
import subprocess
import datetime
import itertools
import fractions
import tempfile

BINARY_NAME = 'dietmc_0p'

BLACK = "\033[0;30m"
RED = "\033[0;31m"
GREEN = "\033[0;32m"
BROWN = "\033[0;33m"
BLUE = "\033[0;34m"
PURPLE = "\033[0;35m"
CYAN = "\033[0;36m"
LIGHT_GRAY = "\033[0;37m"
DARK_GRAY = "\033[1;30m"
LIGHT_RED = "\033[1;31m"
LIGHT_GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
LIGHT_BLUE = "\033[1;34m"
LIGHT_PURPLE = "\033[1;35m"
LIGHT_CYAN = "\033[1;36m"
LIGHT_WHITE = "\033[1;37m"
BOLD = "\033[1m"
FAINT = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"
BLINK = "\033[5m"
NEGATIVE = "\033[7m"
CROSSED = "\033[9m"
END = "\033[0m"

NOTIFY_ID = os.environ.get('NOTIFY_ID', None)

def get_sys_info():
    # get some system information
    if platform.system() == 'Darwin':
        cmds = [
            "system_profiler SPSoftwareDataType",
            "system_profiler SPHardwareDataType",
            "uname -a",
        ]
    else:
        cmds = [
            "lscpu",
            "lshw -short",
            "uname -a",
            "cat /proc/meminfo",
            "cat /proc/cpuinfo",
        ]

    sys_info = {}
    for cmd in cmds:
        print(f'{GREEN}$ {cmd} {END}')
        proc = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE)
        assert proc.returncode == 0
        sys_info[cmd] = proc.stdout.decode()

    return sys_info

class WorkEstimator:
    def __init__(self, est):
        self.est = est
        self.total = 0
        self.finished = 0
        self.start_time = time.time()

    def add(self, item):
        self.total += self.est(item)

    def done(self, item):
        self.finished += self.est(item)

    def remaining(self):
        if self.finished == 0:
            return math.inf
        delta = time.time() - self.start_time
        time_per_unit = fractions.Fraction(delta) / self.finished
        remaining = self.total - self.finished
        return float(time_per_unit * remaining)

BAD_RATE = 60 * 10
GOOD_RATE = 60
LAST_BAD_HTTP = 0
LAST_NOTIFY = 0

def ntfy(msg):
    global LAST_NOTIFY
    global LAST_BAD_HTTP

    from urllib import request, error
    print(f"## Notify : {NOTIFY_ID}")
    print(f"{CYAN}{msg}{END}")

    if NOTIFY_ID:
        # if we failed, wait for a bit
        if time.time() - LAST_BAD_HTTP < BAD_RATE:
            print(f"{RED}Error: HTTP error rate limit{END}")
            return

        # if we notified recently, wait for a bit
        if time.time() - LAST_NOTIFY < GOOD_RATE:
            print(f"{RED}Error: HTTP error rate limit{END}")
            return

        LAST_NOTIFY = time.time()

        try:
            # try to send a notification
            req =  request.Request(f"https://ntfy.sh/{NOTIFY_ID}", data=msg.encode('utf-8'))
            resp = request.urlopen(req)
            assert resp.status == 200
        except error.HTTPError as e:
            # don't fail if the notification fails
            LAST_BAD_HTTP = time.time()
            print(f"{RED}Error: {e}{END}")

def network_test():
    PORT = 5001

    # do a ping and capture the output
    res = subprocess.run("ping -c 5 localhost", shell=True, check=True, stdout=subprocess.PIPE)

    # start the iperf server into the background
    iperf_server = subprocess.Popen(
        f"iperf3 -s -p {PORT}",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # run the iperf client
    iperf_client = subprocess.run(
        f"iperf3 -c localhost -p {PORT} -t 10",
        shell=True,
        check=True,
        stdout=subprocess.PIPE
    )

    # kill the server
    iperf_server.kill()
    return {
        "ping": res.stdout.decode(),
        "iperf": iperf_client.stdout.decode()
    }

class Network:
    def __init__(self) -> None:
        self.applied = None
        self.result = None

        # reset for a clean state
        self.reset()

    def cmd(self, cmd, check=True):
        print(f'{GREEN}$ {cmd} {END}')
        if check:
            assert os.system(cmd) == 0
        else:
            os.system(cmd)

    def apply(self, config):
        if self.applied == config:
            return self.result

        delay = config.delay
        mbits = config.mbits

        # reset for a clean state
        self.reset()

        # run bandwidth and delay tests
        before = network_test()

        print()
        print(f'{PURPLE}### Network Before ###', END)
        print()
        print(before['ping'])
        print(before['iperf'])

        # apply network settings
        if platform.system() == 'Darwin':
            self.cmd(f'(cat /etc/pf.conf && echo "dummynet-anchor \"customRule\"" && echo "anchor \"customRule\"") | sudo pfctl -f -')
            self.cmd('echo "dummynet in quick proto {udp,tcp,icmp} from any to any pipe 1" | sudo pfctl -a customRule -f -')
            self.cmd(f'sudo dnctl pipe 1 config delay {delay} bw {mbits}Mbit/s')
        else:
            # tc qdisc add dev eth0 handle 1: root htb default 11
            # sudo tc qdisc add dev lo root handle 1:0 netem delay ${DELAY}msec

            self.cmd(f'sudo tc qdisc add dev lo handle 1: root htb default 11')
            self.cmd(f'sudo tc class add dev lo parent 1: classid 1:1 htb rate 1000Mbps')
            self.cmd(f'sudo tc class add dev lo parent 1:1 classid 1:11 htb rate {mbits}Mbit')
            self.cmd(f'sudo tc qdisc add dev lo parent 1:11 handle 10: netem delay {delay}ms')
            '''
            self.cmd(f'sudo tc qdisc add dev lo root netem delay {delay}ms')
            self.cmd(f'sudo tc qdisc add dev lo root tbf rate {mbits}Mbit latency 50ms burst 1540')
            '''

        # run bandwidth and delay tests
        after = network_test()

        print()
        print(f'{BLUE}### Network After ({config}) ###', END)
        print()
        print(after['ping'])
        print(after['iperf'])

        self.applied = config
        self.result = {
            "before": before,
            "after": after,
            "delay": delay,
            "mbits": mbits
        }
        return self.result

    def reset(self):
        # enable pfctl
        if platform.system() == 'Darwin':
            self.cmd(f'sudo pfctl -E')

        # cleanup
        if platform.system() == 'Darwin':
            # sudo dnctl -q flush || true
			# sudo pfctl -f /etc/pf.conf || true
            self.cmd(f'sudo dnctl -q flush', check=False)
            self.cmd(f'sudo pfctl -f /etc/pf.conf', check=False)
        elif platform.system() == 'Linux':
            self.cmd(f'sudo tc qdisc del dev lo root', check=False)
            self.cmd(f'sudo tc qdisc del dev eth0 root', check=False)
            self.cmd(f'sudo tc qdisc del dev eth1 root', check=False)
        else:
            raise Exception('Unsupported platform')

class NetworkConfig:
    def __init__(self, mbits = None, delay_ms_one_way = None):
        self.mbits = mbits
        self.delay = delay_ms_one_way

    def __str__(self) -> str:
        return f'{self.mbits}Mbit {self.delay}ms'

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, NetworkConfig):
            return False
        return self.mbits == value.mbits and self.delay == value.delay

    def __hash__(self) -> int:
        return hash((self.mbits, self.delay))

    def __lt__(self, value):
        return (self.mbits, self.delay) < (value.mbits, value.delay)

    def __gt__(self, value):
        return (self.mbits, self.delay) > (value.mbits, value.delay)

BW_HIGH = 1000
BW_MEDIUM = 100
BW_LOW = 50

DELAY_LOW = 0
DELAY_MEDIUM = 10
DELAY_HIGH = 100

NETWORKS = list(set([
    # high bandwidth, variable delay
    NetworkConfig(mbits=BW_HIGH, delay_ms_one_way=DELAY_LOW),
    NetworkConfig(mbits=BW_HIGH, delay_ms_one_way=DELAY_MEDIUM),
    NetworkConfig(mbits=BW_HIGH, delay_ms_one_way=DELAY_HIGH),
    # medium bandwidth, variable delay
    NetworkConfig(mbits=BW_MEDIUM, delay_ms_one_way=DELAY_LOW),
    NetworkConfig(mbits=BW_MEDIUM, delay_ms_one_way=DELAY_MEDIUM),
    NetworkConfig(mbits=BW_MEDIUM, delay_ms_one_way=DELAY_HIGH),
    # low bandwidth, variable delay
    NetworkConfig(mbits=BW_LOW, delay_ms_one_way=DELAY_LOW),
    NetworkConfig(mbits=BW_LOW, delay_ms_one_way=DELAY_MEDIUM),
    NetworkConfig(mbits=BW_LOW, delay_ms_one_way=DELAY_HIGH),
    # fixed delay, variable bandwidth
    # this should be redundant with the above,
    # but we include it for completeness
    NetworkConfig(mbits=BW_LOW, delay_ms_one_way=DELAY_MEDIUM),
    NetworkConfig(mbits=BW_MEDIUM, delay_ms_one_way=DELAY_MEDIUM),
    NetworkConfig(mbits=BW_HIGH, delay_ms_one_way=DELAY_MEDIUM),
]))
