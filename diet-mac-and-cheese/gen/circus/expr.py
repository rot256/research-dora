import circus.gates as gates

from circus.ff import FieldElem, Field
from circus.alloc import Namespace


class Wire:
    """
    A reference counted expression defining a single wire
    """

    def __init__(self, field, children=[]):
        self.refs = 0
        self.field = field

        # take a ref to all children
        for child in children:
            child.ref()

        self.children = children

    def alloc(self, ctx, into=None):
        self.ctx = ctx

        if into is None:
            self.alloced = ctx.alloc()
            self.label = self.alloced
        else:
            self.label = into

    def ref(self):
        self.refs += 1
        return self

    def unref(self):
        self.refs -= 1
        assert self.refs >= 0, "double unref"

        if self.refs == 0:
            # release the reference to all children
            for child in self.children:
                child.unref()

            # free the wire label
            try:
                self.ctx.free(self.alloced)
                del self.alloced
            except AttributeError:
                pass

            del self.ctx
            del self.label


class Range:
    """
    Cont. range of wires
    """

    def __init__(self, field, n):
        self.field = field
        self.n = n

    def __getitem__(self, i):
        assert i < self.n
        return Input(self, self.field, i, self)

    def __len__(self):
        return self.n


class Add(Wire):
    def __init__(self, field, a, b):
        Wire.__init__(self, field, [a, b])
        self.a = a
        self.b = b

    def __repr__(self):
        return f"Add({self.a}, {self.b})"

    def eval(self):
        try:
            return self.value
        except AttributeError:
            pass

        a = a.eval()
        b = b.eval()
        self.value = a + b
        return self.value

    def compile(self, ctx, into=None):
        try:
            return self.label
        except AttributeError:
            pass

        lhs = self.a.compile(ctx)
        rhs = self.b.compile(ctx)

        self.alloc(ctx, into)
        ctx.gate(gates.AddGate(self.field, self.label, lhs, rhs))
        return self.label


class Mul(Wire):
    def __init__(self, field, a, b):
        Wire.__init__(self, field, [a, b])
        self.a = a
        self.b = b

    def __repr__(self):
        return f"Mul({self.a}, {self.b})"

    def eval(self):
        try:
            return self.value
        except AttributeError:
            pass

        a = a.eval()
        b = b.eval()
        self.value = a * b
        return self.value

    def compile(self, ctx, into=None):
        try:
            return self.label
        except AttributeError:
            pass

        lhs = self.a.compile(ctx)
        rhs = self.b.compile(ctx)

        self.alloc(ctx, into)
        ctx.gate(gates.MulGate(self.field, self.label, lhs, rhs))
        return self.label


class MulConst(Wire):
    def __init__(self, field, wire, const):
        assert isinstance(wire, Wire), wire
        assert isinstance(const, FieldElem)

        Wire.__init__(self, field, [wire])
        self.wire = wire
        self.const = const

    def __repr__(self):
        return f"MulConst({self.wire}, {self.const})"

    def eval(self):
        try:
            return self.value
        except AttributeError:
            pass

        wire = self.wire.eval()
        self.value = wire * self.const
        return self.value

    def compile(self, ctx, into=None):
        try:
            return self.label
        except AttributeError:
            pass

        wire = self.wire.compile(ctx)

        self.alloc(ctx, into)
        ctx.gate(gates.MulConstGate(self.field, self.label, wire, self.const))
        return self.label


class AddConst(Wire):
    def __init__(self, field, wire, const):
        assert isinstance(wire, Wire)
        assert isinstance(const, FieldElem)

        Wire.__init__(self, field, [wire])
        self.wire = wire
        self.const = const

    def __repr__(self):
        return f"AddConst({self.wire}, {self.const})"

    def eval(self):
        try:
            return self.value
        except AttributeError:
            pass

        wire = self.wire.eval()
        self.value = wire + self.const
        return self.value

    def compile(self, ctx, into=None):
        try:
            return self.label
        except AttributeError:
            pass

        wire = self.wire.compile(ctx)

        self.alloc(ctx, into)
        ctx.gate(gates.AddConstGate(self.field, self.label, wire, self.const))
        return self.label


