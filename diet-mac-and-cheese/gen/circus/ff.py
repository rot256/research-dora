import random


class FieldElem:
    def __init__(self, field, value):
        self.field = field
        self.value = value

    def inv(self):
        return self.field._ff_inv(self)

    def __add__(self, other):
        return self.field._ff_add(self, other)

    def __mul__(self, other):
        return self.field._ff_mul(self, other)

    def __sub__(self, other):
        return self.field._ff_sub(self, other)

    def __div__(self, other):
        return self.field._ff_div(self, other)

    def __eq__(self, other):
        return self.value == other.value

    def __neg__(self):
        return self.field._ff_sub(self.field.new(0), self)

    def __repr__(self):
        return f"{self.value}"

    def __int__(self):
        return self.value


class Field:
    def __init__(self, size, name):
        self.size = size
        self.name = name

    def new(self, value):
        if isinstance(value, FieldElem):
            return value

        return FieldElem(self, value % self.size)

    def random(self):
        return FieldElem(self, random.randrange(0, self.size))

    def _ff_add(self, a, b):
        return FieldElem(self, (a.value + b.value) % self.size)

    def _ff_mul(self, a, b):
        return FieldElem(self, (a.value * b.value) % self.size)

    def _ff_sub(self, a, b):
        return FieldElem(self, (a.value - b.value) % self.size)

    def _ff_div(self, a, b):
        return FieldElem(self, a * b.inv())

    def _ff_inv(self, a):
        return FieldElem(self, pow(a.value, self.size - 2, self.size))

    def __eq__(self, other):
        return self.size == other.size

    def __hash__(self):
        return hash(self.size)

    def __repr__(self):
        return f"F_p({self.size})"
