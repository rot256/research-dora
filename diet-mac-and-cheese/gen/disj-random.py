import sys
import random

from circus import Circuit, Field

if __name__ == "__main__":
    GATES = 10_000  # per clause
    INPUTS = [100]
    OUTPUTS = [100]
    CLAUSES = 1000
    BRANCHES = 5000

    random.seed(0xDEADBEEF)

    circuit = Circuit()

    # ff = expr.Field(2305843009213693951)
    ff = Field(340282366920938463463374607431768211297)

    bf = circuit.backend(ff)

    def rand_func(fn, steps, inputs, outputs):
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

        for i in range(steps):
            n = random.randint(0, 4)
            i = random.randint(0, len(exprs) - 1)
            j = random.randint(0, len(exprs) - 1)
            c = ff.random()
            if n == 0:
                exprs.append(bf.add(exprs[i], exprs[j]))
            elif n == 1:
                exprs.append(bf.mul(exprs[i], exprs[j]))
            elif n == 2:
                exprs.append(bf.mul(exprs[i], c))
            elif n == 3:
                exprs.append(bf.add(exprs[i], c))

        for o in out:
            for n in range(len(o)):
                o[n] = exprs[-(out_n)]
                out_n -= 1

        return fn

    print("create clauses...")

    clauses = []

    for i in range(CLAUSES):
        clauses.append(rand_func(circuit.func(), GATES, INPUTS, OUTPUTS))

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

    print("create disj...")

    disj = disjunction(circuit.func(), clauses)

    print("create branches...")

    for j in range(BRANCHES):
        # load some inputs
        inps = []
        for n in INPUTS:
            inp = []
            for _ in range(n):
                inp.append(bf.private(lambda: ff.random()))
            inps.append(tuple(inp))

        # load the condition
        cond = bf.private(lambda: random.randrange(0, CLAUSES))

        # run disjunction
        r = disj.call(cond, *inps)

        # assert outputs
        for out in r:
            for i in range(len(out)):
                bf.assert_eq(out[i], out[i].eval())

    print("compile to circuit...")

    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as f:
            for line in circuit.compile():
                f.write(line + "\n")

        with open(sys.argv[2], "w") as f:
            for line in circuit.witness(ff):
                f.write(line + "\n")
    else:
        for line in circuit.compile():
            print(line)

        print()

        for line in circuit.witness(ff):
            print(line)
