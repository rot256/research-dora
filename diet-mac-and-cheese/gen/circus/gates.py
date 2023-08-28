def wrange(w):
    if isinstance(w, tuple):
        assert False, w
    elif isinstance(w, range):
        return f"${w.start} ... ${w.stop - 1}"
    else:
        return f"${w}"


class WitnessGate:
    def __init__(self, field, out, value):
        self.out = out
        self.field = field
        self.value = value

    def __repr__(self):
        return f"WitnessGate({self.out})"

    def convert(self, ff_id):
        f = ff_id[self.field]
        yield f"${self.out} <- @private({f});"

    def run(self, _circuit, wires):
        raise ValueError("not possible")


class AddGate:
    def __init__(self, field, out, lhs, rhs):
        self.out = out
        self.lhs = lhs
        self.rhs = rhs
        self.field = field

    def __repr__(self):
        return f"AddGate({self.out}, {self.lhs}, {self.rhs})"

    def convert(self, ff_id):
        yield f"${self.out} <- @add(${self.lhs}, ${self.rhs});"

    def run(self, _circuit, wires):
        wires[self.out] = wires[self.lhs] + wires[self.rhs]

class CopyGate:
    def __init__(self, field, dst, srcs):
        self.dst = dst
        self.srcs = srcs
        self.field = field

    def _src(self):
        for src in self.srcs:
            if isinstance(src, range):
                yield from src
            else:
                yield src

    def _dst(self):
        if isinstance(self.dst, range):
            yield from self.dst
        else:
            yield self.dst

    def convert(self, ff_id):
        # TODO: the SIEVE IR parser in diet-mac-and-ch
        for dst, src in zip(self._dst(), self._src()):
            yield f"${dst} <- ${src};"

        """
        srcs = [wrange(src) for src in gate.srcs]
        yield f'{wrange(gate.dst)} <- {", ".join(srcs)};'
        """

    def run(self, _circuit, wires):
        for dst, src in zip(self._dst(), self._src()):
            wires[dst] = wires[src]

    def __repr__(self):
        return f"CopyGate({self.dst} <- {self.srcs})"


class CallGate:
    def __init__(self, out, func, args):
        self.out = out
        self.func = func
        self.args = args

    def __repr__(self):
        return f"CallGate({self.out}, {self.func}, {self.args})"

    def run(self, circuit, wires):
        # lookup function
        fn = circuit.functs[self.func.name]

        # collect arguments
        args = []
        for arg in self.args:
            val = [wires[i] for i in arg]
            args.append(tuple(val))
        
        # call function
        out = fn.eval(*args)

        # assign outputs
        for ret, val in zip(self.out, out):
            assert len(ret) == len(val)
            for i, o in enumerate(ret.range): 
                wires[o] = val[i]

    def convert(self, ff_id):
        args = [wrange(arg) for arg in self.args]
        rets = [wrange(ret.range) for ret in self.out]
        yield f'{", ".join(rets)} <- @call({self.func}, {", ".join(args)});'

class MulGate:
    def __init__(self, field, out, lhs, rhs):
        self.out = out
        self.lhs = lhs
        self.rhs = rhs
        self.field = field

    def run(self, _circuit, wires):
        wires[self.out] = wires[self.lhs] * wires[self.rhs]

    def convert(self, ff_map):
        yield f"${self.out} <- @mul(${self.lhs}, ${self.rhs});"

    def __repr__(self):
        return f"MulGate({self.out}, {self.lhs}, {self.rhs})"


class MulConstGate:
    def __init__(self, field, out, wire, const):
        self.out = out
        self.wire = wire
        self.const = const
        self.field = field

    def run(self, _circuit, wires):
        wires[self.out] = wires[self.wire] * self.const

    def convert(self, ff_map):
        yield f"${self.out} <- @mulc(${self.wire}, <{self.const.value}>);"

    def __repr__(self):
        return f"MulConstGate({self.out} <- {self.const} * ({self.wire}) )"


class AddConstGate:
    def __init__(self, field, out, wire, const):
        self.out = out
        self.wire = wire
        self.const = const
        self.field = field

    def run(self, _circuit, wires):
        wires[self.out] = wires[self.wire] + self.const

    def convert(self, ff_map):
        yield f"${self.out} <- @addc(${self.wire}, <{self.const.value}>);"

    def __repr__(self):
        return f"AddConstGate({self.out} <- {self.const} * ({self.wire}))"


class AssertZeroGate:
    def __init__(self, field, wire):
        self.wire = wire
        self.field = field

    def __repr__(self):
        return f"AssertZeroGate({self.wire})"

    def convert(self, ff_id):
        f = ff_id[self.field]
        yield f"@assert_zero({f}: ${self.wire});"

    def run(self, _circuit, wires):
        pass