class AssertZero(Wire):
    def __init__(self, field, wire):
        self.wire = wire
        Wire.__init__(self, field, [self.wire])

    def compile(self, ctx, into=None):
        out = self.wire.compile(ctx)
        ctx.gate(gates.AssertZeroGate(self.field, out))
        self.wire.unref()


class Call(Wire):
    def __init__(self, func, args):
        assert isinstance(func, Func)

        children = []
        for arg in args:
            assert isinstance(arg, Wire) or isinstance(arg, tuple)
            if isinstance(arg, tuple):
                for a in arg:
                    assert isinstance(a, Wire)
                    children.append(a)
            else:
                children.append(arg)

        # allocate outputs
        self.rets = tuple(
            [Rets(self, output.field, output.n) for output in func.outputs]
        )
        self.func = func
        self.args = args
        self.value = False
        self.compiled = False
        Wire.__init__(self, None, children)

    def eval(self):
        if self.value:
            return

        # evaluate all arguments
        args = []
        for arg in self.args:
            if isinstance(arg, tuple):
                args.append(tuple([a.eval() for a in arg]))
            else:
                args.append(arg.eval())

        # call function
        rets = self.func.eval(*args)

        # assign outputs
        for i, ret in enumerate(rets):
            self.rets[i].value = ret

        self.value = True

    def compile(self, ctx):
        if self.compiled:
            return self.refs

        arg_wires = []
        for arg in self.args:
            if isinstance(arg, tuple):
                assert len(arg) > 0

                # compile each wire
                inp = [inp.compile(ctx) for inp in arg]

                # check if already cont
                # (TODO: allocate cont. when compiling)
                if inp == sorted(inp):
                    arg_wires.append(range(inp[0], inp[-1] + 1))
                    continue

                # otherwise allocate cont. range and copy
                out = ctx.alloc_n(len(inp))
                ctx.gate(gates.CopyGate(arg[0].field, out, inp))

                # use cont. wires
                arg_wires.append(out)
            else:
                arg_wires.append(arg.compile(ctx))

        # deref children
        for child in self.children:
            child.unref()

        # allocate outputs
        self.ctx = ctx
        for ret in self.rets:
            ret.range = ctx.alloc_n(ret.n)

        ctx.gate(gates.CallGate(self.rets, self.func, arg_wires))
        self.compiled = True
        return self.refs

    def unref(self):
        assert False, "unref call"


class Witness(Wire):
    def __init__(self, field, fn):
        self.fn = fn
        Wire.__init__(self, field)

    def eval(self):
        try:
            return self.value
        except AttributeError:
            pass

        self.value = self.field.new(self.fn())
        return self.value

    def compile(self, ctx, into=None):
        try:
            return self.label
        except AttributeError:
            pass

        self.alloc(ctx, into)
        ctx.gate(gates.WitnessGate(self.field, self.label, self.eval()))
        return self.label


class Input(Wire):
    """
    A wire in a cont. range (input/output etc.)

    All the wires in have the same lifetime
    (as they are defined together, e.g. as the output of a call)
    """

    def __init__(self, arg, field, idx, resolve=None):
        Wire.__init__(self, field)
        self.arg = arg
        self.idx = idx
        self.resolve = resolve

    def compile(self, ctx, into=None):
        try:
            return self.label
        except AttributeError:
            pass

        self.ctx = ctx
        if self.resolve is not None:
            self.resolve.compile(ctx)

        self.label = self.arg.range.start + self.idx
        return self.label

    def eval(self):
        return self.arg.eval()[self.idx]

    def __repr__(self):
        return f"I({self.field}, {self.idx})"


class Rets(Range):
    """
    Return range from function
    """

    def __init__(self, call, field, n):
        self.call = call
        Range.__init__(self, field, n)

    def compile(self, ctx, into=None):
        self.call.compile(ctx)

    def eval(self):
        try:
            return self.value
        except AttributeError:
            self.call.eval()
            return self.value


class Arg(Range):
    """
    Unassignable wire range
    """

    def __init__(self, field, n):
        self.field = field
        Range.__init__(self, field, n)

    def __getitem__(self, i):
        assert i < self.n, f"argument index out of range: {i} >= {self.n}"
        return Input(self, self.field, i)


