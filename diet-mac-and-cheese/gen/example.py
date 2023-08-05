from circus import *

if __name__ == "__main__":
    # define a field
    ff = Field(340282366920938463463374607431768211297)

    # create a circuit and add a backend for the field ff
    circuit = Circuit()
    bf = circuit.backend(ff)

    # proves that a wire x is non-zero
    x = bf.private(lambda: ff.new(5))
    y = bf.private(lambda: x.eval().inv())
    o = bf.mul(x, y)
    bf.assert_eq(o, ff.new(1))

    # generate SIEVE-IR circuit
    for line in circuit.compile():
        print(line)

    # generate SIEVE-IR witness
    for line in circuit.witness(ff):
        print(line)
