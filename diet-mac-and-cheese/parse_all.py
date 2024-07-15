import re
import os
import sys
import json

from fractions import Fraction

def parse_all(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if re.match(r'result-(.*)\.json', file) is None:
                continue
            path = os.path.join(root, file)
            with open(path, 'r') as f:
                yield process_result(json.load(f))

def process_result(result):
    meta = result["meta"]
    net = result["network"]
    out = result["outputs"]["verifier"]

    if "ram" in meta:
        ram = True
    else:
        ram = False

    # extract running time from verifier
    assert "bytes sent:" in out
    assert "bytes recv:" in out
    assert "bytes total:" in out

    if ram:
        assert "time ram exec:" in out
    else:
        assert "time circ exec:" in out

    m = re.search(r'bytes sent: (\d+)', out)
    assert m is not None
    sent = int(m.group(1))

    m = re.search(r'bytes recv: (\d+)', out)
    assert m is not None
    recv = int(m.group(1))

    m = re.search(r'bytes total: (\d+)', out)
    assert m is not None
    total = int(m.group(1))

    assert sent + recv == total

    if ram:
        m = re.search(r'time ram exec: (\d+).(\d+)s', out)
    else:
        m = re.search(r'time circ exec: (\d+).(\d+)s', out)
    assert m is not None
    secs = Fraction(m.group(1) + "." + m.group(2))
    time_ms = round(secs * 1000)
    comm_bytes = total

    delay_ms = int(net["delay"])
    bandwith_mbits = int(net["mbits"])

    # sanity check
    bytes_per_sec = bandwith_mbits * 1000 * 1000 / 8
    max_comm = (time_ms / 1000) * bytes_per_sec
    assert comm_bytes <= max_comm

    if ram:
        steps = meta["ram_steps"]
        size = meta["ram_size"]

        return {
            "ram_steps": steps,
            "ram_size": size,
            "time_ms": time_ms,
            "comm_bytes": comm_bytes,
            "verifier_sent_bytes": sent,
            "verifier_recv_bytes": recv,
            "latency_ms": delay_ms,
            "bandwith_mbits": bandwith_mbits
        }

    else:
        gates = meta["gates"]
        steps = meta["branches"]
        clauses = meta["clauses"]

        return {
            "steps": steps,
            "clauses": clauses,
            "gates_per_clause": gates,
            "time_ms": time_ms,
            "comm_bytes": comm_bytes,
            "verifier_sent_bytes": sent,
            "verifier_recv_bytes": recv,
            "latency_ms": delay_ms,
            "bandwith_mbits": bandwith_mbits
        }

import glob

results = parse_all(sys.argv[1])
combined = list(results)
output = sys.argv[2]

with open(output, 'w') as f:
    json.dump(combined, f, indent=4)
