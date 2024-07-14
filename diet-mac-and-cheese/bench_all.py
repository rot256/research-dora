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

NOTIFY_ID = 'dora-benchmarking-run'

def ntfy(msg):
    from urllib import request
    print(f"## Notify : {NOTIFY_ID}")
    print(f"{CYAN}{msg}{END}")
    if NOTIFY_ID:
        req =  request.Request(f"https://ntfy.sh/{NOTIFY_ID}", data=msg.encode('utf-8'))
        resp = request.urlopen(req)
        assert resp.status == 200

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

class Prover:
    def __init__(self, path):
        self.port = random.randint(8000, 50_000)
        self.relation = os.path.join(path, 'relation.txt')
        self.instance = os.path.join(path, 'public.txt')
        self.witness = os.path.join(path, 'private.txt')

        # check that the files exist
        assert os.path.exists(self.relation)
        assert os.path.exists(self.instance)
        assert os.path.exists(self.witness)

        self.output = tempfile.TemporaryFile()

        cmd = [
            "cargo",
            "run",
            "--release",
            "--bin", BINARY_NAME,
            "--",
            "--text",
            "--lpn", "medium",
            "--relation", self.relation,
            "--instance", self.instance,
            "--connection-addr", f"127.0.0.1:{self.port}",
            "prover",
            "--witness", self.witness
        ]

        env = os.environ.copy()
        env['RUSTFLAGS'] = '-C target-cpu=native'

        print(f'{GREEN}$ {' '.join(cmd)}{END}')

        self.process = subprocess.Popen(
            cmd,
            env=env,
            stdout=self.output,
            stderr=self.output
        )

class Verifier:
    def __init__(self, prover):
        self.relation = prover.relation
        self.instance = prover.instance

        # check that the files exist
        assert os.path.exists(self.relation)
        assert os.path.exists(self.instance)

        self.output = tempfile.TemporaryFile()

        cmd = [
            "cargo",
            "run",
            "--release",
            "--bin", BINARY_NAME,
            "--",
            "--text",
            "--lpn", "medium",
            "--relation", self.relation,
            "--instance", self.instance,
            "--connection-addr", f"127.0.0.1:{prover.port}"
        ]

        print(f'{GREEN}$ {' '.join(cmd)}{END}')
        env = os.environ.copy()
        env['RUSTFLAGS'] = '-C target-cpu=native'

        # check that the prover is still running
        self.prover = prover
        assert self.prover.process.poll() is None, 'Prover is not running'

        # start the verifier
        self.process = subprocess.Popen(
            cmd,
            env=env,
            stdout=self.output,
            stderr=self.output
        )

    def complete(self):
        # wait for either the prover or verifier to finish
        while 1:
            try:
                self.prover.process.wait(5)
                assert self.prover.process.returncode == 0
                break
            except subprocess.TimeoutExpired:
                pass

            try:
                self.process.wait(5)
                assert self.process.returncode == 0
                break
            except subprocess.TimeoutExpired:
                pass

        # wait for other processes to finish
        # give them 60 seconds to do so
        self.process.wait(60)
        self.prover.process.wait(60)

        # read the outputs
        self.prover.output.seek(0)
        self.output.seek(0)
        verifier_stdout = self.output.read().decode()
        prover_stdout = self.prover.output.read().decode()

        # check the return codes
        assert self.process.returncode == 0, verifier_stdout
        assert self.prover.process.returncode == 0, prover_stdout

        # content checks
        assert "bytes sent:" in prover_stdout
        assert "bytes recv:" in prover_stdout
        assert "bytes total:" in prover_stdout
        assert "time circ exec:" in prover_stdout

        assert "bytes sent:" in verifier_stdout
        assert "bytes recv:" in verifier_stdout
        assert "bytes total:" in verifier_stdout
        assert "time circ exec:" in verifier_stdout

        # return the prover/verifier outputs
        return {
            "verifier": verifier_stdout,
            "prover": prover_stdout,
        }

def identifier(network):
    return f'{network.mbits}mbits-{network.delay}ms'

def result_file(network):
    return f'result-{identifier(network)}.json'

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

uname = subprocess.run('uname -a', shell=True, check=True, stdout=subprocess.PIPE).stdout.decode().strip()
hostname = subprocess.run('hostname', shell=True, check=True, stdout=subprocess.PIPE).stdout.decode().strip()

