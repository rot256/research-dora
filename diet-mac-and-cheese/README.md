# Dora Benchmarking

## Install Dependencies

```bash
./deps.sh
```

## Regenerate Benchmark Circuits

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

If you want to be notified of the progress you can use [ntfy.sh](ntfy.sh) as follows:

```bash
NOTIFY_ID=my-ntfy-id ./bench_all.sh
```

## Parse The Results

To parse the raw outputs into nice JSON files, run:

```bash
./parse_all.sh
```
