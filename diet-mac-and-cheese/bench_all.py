import os
import time
import math
import json
import random
import platform
import subprocess
import datetime
import itertools

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

        # apply network settings
        if platform.system() == 'Darwin':
            self.cmd(f'(cat /etc/pf.conf && echo "dummynet-anchor \"customRule\"" && echo "anchor \"customRule\"") | sudo pfctl -f -')
            self.cmd('echo "dummynet in quick proto {udp,tcp,icmp} from any to any pipe 1" | sudo pfctl -a customRule -f -')
            self.cmd(f'sudo dnctl pipe 1 config delay {delay} bw {mbits}Mbit/s')
        else:
            # tc qdisc add dev eth0 handle 1: root htb default 11
            self.cmd(f'sudo tc qdisc add dev eth0 handle 1: root htb default 11')
            self.cmd(f'sudo tc class add dev eth0 parent 1: classid 1:1 htb rate 1000Mbps')
            self.cmd(f'sudo tc class add dev eth0 parent 1:1 classid 1:11 htb rate {mbits}Mbit')
            self.cmd(f'sudo tc qdisc add dev eth0 parent 1:11 handle 10: netem delay {delay}ms')

        # run bandwidth and delay tests
        after = network_test()

        print(f'{PURPLE}### Network Before ###', END)
        print()
        print(before['ping'])
        print(before['iperf'])

        print(f'{BLUE}### Network After ({config}) ###', END)
        print()
        print(after['ping'])
        print(after['iperf'])

        return {
            "before": before,
            "after": after,
            "delay": delay,
            "mbits": mbits
        }
    
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

        cmd = f"cargo run --release --bin {BINARY_NAME} --"
        cmd += " --text"
        cmd += " --lpn medium"
        cmd += f" --relation {self.relation}"
        cmd += f" --instance {self.instance}"
        cmd += f" --connection-addr 127.0.0.1:{self.port}"
        cmd += " prover"
        cmd += f" --witness {self.witness}"

        env = os.environ.copy()
        env['RUSTFLAGS'] = '-C target-cpu=native'

        print(f'{GREEN}$ {cmd} {END}')

        self.process = subprocess.Popen(
            cmd,
            env=env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

class Verifier:
    def __init__(self, prover):
        self.relation = prover.relation
        self.instance = prover.instance

        # check that the files exist
        assert os.path.exists(self.relation)
        assert os.path.exists(self.instance)

        cmd = f"cargo run --release --bin {BINARY_NAME} --"
        cmd += " --text"
        cmd += " --lpn medium"
        cmd += f" --relation {self.relation}"
        cmd += f" --instance {self.instance}"
        cmd += f" --connection-addr 127.0.0.1:{prover.port}"

        print(f'{GREEN}$ {cmd} {END}')

        env = os.environ.copy()
        env['RUSTFLAGS'] = '-C target-cpu=native'

        self.prover = prover
        self.process = subprocess.Popen(
            cmd,
            env=env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

    def complete(self):
        # wait for both processes to complete
        self.process.wait()
        self.prover.process.wait()

        prover_stdout = self.prover.process.stdout.read().decode()
        prover_stderr = self.prover.process.stderr.read().decode()

        verifier_stdout = self.process.stdout.read().decode()
        verifier_stderr = self.process.stderr.read().decode

        assert self.process.returncode == 0, verifier_stderr
        assert self.prover.process.returncode == 0, prover_stderr

        # content checks
        assert 'bytes sent:' in verifier_stdout
        assert 'bytes recv:' in verifier_stdout
        assert 'bytes total:' in verifier_stdout
        assert 'time circ exec:' in verifier_stdout

        assert 'bytes sent:' in prover_stdout
        assert 'bytes recv:' in prover_stdout
        assert 'bytes total:' in prover_stdout
        assert 'time circ exec:' in prover_stdout

        # return the prover/verifier outputs
        return {
            "verifier": {
                "stdout": verifier_stdout,
                "stderr": verifier_stderr,
            },
            "prover": {
                "stdout": prover_stdout,
                "stderr": prover_stderr,
            },
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
        "uname -a"
        "cat /proc/meminfo",
        "cat /proc/cpuinfo",
    ]

uname = subprocess.run('uname -a', shell=True, check=True, stdout=subprocess.PIPE).stdout.decode().strip()
hostname = subprocess.run('hostname', shell=True, check=True, stdout=subprocess.PIPE).stdout.decode().strip()

sys_info = {}
for cmd in cmds:
    proc = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE)
    assert proc.returncode == 0
    print(f'{GREEN}$ {cmd} {END}')
    sys_info[cmd] = proc.stdout.decode()

def execute(runs):
    # sort the runs by network settings
    runs = sorted(runs)
    total = len(runs)
    network = Network()
    finished = 0
    start_time = time.time()
    for (num, (net, bench)) in enumerate(runs):
        # read the meta data
        path = os.path.join(BENCH_DIR, bench)
        meta = os.path.join(path, 'meta.json')
        meta = json.load(open(meta))

        estimated_time = math.inf 
        if finished > 0:
            delta = time.time() - start_time
            per_bench = delta / finished
            remaining = total - num
            estimated_time = per_bench * remaining
        
        print(f'{BLUE}Estimated Time Remaining: {estimated_time} seconds{END}')
            
        # check if we already ran this benchmark
        result = os.path.join(path, result_file(net))
        if os.path.exists(result):
            print(f'{YELLOW}### [{num+1}/{total}] : Skipping {bench} {net} ###{END}')
            continue

        print(f'{YELLOW}### [{num+1}/{total}] : Running {bench} {net} ###{END}')

       
        
        # apply network settings
        net_check = network.apply(net)

        s = "Benchmark:\n"
        s += f"- Index: {num+1}/{total}\n"
        s += f"- Network: {net}\n"
        s += f"- Meta: {meta}\n"
        s += f"- Est. Time Remaining: {estimated_time:.2f}s\n"
        s += f"- Start Time: {datetime.datetime.now()}\n"
        s += f"- Uname: {uname}\n"
        s += f"- Hostname: {hostname}\n"
        s += f"\n"
        s += f"{net_check["after"]["iperf"]}\n"
        ntfy(s)

        # sanity check: no other BINARY_NAME process is running
        # ps -axc -o comm
        proc = subprocess.run(f'ps -axc -o comm', shell=True, check=True, stdout=subprocess.PIPE)
        assert proc.returncode == 0
        for line in proc.stdout.decode().split('\n'):
            if BINARY_NAME in line:
                raise Exception(f'Process {BINARY_NAME} is already running')
        
        for _ in range(5):
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
                print(f'{RED}### ERROR {bench} {net} ###{END}')
                ntfy(f'''Error: {bench} {net}''')
                print(e)

        else:
            exit(1)

        finished += 1
        
    ntfy(f'''Completed {total} benchmarks :)''')

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
        execute(list(itertools.product(networks, benchmarks)))