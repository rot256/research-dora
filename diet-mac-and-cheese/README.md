# Dora Benchmarking

## Install Dependencies

The benchmarks can be run on Ubuntu (and likely Debian etc.).
On Ubuntu, all dependencies can be installed using `deps.sh` as follows:

```bash
./deps.sh
```

Which will also install a stable version of Rust.

## Benchmark Circuits

### Distribution of Clauses

We generate random circuits for benchmarking purposes, circuits are sampled as follows:

- We fix the number of inputs to each clause (at 100).
- We then sample addition/multiplication gates uniformly at random.
- The inputs of each gate are picked uniformly at random from all previously computed gate outputs.

### Regenerating The Circuits

First remove the old benchmark circuits / results:

```bash
rm -r benchmark-circ-f61-rev
rm -r benchmark-circ-f128-rev
rm -r benchmark-ram-f61-rev
```

Then run:

```bash
./gen_all.sh
```

## Run Benchmarks

Simply run:

```bash
./bench_all.sh
```

This will take a while (couple of days) to run...

Especially the `f128` results will take a while...

If you want to be notified of the progress you can use [ntfy.sh](https://ntfy.sh) as follows:

```bash
NOTIFY_ID=my-ntfy-id ./bench_all.sh
```

Which will send a notification whenever one of the benchmarks finish.

## Parse The Results

The results of the benchmark is the raw stdout/stderr of the `dietmc_0p` binary.
To parse these results into a single JSON file with all the results, run:

```bash
./parse_all.sh
```

To parse your own results, see `parse_all.sh` for an example of how to use `parse_all.py` to extract the results.