class Return(Range):
    """
    Unreadable wire range
    """

    def __init__(self, field, n):
        self.assign = [None] * n
        Range.__init__(self, field, n)

    def __setitem__(self, i, wire):
        assert self.assign[i] is None, "double assigned return value"
        wire.ref()
        self.assign[i] = wire


class Backend:
    """
    Field backend for a circuit
    """

    def __init__(self, circuit, field):
        self.circuit = circuit
        self.field = field
        self.roots = []
        self.gates = []

        self.outputs = []
        self.inputs = []

    def private(self, fn):
        return Witness(self.field, fn)

    def add(self, a, b):
        if isinstance(a, FieldElem) and isinstance(b, FieldElem):
            return a + b

        if isinstance(a, FieldElem):
            return AddConst(self.field, b, a)

        if isinstance(b, FieldElem):
            return AddConst(self.field, a, b)

        return Add(self.field, a, b)

    def sub(self, a, b):
        mn = self.mul(b, self.field.new(-1))
        return self.add(a, mn)

    def mul(self, a, b):
        if isinstance(a, FieldElem) and isinstance(b, FieldElem):
            return a * b

        if isinstance(a, FieldElem):
            return MulConst(self.field, b, a)

        if isinstance(b, FieldElem):
            return MulConst(self.field, a, b)

        return Mul(self.field, a, b)

    def assert_eq(self, a, b):
        self.assert_zero(self.sub(a, b))

    def assert_zero(self, wire):
        self.roots.append(AssertZero(self.field, wire))

    def live(self, wire):
        self.roots.append(wire)

    def compile(self, ctx):
        for wire in self.roots:
            wire.compile(ctx)

    def gate(self, gate):
        self.gates.append(gate)

    def input(self, n):
        assert isinstance(self.circuit, Func)
        return self.circuit.input(self.field, n)

    def output(self, n):
        assert isinstance(self.circuit, Func)
        return self.circuit.output(self.field, n)


def exp_range(w):
    if isinstance(w, tuple):
        assert False
        s, e = w
        return range(s, e + 1)
    elif isinstance(w, range):
        return w
    else:
        return range(w, w + 1)


def convert(gates, ff_id):
    for gate in gates:
        yield from gate.convert(ff_id)


