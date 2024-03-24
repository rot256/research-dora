import os
import sys
import itertools
import random

from circus import *

INPUTS = 100      # inputs of branch
OUTPUTS = 100     # outputs of branch
BRANCHES_0 = 50_000 # number of branches to run (number of switches)
BRANCHES_1 = 100_000 # number of branches to run (number of switches)

'''
params_clauses = [10, 100, 1_000, 10_000]
params_gates = [10, 100, 1_000, 10_000]

params_sets = list(itertools.product(params_clauses, params_gates))
params_sets = [
    (2**3, 2**18),
    (2**6, 2**15),
    (2**9, 2**12),
    (2**12, 2**9),
    (2**15, 2**6)
]
'''

try:
    bench = os.path.join(sys.argv[1], f'benchmarks/')
    print(f"removing: {bench}")
    os.remove(bench)
except OSError:
    pass

from pathlib import Path
Path(sys.argv[1]).mkdir(parents=True, exist_ok=True)

# write benchmark script
script_path = os.path.join(sys.argv[1], 'bench_all.sh')
with open(script_path, 'w') as f:
    f.write('''#!/bin/bash

set -e

PORT=7876

for DELAY in 0 10 100; do
    # set simulated network delay using traffic control:
    echo "Run benchmarks with delay: ${DELAY}ms"

    sudo tc qdisc del dev lo root || true
    sudo tc qdisc add dev lo root handle 1:0 netem delay ${DELAY}msec
    ping -c 1 127.0.0.1

    # simulate network conditions for particular port (source or destination)
    # sudo tc qdisc del dev lo root || true
    # sudo tc qdisc add dev lo handle 1: root htb
    # sudo tc class add dev lo parent 1: classid 1:1 htb rate 1gbit
    # sudo tc qdisc add dev lo parent 1:1 handle 10: netem delay ${DELAY}msec
    # sudo tc filter add dev lo protocol ip parent 1: prio 1 u32 match ip dport $PORT 0xffff flowid 1:1
    # sudo tc filter add dev lo protocol ip parent 1: prio 1 u32 match ip sport $PORT 0xffff flowid 1:1

    # run each benchmark with given delay
    for d in benchmarks/* ; do
        echo "Running test: $d"

        # start prover
        RUSTFLAGS='-C target-cpu=native' cargo run --release --bin dietmc_0p -- \\
            --text \\
            --lpn medium \\
            --relation $d/relation* \\
            --instance $d/public* \\
            --connection-addr 127.0.0.1:${PORT} \\
            prover \\
            --witness $d/private* 2> $d/${DELAY}_prover.out &

        pid_prv=$!

        # start verifier
        RUSTFLAGS='-C target-cpu=native' cargo run --release --bin dietmc_0p -- \\
            --text \\
            --lpn medium \\
            --relation $d/relation* \\
            --instance $d/public* \\
            --connection-addr 127.0.0.1:${PORT} 2> $d/${DELAY}_verifier.out &
        pid_vrf=$!

        # wait for both to terminate
        wait $pid_prv
        wait $pid_vrf

        # print times
        grep "time circ exec:" $d/${DELAY}_prover.out
        grep "time circ exec:" $d/${DELAY}_verifier.out
    done

    sudo tc qdisc del dev lo root || true
done

echo "Benchmark complete."
''')

# make executable
import stat
st = os.stat(script_path)
os.chmod(script_path, st.st_mode | stat.S_IEXEC)

BOUND = 2**27

params_clauses  = [2**3, 2**6, 2**9, 2**12, 2**15]
params_gates    = [2**15, 2**12, 2**9, 2**6]
params_branches = [BRANCHES_0, BRANCHES_1]
params_branches = [25_000]

# product of all params
params_sets = list(itertools.product(params_clauses, params_gates, params_branches))

# do not exceed bound (we will run out of memory :( )
params_sets = [par for par in params_sets if par[0] * par[1] <= BOUND]

# start with biggest params
params_sets = sorted(params_sets, key=lambda x: (-x[0] * x[1], -x[0]))

print(f"num parameters: {len(params_sets)}")

