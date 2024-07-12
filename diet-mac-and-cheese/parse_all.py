import re
import os
import sys
import json

def parse_all(directory):
    # Parse all the files in the directory
    per_bench = None
    results = []
    for bench in os.listdir(directory):
        found = []
        direc = os.path.join(directory, bench)
        for file in os.listdir(direc):
            # check if the file is a result file
            if re.match(r'result-(.*)\.json', file) is None:
                continue

            # load the results
            path = os.path.join(direc, file)
            with open(path, 'r') as f:
                found.append(json.load(f))

        assert per_bench is None or len(found) == per_bench
        per_bench = len(found)
        results += found

    return results

def process_result(result):
    meta = result["meta"]
    net = result["network"]
    out = result["outputs"]["verifier"]

    # extract running time from verifier
    assert "bytes sent:" in out
    assert "bytes recv:" in out
    assert "bytes total:" in out
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

    m = re.search(r'time circ exec: (\d+).(\d+)s', out)
    assert m is not None
    sc = int(m.group(1))
    ms = int(m.group(2))

    time_ms = sc * 1000 + ms
    comm_bytes = total

    delay_ms = int(net["delay"])
    bandwith_mbits = int(net["mbits"])

    # sanity check
    bytes_per_sec = bandwith_mbits * 1000 * 1000 / 8
    max_comm = (time_ms / 1000) * bytes_per_sec
    assert comm_bytes <= max_comm

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

results = parse_all(sys.argv[1])

combined = []
for res in results:
    combined.append(process_result(res))


print(json.dumps(combined, indent=4))
