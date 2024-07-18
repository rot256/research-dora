import os
import re
import sys
from fractions import Fraction
import glob
import json

delays = {}

max_branch = 0

for direc in sys.argv[1:]:
    with open(os.path.join(direc, 'meta.json'), 'r') as f:
        meta = json.loads(f.read())

    for file in os.listdir(direc):
        m = re.match('(\\d*)_verifier.out', file)

        if m is None:
            continue

        delay = int(m.group(1))

        with open(os.path.join(direc, file), 'r') as f:
            time = re.search('time circ exec: (\\d*\\.\\d*)s', f.read())
            if time is None:
                continue
            time = Fraction(time.group(1))

        cp = dict(meta)
        cp['per_sec'] = float(meta['branches'] / time)
        max_branch = max(meta['branches'], max_branch)
        try:
            delays[delay].append(cp)
        except KeyError:
            delays[delay] = [cp]



    print(meta)

import itertools

print(f'''
# Preliminary Benchmarks of Dora

## Note:

- We execute {max_branch} branches and take the average
- Batches of vOLE correlations are computed as needed (many rounds), hence performance, particular for small sizes, can "jump" by a significant amount:
  as another batch of vOLE correlations is required adding rounds and computation costs.
- Bandwidth is limited to 1Gbps.
- Diffrent network latencies are simulated using tc(8)
- The distribution of circuits is uniform: every gate is either addition/multiplication with probability 1/2, the toplogy of the circuit is random.
- As a result, the expected number of multiplications is half the number of gates.
- Every clause has 100 input wires and 100 output wires.
- All benchmarks run on `11th Gen Intel(R) Core(TM) i7-11800H @ 2.30GHz`
- The implementation is single threaded (one thread for the prover and one thread for the verifier)
''')

for delay, rs in sorted(delays.items()):
    opt_gates = set([e['gates'] for e in rs])
    opt_clauses = set([e['clauses'] for e in rs])

    table = {(a, b): None for (a, b) in itertools.product(opt_gates, opt_clauses)}

    for e in rs:
        table[e['gates'], e['clauses']] = e['per_sec']

    print(f'## {delay}ms Network Delay')
    print()
    print('Table shows number of branches taken per second for different number of clauses and gates per clause:')
    print()

    row = [ 'Gates Per Clause' ]
    for clauses in sorted(opt_clauses):
        row.append(f'{clauses} Clauses')
    print('|' + ' | '.join(row) + '|')
    print('|' + ' | '.join([' ---- ' for _ in row]) + '|')

    for gates in sorted(opt_gates):
        row = [ f'{gates}' ]
        for clauses in sorted(opt_clauses):
            entry = table[gates, clauses]
            if entry is None:
                entry = 0
            row.append(f'{entry:.2f}')
        print('|' + ' | '.join(row) + '|')

    print()
