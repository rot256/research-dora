import os
import sys
import itertools
import random

from circus import *

INPUTS = 100        # inputs of branch
OUTPUTS = 100       # outputs of branch
BRANCHES_0 = 12_500 # number of branches to run (number of switches)
BRANCHES_1 = 25_000 # number of branches to run (number of switches)
BRANCHES_2 = 50_000 # number of branches to run (number of switches)

field = sys.argv[1]
output = sys.argv[2]

ffs = [
    Field(340282366920938463463374607431768211297, 'f128'),
    Field(2305843009213693951, 'f61')
]

for ff in ffs:
    if ff.name == field:
        break
else:
    raise ValueError(f"field {field} not found")


# create output directory
from pathlib import Path
Path(output).mkdir(parents=True, exist_ok=False)

params_clauses  = [2**3, 2**6, 2**9, 2**12, 2**15]
params_gates    = [2**6, 2**9, 2**12, 2**15]
params_branches = [BRANCHES_0, BRANCHES_1, BRANCHES_2]

# product of all params
params_sets = list(itertools.product(params_clauses, params_gates, params_branches))

# do not exceed bound (we will run out of memory :( )
# params_sets = [par for par in params_sets if par[0] + par[1] <= BOUND]

for (CLAUSES, GATES, BRANCHES) in params_sets:
    random.seed(0xDEADBEEF)

    print(f"clauses: {CLAUSES}, gates: {GATES}, inputs: {INPUTS}, outputs: {OUTPUTS}, branches: {BRANCHES}")

    circuit = Circuit()

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
    size = BRANCHES * GATES
    direc = os.path.join(output, f'branches_{size:016}_{BRANCHES}_clauses_{CLAUSES}_gates_{GATES}/')

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
        "field": {
            "size": ff.size,
            "name": ff.name
        }
    }, indent=4)

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
        f.write(f"@type field {ff.size};\n")
        f.write("@begin\n")
        f.write("    <0>;\n")
        f.write("@end")
