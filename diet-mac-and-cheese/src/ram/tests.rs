use std::{
    io::{BufReader, BufWriter},
    net::{TcpListener, TcpStream},
    os::unix::net::UnixStream,
    time::{Duration, Instant},
};

use ocelot::svole::{
    LPN_EXTEND_LARGE, LPN_EXTEND_MEDIUM, LPN_EXTEND_SMALL, LPN_SETUP_LARGE, LPN_SETUP_MEDIUM,
    LPN_SETUP_SMALL,
};
use rand::{Rng, SeedableRng};
use scuttlebutt::{AesRng, Channel, SyncChannel, TrackChannel};
use swanky_field_f61p::F61p;

use std::env;
use std::iter;

use crate::{
    backend_trait::BackendT,
    ram::{prover::Prover, Bounded, RAM_SIZE, RAM_STEPS},
    DietMacAndCheeseProver, DietMacAndCheeseVerifier,
};

use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug)]
struct BenchResult {
    size: usize,
    steps: usize,
    ms: u128,
}

use super::verifier::Verifier;

const REPEATS: usize = 5;

#[test]
fn bench_net_ram() {
    let mut out: Vec<_> = vec![];

    for _ in 0..REPEATS {
        out.extend(
            iter::empty()
                .chain(test_size_ram(1 << 20))
                .chain(test_size_ram(1 << 18))
                .chain(test_size_ram(1 << 16))
                .chain(test_size_ram(1 << 14))
                .chain(test_size_ram(1 << 12)),
        );
    }

    match env::var("JSON_OUTPUT") {
        Ok(path) => {
            use std::io::Write;
            let mut file = std::fs::File::create(path).unwrap();
            let s = serde_json::to_string_pretty(&out).unwrap();
            file.write_all(s.as_bytes()).unwrap();
        }
        Err(_) => {
            for r in out {
                println!("{:?}", r);
            }
        }
    }
}

fn test_size_ram(size: usize) -> impl Iterator<Item = BenchResult> {
    iter::empty()
        .chain(test_size_steps_ram(1 << 23, size))
        .chain(test_size_steps_ram(1 << 22, size))
}

fn test_size_steps_ram(steps: usize, size: usize) -> impl Iterator<Item = BenchResult> {
    println!("running: SIZE={} STEPS={}", size, steps);
    let conn_addr = "127.0.0.1:7642";
    let listener = TcpListener::bind(conn_addr).unwrap();

    let handle = std::thread::spawn(move || {
        let rng = AesRng::from_seed(Default::default());
        let (sock, _addr) = listener.accept().unwrap();
        let reader = BufReader::new(sock.try_clone().unwrap());
        let writer = BufWriter::new(sock);
        let mut channel: SyncChannel<BufReader<TcpStream>, BufWriter<TcpStream>> =
            SyncChannel::new(reader, writer);

        let mut verifier: DietMacAndCheeseVerifier<F61p, F61p, _> = DietMacAndCheeseVerifier::init(
            &mut channel,
            rng,
            LPN_SETUP_MEDIUM,
            LPN_EXTEND_MEDIUM,
            false,
        )
        .unwrap();

        let mut ram =
            Verifier::<F61p, F61p, _, _, 1, 1, 3, 2, 4>::new(&mut verifier, Bounded::new(size));
        let addr = verifier.input_private(None).unwrap();
        for _i in 0..steps {
            let value = ram.remove(&mut verifier, &[addr]).unwrap();
            ram.insert(&mut verifier, &[addr], &value).unwrap();
        }
        ram.finalize(&mut verifier).unwrap();

        verifier.finalize().unwrap();
    });

    // run verifier
    let start;

    {
        let rng = AesRng::from_seed(Default::default());
        let stream_prover = TcpStream::connect(conn_addr).unwrap();
        let reader = BufReader::new(stream_prover.try_clone().unwrap());
        let writer = BufWriter::new(stream_prover);
        let mut channel = SyncChannel::new(reader, writer);

        let mut prover: DietMacAndCheeseProver<F61p, F61p, _> = DietMacAndCheeseProver::init(
            &mut channel,
            rng,
            LPN_SETUP_MEDIUM,
            LPN_EXTEND_MEDIUM,
            false,
        )
        .unwrap();

        // start the clock.
        // the OTs happen when first requested
        start = Instant::now();

        let mut ram =
            Prover::<F61p, F61p, _, _, 1, 1, 3, 2, 4>::new(&mut prover, Bounded::new(size));

        let addr = rand::random::<u32>() % (size as u32);
        let addr = F61p::try_from(addr as u128).unwrap();
        let addr = prover.input_private(Some(addr.into())).unwrap();

        for _ in 0..steps {
            let value = ram.remove(&mut prover, &[addr]).unwrap();
            ram.insert(&mut prover, &[addr], &value).unwrap();
        }
        ram.finalize(&mut prover).unwrap();

        prover.finalize().unwrap();
    }

    handle.join().unwrap();
    iter::once(BenchResult {
        size,
        steps,
        ms: start.elapsed().as_millis(),
    })
}

