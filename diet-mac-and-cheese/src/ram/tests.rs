use std::{
    io::{BufReader, BufWriter},
    os::unix::net::UnixStream,
};

use ocelot::svole::{LPN_EXTEND_MEDIUM, LPN_EXTEND_SMALL, LPN_SETUP_MEDIUM, LPN_SETUP_SMALL};
use rand::{Rng, SeedableRng};
use scuttlebutt::{AesRng, Channel};
use swanky_field_f61p::F61p;

use crate::{
    backend_trait::BackendT,
    ram::{prover::Prover, Bounded},
    DietMacAndCheeseProver, DietMacAndCheeseVerifier,
};

use super::verifier::Verifier;

const RAM_SIZE: usize = 10_000_000;
const RAM_STEPS: usize = 50_000_000;

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

        let mut ram = Prover::<F61p, F61p, _, _>::new(Bounded::new(RAM_SIZE));

        for i in 0..RAM_STEPS {
            if i & 0xffff == 0 {
                println!("{:x} {:x} {:x}", i, RAM_STEPS, RAM_SIZE);
            }
            let addr: usize = prover.rng.gen::<usize>() % RAM_SIZE;
            let addr = F61p::try_from(addr as u128).unwrap();
            let addr = prover.input_private(Some(addr.into())).unwrap();

            let value = ram.remove(&mut prover, &[addr]);

            ram.insert(&mut prover, &[addr], &value);
        }
        ram.finalize(&mut prover);
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

        let mut ram = Verifier::<F61p, F61p, _, _>::new(Bounded::new(RAM_SIZE));
        for _i in 0..RAM_STEPS {
            let addr = verifier.input_private(None).unwrap();
            let value = ram.remove(&mut verifier, &[addr]);
            ram.insert(&mut verifier, &[addr], &value)
        }
        ram.finalize(&mut verifier);
        verifier.finalize().unwrap();
    }

    // wait for prover
    handle.join().unwrap();
}