sys_info = {}
for cmd in cmds:
    print(f'{GREEN}$ {cmd} {END}')
    proc = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE)
    assert proc.returncode == 0
    sys_info[cmd] = proc.stdout.decode()

def work_of_meta(meta):
    return meta['branches'] * meta['gates'] + meta['clauses'] * meta['gates']

def execute(root, runs):
    # sort the runs by network settings
    runs = sorted(runs)
    total = len(runs)
    network = Network()
    start_time = time.time()

    # calculate the total work
    total_work = 0
    finished_work = 0
    for (net, bench) in runs:
        path = os.path.join(root, bench)
        meta = os.path.join(path, 'meta.json')
        meta = json.load(open(meta))
        result = os.path.join(path, result_file(net))
        if os.path.exists(result):
            continue
        total_work += work_of_meta(meta)

    for (num, (net, bench)) in enumerate(runs):
        # read the meta data
        path = os.path.join(root, bench)
        meta = os.path.join(path, 'meta.json')
        meta = json.load(open(meta))

        remaining_time = math.inf
        if finished_work > 0:
            assert total_work >= finished_work
            delta = time.time() - start_time
            time_per_unit = fractions.Fraction(delta) / finished_work
            remaining = total_work - finished_work
            remaining_time = float(time_per_unit * remaining)

        print(f'{BLUE}Estimated Time Remaining: {remaining_time} seconds{END}')

        # check if we already ran this benchmark
        result = os.path.join(path, result_file(net))
        if os.path.exists(result):
            print(f'{YELLOW}### [{num+1}/{total}] : Skipping {bench} {net} ###{END}')
            continue

        print(f'{YELLOW}### [{num+1}/{total}] : Running {bench} {net} ###{END}')

        # apply network settings
        net_check = network.apply(net)
        assert net_check is not None

        s = "Benchmark:\n"
        s += f"- Index: {num+1}/{total}\n"
        s += f"- Network: {net}\n"
        s += f"- Meta: {meta}\n"
        s += f"- Est. Time Remaining: {remaining_time:.2f}s\n"
        s += f"- Start Time: {datetime.datetime.now()}\n"
        s += f"- Uname: {uname}\n"
        s += f"- Hostname: {hostname}\n"
        s += f"\n"
        s += f"{net_check["after"]["iperf"]}\n"
        s += f"\n"
        s += f"{net_check["after"]["ping"]}\n"
        ntfy(s)

        # sanity check: ensure no BINARY_NAME process is running
        # ps -axc -o comm
        subprocess.run(f'killall {BINARY_NAME}', shell=True)

        for _ in range(3):
            try:
                # run the prover and verifier
                print('Start prover')
                prover = Prover(path)

                print('Start verifier')
                verifier = Verifier(prover)

                print('Wait for completion...')
                outputs = verifier.complete()

                # save the results
                results = {
                    "network": net_check,
                    "meta": meta,
                    "outputs": outputs,
                    "sys_info": sys_info
                }
                json.dump(results, open(result, 'w'))
                break

            except Exception as e:
                import traceback
                backtrace = traceback.format_exc()
                print(f'{RED}### ERROR {bench} {net} ###{END}')
                ntfy(f'Error: {bench} {net}\n\n{e}\n\n{backtrace}')
                time.sleep(5)
                raise e

        else:
            exit(1)

        finished_work += work_of_meta(meta)

    ntfy(f'''Completed {total} benchmarks.''')

if __name__ == '__main__':
    import sys
    for directory in sys.argv[1:]:
        benchmarks = os.listdir(directory)
        networks = [
            # fixed bandwidth, variable delay
            NetworkConfig(mbits=1000, delay_ms_one_way=0),
            NetworkConfig(mbits=1000, delay_ms_one_way=10),
            NetworkConfig(mbits=1000, delay_ms_one_way=100),
            # fixed delay, variable bandwidth
            NetworkConfig(mbits=50, delay_ms_one_way=10),
            NetworkConfig(mbits=100, delay_ms_one_way=10),
            NetworkConfig(mbits=1000, delay_ms_one_way=10),
        ]
        execute(directory, list(itertools.product(networks, benchmarks)))
