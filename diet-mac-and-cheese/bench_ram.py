import sys

from utils import *

BINARY_NAME = 'dietmc_ram'

class Prover:
    def __init__(
        self,
        ram_size,
        ram_steps
    ):
        self.port = random.randint(8000, 50_000)
        self.ram_size = ram_size
        self.ram_steps = ram_steps

        # check that the files exist
        self.output = tempfile.TemporaryFile()

        cmd = [
            "cargo",
            "run",
            "--release",
            "--bin", BINARY_NAME,
            "--",
            "--lpn", "medium",
            "--ram-size", str(self.ram_size),
            "--ram-steps", str(self.ram_steps),
            "--connection-addr", f"127.0.0.1:{self.port}",
            "--prover",
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
        self.output = tempfile.TemporaryFile()
        self.ram_size = prover.ram_size
        self.ram_steps = prover.ram_steps

        cmd = [
            "cargo",
            "run",
            "--release",
            "--bin", BINARY_NAME,
            "--",
            "--lpn", "medium",
            "--ram-size", str(self.ram_size),
            "--ram-steps", str(self.ram_steps),
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
                if self.prover.process.returncode != 0:
                    print(self.prover.output.read().decode())
                    raise Exception('Prover failed')
                break
            except subprocess.TimeoutExpired:
                pass

            try:
                self.process.wait(5)
                if self.process.returncode != 0:
                    print(self.output.read().decode())
                    raise Exception('Verifier failed')
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
        assert "time ram exec:" in prover_stdout

        assert "bytes sent:" in verifier_stdout
        assert "bytes recv:" in verifier_stdout
        assert "bytes total:" in verifier_stdout
        assert "time ram exec:" in verifier_stdout

        # return the prover/verifier outputs
        return {
            "verifier": verifier_stdout,
            "prover": prover_stdout,
        }

ram_sizes = [
    2**10,
    2**11,
    2**12,
    2**13,
    2**14,
    2**15,
    2**16,
    2**17,
    2**18,
    2**19,
    2**20,
]

ram_steps = [
    2**22,
    2**23,
    2**24,
]

def result_file(item):
    (net, ram_size, ram_steps) = item
    return f'result-{net.mbits}mbits-{net.delay}ms-{ram_size}size-{ram_steps}steps.json'

if __name__ == '__main__':
    benchmarks = list(itertools.product(NETWORKS, ram_sizes, ram_steps))
    benchmarks = sorted(benchmarks)
    output_dir = sys.argv[1]

    sys_info = get_sys_info()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    def ests(item):
        (net, ram_size, ram_steps) = item
        return ram_size + ram_steps

    network = Network()
    estimator = WorkEstimator(est=ests)

    print(f'{YELLOW}Running Benchmarks:{END}')
    print(f'{YELLOW}  - networks   : {len(NETWORKS)}{END}')
    print(f'{YELLOW}  - ram_sizes  : {len(ram_sizes)}{END}')
    print(f'{YELLOW}  - ram_steps  : {len(ram_steps)}{END}')
    print(f'{YELLOW}  - output_dir : {output_dir}{END}')
    print(f'{YELLOW}  - benchmarks : {len(benchmarks)}{END}')

    total = len(benchmarks)

    # estimate the total work
    for item in benchmarks:
        path = os.path.join(output_dir, result_file(item))
        if not os.path.exists(path):
            estimator.add(item)

    # run the benchmarks
    for num, item in enumerate(benchmarks):
        (net, ram_size, ram_steps) = item

        # check if the result file already exists
        path = os.path.join(output_dir, result_file(item))
        if os.path.exists(path):
            print(f'{YELLOW}skipping {path}{END}')
            continue

        # apply the network configuration
        net_check = network.apply(net)
        assert net_check is not None

        meta = {
            "ram": True,
            "ram_size": ram_size,
            "ram_steps": ram_steps,
            "field": {
                "name": "f61",
                "size": 2305843009213693951
            }
        }

        remaining_time = estimator.remaining()

        # notify me
        s = "Benchmark:\n"
        s += f"- Index: {num+1}/{total}\n"
        s += f"- Network: {net}\n"
        s += f"- Meta: {meta}\n"
        s += f"- Est. Time Remaining: {remaining_time:.2f}s\n"
        s += f"- Start Time: {datetime.datetime.now()}\n"
        s += f"\n"
        s += f"{net_check["after"]["iperf"]}\n"
        s += f"\n"
        s += f"{net_check["after"]["ping"]}\n"
        ntfy(s)

        # run the benchmark
        print(f'{YELLOW}Running {path}{END}')
        for _ in range(5):
            # sanity check: ensure no BINARY_NAME process is running
            # ps -axc -o comm
            subprocess.run(f'killall {BINARY_NAME}', shell=True)

            try:
                prover = Prover(ram_size=ram_size, ram_steps=ram_steps)
                verifier = Verifier(prover)
                outputs = verifier.complete()
                break
            except Exception as e:
                import traceback
                backtrace = traceback.format_exc()
                print(f'{RED}Error: {e}{END}')
                print(f'{RED}{backtrace}{END}')
                ntfy(f'Error: {e}\n{backtrace}')
                time.sleep(5)
        else:
            print(f'{RED}Failed to run benchmark{END}')
            ntfy(f'Failed to run benchmark :(')
            exit(-1)

        # save the results
        result = {
            "meta": meta,
            "outputs": outputs,
            "network": net_check,
        }

        with open(path, 'w') as f:
            json.dump(result, f, indent=4)

        # update the estimator
        estimator.done(item)