class Func:
    def __init__(self, circuit, name):
        self.name = name
        self.public = []
        self.roots = []
        self.backends = {}
        self.inputs = []
        self.outputs = []
        self.circuit = circuit
        self.is_plugin = False

    def eval(self, *args):
        # check for known plugins
        if self.is_plugin:
            if self.plugin_name == "galois_disjunction_v0":
                cond = args[0]

                assert self.plugin_args[0] == "switch"
                assert self.plugin_args[1] == "strict"

                dispatch = iter(self.plugin_args[2:])

                # lookup active clause
                while 1:
                    cn = int(next(dispatch))
                    fn = next(dispatch)
                    if cn == cond.value:
                        return fn.eval(*args[1:])

            else:
                assert False, "unknown plugin"

        # assign arguments
        wires = {}
        for inp, arg in zip(self.inputs, args):
            if isinstance(arg, tuple):
                assert inp.n == len(arg)
                for i, w in zip(inp.range, arg):
                    wires[i] = w
            else:
                assert inp.n == 1, f"takes tuple of arguments {inp.n} args"
                wires[inp.range[0]] = arg

        # evaluate all gates in compiled function
        for gate in self.ctx.gates:
            gate.run(self.circuit, wires)

        # return outputs
        rets = []
        for out in self.outputs:
            rets.append(tuple([wires[i] for i in out.range]))

        return tuple(rets)

    def call(self, *args):
        # do a type check on the arguments
        call = Call(self, args)
        if len(call.rets) == 1:
            return call.rets[0]
        return call.rets

    def input(self, ff, n):
        assert ff in self.backends
        arg = Arg(ff, n)
        self.inputs.append(arg)
        return arg

    def output(self, ff, n):
        assert ff in self.backends
        arg = Return(ff, n)
        self.outputs.append(arg)
        return arg

    def backend(self, ff):
        assert ff not in self.backends
        bf = Backend(self, ff)
        self.backends[ff] = bf
        return bf

    def plugin(self, name, *args):
        self.is_plugin = True
        self.plugin_name = name
        self.plugin_args = args
        assert len(self.roots) == 0

    def _compile(self):
        ff_id = self.circuit.ff_id

        try:
            return self.ctx
        except AttributeError:
            pass

        off = 0

        out = []
        for val in self.outputs:
            val.range = range(off, off + val.n)
            off += val.n

        ins = []
        for val in self.inputs:
            val.range = range(off, off + val.n)
            off += val.n

        ctx = Namespace(off)

        if self.is_plugin:
            return

        # compile asserts
        for ff in self.backends.values():
            ff.compile(ctx)

        # assert all values assigned
        for out in self.outputs:
            assert isinstance(out, Return)

            nxt = iter(out.range)
            for wire in out.assign:
                assert wire is not None, "unassigned output in function"
                tbl = next(nxt)
                lbl = wire.compile(ctx, tbl)
                if lbl != tbl:
                    ctx.gate(
                        gates.CopyGate(
                            wire.field,
                            tbl,
                            [lbl],
                        )
                    )
                wire.unref()

        self.ctx = ctx
        return self.ctx

    def compile(self):
        ctx = self._compile()

        ff_id = self.circuit.ff_id

        out = []
        for val in self.outputs:
            out.append(f"{ff_id[val.field]}:{val.n}")

        ins = []
        for val in self.inputs:
            ins.append(f"{ff_id[val.field]}:{val.n}")

        yield f'@function({self.name}, @out: {",".join(out)}, @in: {",".join(ins)})'

        # handle plugin body

        if self.is_plugin:
            yield f"  @plugin("
            yield f"    {self.plugin_name},"
            for i, arg in enumerate(self.plugin_args):
                if i == len(self.plugin_args) - 1:
                    yield f"    {arg}"
                else:
                    yield f"    {arg},"
            yield "  );"
            return

        # compile gates body

        for gate in convert(ctx.gates, ff_id):
            yield f"  {gate}"

        yield f"@end"

    def __repr__(self):
        return self.name


class Circuit:
    def __init__(self):
        self.ff_id = {}
        self.roots = []
        self.functs = {}
        self.backends = {}
        self.witnesses = []

    def backend(self, ff):
        assert ff not in self.backends
        bf = Backend(self, ff)
        self.backends[ff] = bf
        self.ff_id[ff] = len(self.ff_id)
        return bf

    def func(self, define, name=None):
        if name is None:
            name = f"f{len(self.functs)}"
        assert name not in self.functs
        
        # allocate function
        fn = Func(self, name)
        self.functs[name] = fn

        # define function (populates body)
        define(fn)

        # compile function
        fn._compile()
        return fn

    def extract_witnesses(self):
        try:
            self.ctx
        except AttributeError:
            self.compile()

        wit = {}
        for gate in self.ctx.gates:
            if isinstance(gate, gates.WitnessGate):
                try:
                    wit[gate.field].append(gate.value)
                except KeyError:
                    wit[gate.field] = [gate.value]
        return wit

    def witness(self, ff):
        try:
            self.wit
        except AttributeError:
            self.wit = self.extract_witnesses()

        yield "version 2.0.0;"
        yield "private_input;"
        yield f"@type field {ff.size};"
        yield "@begin"
        for e in self.wit[ff]:
            yield f"  <{e.value}>;"
        yield "@end"

    def compile(self):
        try:
            return self.ctx
        except AttributeError:
            self.ctx = Namespace()

        for ff in self.backends.values():
            ff.compile(self.ctx)

        yield "version 2.0.0;"
        yield "circuit;"

        yield ""
        yield '// Circuit generated by the "Circus" Expression Compiler'
        yield ""

        for ff in self.backends:
            yield f"@type field {ff.size};"

        yield "@begin"
        for func in self.functs.values():
            for gate in func.compile():
                yield f"  {gate}"

        for _ff, idx in self.ff_id.items():
            yield f"  @new({idx}: {gates.wrange(self.ctx.range())});"

        for gate in convert(self.ctx.gates, self.ff_id):
            yield f"  {gate}"

        yield "@end"
