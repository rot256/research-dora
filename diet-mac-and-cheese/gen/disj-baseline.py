import sys
import random

from circus import *

if __name__ == '__main__':

    GATES = 10_000 # per clause
    INPUTS = 100
    OUTPUTS = 100
    CLAUSES = 1000
    BRANCHES = 256

    random.seed(0xdeadbeef)

    circuit = Circuit()

    ff = Field(2305843009213693951)

    bf = circuit.backend(ff)

    def rand_func(fn, steps, inputs, outputs):
        import random

        bf  = fn.backend(ff)
        ins = bf.input(inputs)
        out = bf.output(outputs)
        exprs = [ins[i] for i in range(len(ins))]

        for i in range(steps):
            n = random.randint(0, 4)
            i = random.randint(0, len(exprs)-1)
            j = random.randint(0, len(exprs)-1)
            c = ff.random()
            if n == 0:
                exprs.append(bf.add(exprs[i], exprs[j]))
            elif n == 1:
                exprs.append(bf.mul(exprs[i], exprs[j]))
            elif n == 2:
                exprs.append(bf.mul(exprs[i], c))
            elif n == 3:
                exprs.append(bf.add(exprs[i], c))

        for i in range(len(out)):
            out[i] = exprs[-(i+1)]

        return fn

    clauses = []

    print('create clauses...')

    for i in range(CLAUSES):
        clauses.append(rand_func(circuit.func(), GATES, INPUTS, OUTPUTS))

    print('create branches...')

    for j in range(BRANCHES):
        print('branch:', j)
        inp = []
        for _ in range(INPUTS):
            inp.append(bf.private(lambda: ff.random()))

        for cls in clauses:
            res = cls.call(tuple(inp))
            out = cls.eval([e.eval() for e in inp])
            for i in range(OUTPUTS):
                bf.assert_eq(res[i], ff.new(out[i]))

    print('compile...')

    if len(sys.argv) > 1:
        with open(sys.argv[1], 'w') as f:
            for line in circuit.compile():
                f.write(line + '\n')

        with open(sys.argv[2], 'w') as f:
            for line in circuit.witness(ff):
                f.write(line + '\n')