# params_clauses = [10, 100]
# params_gates = [10, 100]
# rsync -azP --exclude '*target/*' -r swanky-dora/ ubuntu@ec2-3-144-192-158.us-east-2.compute.amazonaws.com:~/swanky
for (CLAUSES, GATES, BRANCHES) in params_sets:
    random.seed(0xDEADBEEF)

    print(f"clauses: {CLAUSES}, gates: {GATES}, inputs: {INPUTS}, outputs: {OUTPUTS}, branches: {BRANCHES}")

    circuit = Circuit()

    ff = Field(340282366920938463463374607431768211297)

    bf = circuit.backend(ff)

    def rand_func(fn, muls, inputs, outputs):
        import random

        bf = fn.backend(ff)
        ins = bf.input(inputs)
        out = bf.output(outputs)
        exprs = [ins[i] for i in range(len(ins))]

        adds = muls

        while muls > 0:
            n = random.randint(0, 1)
            i = random.randint(0, len(exprs) - 1)
            j = random.randint(0, len(exprs) - 1)
            c = ff.random()
            if n == 0 and adds > 0:
                exprs.append(bf.add(exprs[i], exprs[j]))
                adds -= 1
            elif n == 1:
                exprs.append(bf.mul(exprs[i], exprs[j]))
                muls -= 1
            else:
                pass

        for i in range(len(out)):
            out[i] = exprs[-(i + 1)]

    print("create clauses...")

    num_inputs = min(INPUTS, GATES)
    num_outputs = min(OUTPUTS, GATES)

    RND = circuit.func(lambda f: rand_func(f, GATES, num_inputs, num_outputs))

    clauses = []
    for i in range(CLAUSES):
        if i > 0 and i % 1000 == 0:
            print(f"    {i}/{CLAUSES}")
        clauses.append(RND)
        #clauses.append(
        #    circuit.func(lambda f: rand_func(f, GATES, num_inputs, num_outputs))
        #)

    print("create disjunction...")

    def disjunction(fn, clauses):
        bf = fn.backend(ff)

        # condition input
        _ = bf.input(1)

        # define inputs
        for ins in clauses[0].inputs:
            _ = bf.input(len(ins))

        # define outputs
        for out in clauses[0].outputs:
            _ = bf.output(len(out))

        # fill body with plugin
        args = []
        for i, cl in enumerate(clauses):
            args.append(str(i))
            args.append(cl)

        fn.plugin("galois_disjunction_v0", "switch", "strict", *args)

    disj = circuit.func(lambda fn: disjunction(fn, clauses))

    print("create branches...")

    # sample random inputs
    inp = [bf.private(ff.random) for _ in range(num_inputs)]

    for j in range(BRANCHES):
        # load the condition
        cond = bf.private(lambda: random.randrange(0, CLAUSES))
        out  = disj.call(cond, tuple(inp))

        # call each clause
        #for i in range(1):
        #    bf.assert_eq(out[i], ff.new(out[i].eval()))
        # mark as live (to ensure included in circuit)
        bf.live(out)

    print("compile...")

    import os

    # added so that we execute biggest -> smallest
    size = BRANCHES * CLAUSES * GATES
    order = 10**16 - size
    direc = os.path.join(sys.argv[1], f'benchmarks/branches_{order:016}_{BRANCHES}_clauses_{CLAUSES}_gates_{GATES}/')

    from pathlib import Path
    Path(direc).mkdir(parents=True, exist_ok=True)

    relation = os.path.join(direc, 'relation.txt')
    private = os.path.join(direc, 'private.txt')
    public = os.path.join(direc, 'public.txt')
    meta = os.path.join(direc, 'meta.json')

    print(f"writing to:")
    print(f"    {relation}")
    print(f"    {private}")
    print(f"    {public}")

    # write metadata file
    import json
    s = json.dumps({
        "branches": BRANCHES,
        "clauses": CLAUSES,
        "gates": GATES,
        "inputs": num_inputs,
        "outputs": num_outputs,
    })

    with open(meta, 'w') as f:
        f.write(s)

    # write circuit
    with open(relation, 'w') as f:
        for line in circuit.compile():
            f.write(line + '\n')

    # write witness
    with open(private, 'w') as f:
        for line in circuit.witness(ff):
            f.write(line + '\n')

    # write public input
    with open(public, 'w') as f:
        f.write("version 2.0.0;\n");
        f.write("public_input;\n");
        f.write("@type field 2305843009213693951;\n")
        f.write("@begin\n")
        f.write("    <0>;\n")
        f.write("@end")

