import sys
import random

from circus import *

if __name__ == "__main__":
    GATES = 10_000 # per clause
    INPUTS = 100
    OUTPUTS = 100
    CLAUSES = 1000
    BRANCHES = 256

    random.seed(0xDEADBEEF)

    circuit = Circuit()

    ff = Field(340282366920938463463374607431768211297)

    bf = circuit.backend(ff)

    def rand_func(fn, steps, inputs, outputs):
        import random

        bf = fn.backend(ff)
        ins = bf.input(inputs)
        out = bf.output(outputs)
        exprs = [ins[i] for i in range(len(ins))]

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

        for i in range(len(out)):
            out[i] = exprs[-(i + 1)]

    print("create clauses...")

    clauses = []
    for i in range(CLAUSES):
        clauses.append(
            circuit.func(lambda f: rand_func(f, GATES, INPUTS, OUTPUTS))
        )

    print("create disjunction...")
    
    def disj(fn, clauses):
        bf = fn.backend(ff)
        inp = bf.input(INPUTS)

        # call each clause
        outputs = []

        for cls in clauses:
            res = cls.call(tuple([inp[i] for i in range(len(inp))]))
            outputs.append([res[i] for i in range(len(res))])

        # create output
        while len(outputs) > 1:
            a = outputs[: len(outputs) // 2]
            b = outputs[len(outputs) // 2 :]

            outputs = []
            for xs, ys in zip(a, b):
                outputs.append([bf.add(x, y) for x,y in zip(xs, ys)])

            if len(outputs) % 2 == 1:
                outputs.append(outputs[-1])
        
        out = bf.output(OUTPUTS)
        for i in range(OUTPUTS):
            out[i] = output[i]

    disj = circuit.func(lambda fn: disj(fn, clauses))

    print("create branches...")

    for j in range(BRANCHES):
        # sample random inputs        
        inp = [bf.private(ff.random) for _ in range(INPUTS)]
        out = disj.call(tuple(inp))

        # call each clause
        for i in range(OUTPUTS):
            bf.assert_eq(out[i], ff.new(out[i].eval()))

    print("compile...")

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
