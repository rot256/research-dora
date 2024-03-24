INF = 1_000_000_000_000


class Namespace:
    """
    Wire namespace during compilation.

    Implements a single "heap allocation"
    of wires based on buckets (of different sizes)
    """

    def __init__(self, start=0):
        mst = range(start, INF)
        size = mst.stop - mst.start

        self.buckets = {size: set([mst])}
        self.buck_vals = [size]

        # neighbors of each free range
        self.nxts = {mst.start: mst}
        self.prvs = {mst.stop: mst}

        # sanity check
        # (allows us to check if freed ranges has been alloced prior)
        self.alloced = set()

        self.gates = []

        self.start = start
        self.top = start

    def _del(self, r):
        n = r.stop - r.start
        self.buckets[n].discard(r)

        if len(self.buckets[n]) == 0:
            self.buck_vals.remove(n)
            self.buck_vals.sort()
            del self.buckets[n]

        del self.prvs[r.stop]
        del self.nxts[r.start]

    def _add(self, r):
        # merge with next range
        try:
            nei = self.nxts[r.stop]
        except KeyError:
            pass
        else:
            self._del(nei)
            self._add(range(r.start, nei.stop))
            return

        # merge with previous range
        try:
            nei = self.prvs[r.start]
        except KeyError:
            pass
        else:
            self._del(nei)
            self._add(range(nei.start, r.stop))
            return

        # add range

        assert r.start not in self.nxts
        assert r.stop not in self.prvs

        self.nxts[r.start] = r
        self.prvs[r.stop] = r

        size = r.stop - r.start

        try:
            self.buckets[size].add(r)
        except KeyError:
            self.buckets[size] = set([r])
            self.buck_vals.append(size)
            self.buck_vals.sort()

    def _pop(self, n):
        r = self.buckets[n].pop()
        self._del(r)
        return r

    def _alloc_n(self, n):
        # find smallest bucket that fits
        b = self.buck_vals
        while len(b) > 1:
            r = len(b) // 2
            l = max(r - 1, 0)

            if b[l] == n:
                b = [b[l]]

            elif b[l] < n:
                if n <= b[r]:
                    b = [b[r]]
                else:
                    b = b[l+1:]

            elif b[l] > n:
                b = b[:l+1]
            
        assert len(b) == 1

        # perfect fit, yay!
        if b[0] == n:
            return self._pop(b[0])

        assert b[0] > n

        # split range
        r = self._pop(b[0])

        i1 = r.start
        i2 = r.start + n
        i3 = r.stop

        s1 = i2 - i1
        s2 = i3 - i2

        self._add(range(i2, i3))

        # keep maxium index alloced

        self.top = max(self.top, i2)

        return range(i1, i2)

    def alloc_n(self, n):
        """
        Allocate n consecutive wires
        """
        r = self._alloc_n(n)
        for w in r:
            self.alloced.add(w)
        return r

    def alloc(self):
        """
        Allocate a single wire
        """
        r = self.alloc_n(1)
        assert len(r) == 1
        return r.start

    def _free(self, w):
        if w < self.start:
            return
        assert w in self.alloced, f"freeing unalloced wire: {w}"
        self.alloced.remove(w)
        self._add(range(w, w + 1))

    def free(self, r):
        if isinstance(r, range):
            # blow up into individual wires
            # (which are then merged back into ranges)
            for w in r:
                self._free(w)
        else:
            self._free(r)

    def range(self):
        return range(self.start, self.top)

    def gate(self, gate):
        """
        Add to the stream of gates
        """
        self.gates.append(gate)
