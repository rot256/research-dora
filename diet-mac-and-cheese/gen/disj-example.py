from circus import *

if __name__ == "__main__":
    # define a field
    ff = Field(340282366920938463463374607431768211297)

    # create a circuit and add a backend for the field ff
    circuit = Circuit()
    bf = circuit.backend(ff)

    def clause1(fn):
        bf = fn.backend(ff)
        inp = bf.input(3)  # 3 inputs
        out = bf.output(1)  # 1 output
        out[0] = bf.mul(bf.mul(inp[0], inp[1]), inp[2])
        return fn

    def clause2(fn):
        bf = fn.backend(ff)
        inp = bf.input(3)  # 3 inputs
        out = bf.output(1)  # 1 output
        out[0] = bf.add(bf.add(inp[0], inp[1]), inp[2])
        return fn

    def disj(disj, fn1, fn2):
        bf = disj.backend(ff)
        _ = bf.input(1)  # condition
        _ = bf.input(3)  # 3 inputs
        _ = bf.output(1)  # 1 output
        disj.plugin("galois_disjunction_v0", "switch", "strict", "1", fn1, "2", fn2)
        return disj

    # add two functions to circuit
    fn1 = clause1(circuit.func())
    fn2 = clause2(circuit.func())

    # add a disjunction to the circuit
    dj = disj(circuit.func(), fn1, fn2)

    # call disjunction
    a = bf.private(lambda: 2)
    b = bf.private(lambda: 3)
    c = bf.private(lambda: 4)

    cond = bf.private(lambda: 1)

    out = dj.call(cond, (a, b, c))

    # assert that the output was computed correctly
    bf.assert_eq(out[0], out[0].eval())

    # generate SIEVE-IR circuit
    for line in circuit.compile():
        print(line)

    # generate SIEVE-IR witness
    for line in circuit.witness(ff):
        print(line)