#[test]
fn test_ram() {
    let (sender, receiver) = UnixStream::pair().unwrap();

    let handle = std::thread::spawn(move || {
        let rng = AesRng::from_seed(Default::default());
        let reader = BufReader::new(sender.try_clone().unwrap());
        let writer = BufWriter::new(sender);
        let mut channel = Channel::new(reader, writer);

        let mut prover: DietMacAndCheeseProver<F61p, F61p, _> = DietMacAndCheeseProver::init(
            &mut channel,
            rng,
            LPN_SETUP_MEDIUM,
            LPN_EXTEND_MEDIUM,
            false,
        )
        .unwrap();

        for _ in 0..REPEATS {
            let mut ram =
                Prover::<F61p, F61p, _, _, 1, 1, 3, 2, 4>::new(&mut prover, Bounded::new(RAM_SIZE));

            for i in 0..RAM_STEPS {
                if i & 0xffff == 0 {
                    println!("{:x} {:x} {:x}", i, RAM_STEPS, RAM_SIZE);
                }
                let addr = rand::random::<u32>() % (RAM_SIZE as u32);
                let addr = F61p::try_from(addr as u128).unwrap();
                let addr = prover.input_private(Some(addr.into())).unwrap();

                let value = ram.remove(&mut prover, &[addr]).unwrap();

                ram.insert(&mut prover, &[addr], &value).unwrap();
            }
            ram.finalize(&mut prover).unwrap();
        }

        prover.finalize().unwrap();

        println!("done");
    });

    // run verifier
    {
        let rng = AesRng::from_seed(Default::default());
        let reader = BufReader::new(receiver.try_clone().unwrap());
        let writer = BufWriter::new(receiver);
        let mut channel = Channel::new(reader, writer);

        let mut verifier: DietMacAndCheeseVerifier<F61p, F61p, _> = DietMacAndCheeseVerifier::init(
            &mut channel,
            rng,
            LPN_SETUP_MEDIUM,
            LPN_EXTEND_MEDIUM,
            false,
        )
        .unwrap();
        for _ in 0..REPEATS {
            let mut ram = Verifier::<F61p, F61p, _, _, 1, 1, 3, 2, 4>::new(
                &mut verifier,
                Bounded::new(RAM_SIZE),
            );
            for _i in 0..RAM_STEPS {
                let addr = verifier.input_private(None).unwrap();
                let value = ram.remove(&mut verifier, &[addr]).unwrap();
                ram.insert(&mut verifier, &[addr], &value).unwrap();
            }
            ram.finalize(&mut verifier).unwrap();
        }
        verifier.finalize().unwrap();
    }

    // wait for prover
    handle.join().unwrap();
}
