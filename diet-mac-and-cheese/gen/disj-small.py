import sys
import random

from circus import Circuit, Field

random.seed(0xDEADBEEF)

circuit = Circuit()

ff = Field(2305843009213693951)
# ff = Field(340282366920938463463374607431768211297)

bf = circuit.backend(ff)

def rand_func(fn, muls, inputs, outputs):
    import random

    bf = fn.backend(ff)

    ins = []
    out = []
    out_n = 0

    for n in inputs:
        w = bf.input(n)
        ins += [w[i] for i in range(len(w))]

    for n in outputs:
        out_n += n
        out.append(bf.output(n))

    exprs = list(ins)

    while muls > 0:
        n = random.randint(0, 4)
        i = random.randint(0, len(exprs) - 1)
        j = random.randint(0, len(exprs) - 1)
        c = ff.random()
        if n == 0:
            exprs.append(bf.add(exprs[i], exprs[j]))
        elif n == 1:
            exprs.append(bf.mul(exprs[i], exprs[j]))
            muls -= 1
        elif n == 2:
            exprs.append(bf.mul(exprs[i], c))
        elif n == 3:
            exprs.append(bf.add(exprs[i], c))

    for o in out:
        for n in range(len(o)):
            o[n] = exprs[-(out_n)]
            out_n -= 1

    return fn

MULS = 1400
CLAUSES = 50
SEQ = 200
STEPS = 1_000_000
INPUTS = [10]
OUTPUTS = [10]

clauses = []

for i in range(CLAUSES):
    clauses.append(
        circuit.func(lambda fn: rand_func(fn, MULS, INPUTS, OUTPUTS))
    )

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

    return fn

disj = circuit.func(lambda fn: disjunction(fn, clauses))

print("create branches...")

total = 0

assert STEPS % SEQ == 0

for _ in range(STEPS // SEQ):
    # load some inputs
    for n in INPUTS:
        out = []
        for _ in range(n):
            out.append(bf.private(lambda: ff.random()))

    # apply step function over-and-over
    for j in range(SEQ):
        print(total)
        total += 1

        # load the condition
        cond = bf.private(lambda: random.randrange(0, CLAUSES))

        # run disjunction
        out = disj.call(cond, tuple(out))
        out = [out[i] for i in range(len(out))]

    # assert outputs
    for i in range(len(out)):
        bf.assert_eq(out[i], out[i].eval())

with open(sys.argv[1], "w") as f:
    for line in circuit.compile():
        f.write(line + "\n")

with open(sys.argv[2], "w") as f:
    for line in circuit.witness(ff):
        f.write(line + "\n")
