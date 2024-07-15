from utils import *

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

uname = subprocess.run('uname -a', shell=True, check=True, stdout=subprocess.PIPE).stdout.decode().strip()
hostname = subprocess.run('hostname', shell=True, check=True, stdout=subprocess.PIPE).stdout.decode().strip()

sys_info = get_sys_info()

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
