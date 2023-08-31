use eyre::Result;

use std::{
    collections::{hash_map::Entry, HashMap},
    marker::PhantomData,
};

use scuttlebutt::{AbstractChannel, AesRng};
use swanky_field::{FiniteField, IsSubFieldOf};

use std::iter;

use crate::{
    backend_trait::BackendT,
    homcom::{FComProver, MacProver, MacVerifier},
    ram::{collapse_vecs, perm::permutation},
    DietMacAndCheeseProver, DietMacAndCheeseVerifier,
};

use generic_array::typenum::Unsigned;

use super::{tx::TxChannel, MemorySpace};

// Low-level commit to vector
// (allows control of the channel for Fiat-Shamir)
//
// Idealy there would be a nicer way to do this.
fn commit_vec<'a, V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel>(
    backend: &mut FComProver<V, F>,
    channel: &mut C,
    rng: &mut AesRng,
    sec: impl IntoIterator<Item = V>, // secret values
    len: usize,                       // padded length
) -> Result<impl Iterator<Item = MacProver<V, F>>>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    // commit to remaining (padded)
    let mut pad = Vec::with_capacity(len);
    pad.extend(sec.into_iter().chain(iter::repeat(V::ZERO)).take(len));

    // mac vector
    let tag = backend.input(channel, rng, &pad)?;

    // combine
    Ok(tag
        .into_iter()
        .zip(pad.into_iter())
        .map(|(t, v)| MacProver::new(v, t)))
}

pub struct Verifier<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel, M: MemorySpace<V>>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    space: M,
    _ph: PhantomData<(V, F, C, M)>,
    tx: blake3::Hasher,
    dim_chal: usize,
    memory: HashMap<Box<[V]>, Vec<V>>,
    // reads
    rds: Vec<Box<[MacVerifier<F>]>>,
    // writes
    wrs: Vec<Box<[MacVerifier<F>]>>,
}

impl<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel, M: MemorySpace<V>> Verifier<V, F, C, M>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    fn dim(&self) -> usize {
        self.space.dim_addr() + self.space.dim_value() + self.dim_chal
    }

    pub fn new(space: M) -> Self {
        let bits = <V as FiniteField>::NumberOfBitsInBitDecomposition::to_usize();
        let dim_chal = (100 + bits - 1) / bits;
        println!("dim_chal: {}", dim_chal);
        Self {
            space,
            dim_chal,
            rds: Vec::with_capacity(60_000_000),
            wrs: Vec::with_capacity(60_000_000),
            memory: Default::default(),
            tx: Default::default(),
            _ph: Default::default(),
        }
    }

    /// Read is a destructive operation which "r"
    pub fn remove(
        &mut self,
        verifier: &mut DietMacAndCheeseVerifier<V, F, C>,
        addr: &[MacVerifier<F>],
    ) -> Box<[MacVerifier<F>]> {
        debug_assert_eq!(addr.len(), self.space.dim_addr());
        let mut ch = TxChannel::new(verifier.channel.clone(), &mut self.tx);

        // concatenate addr || value || challenge
        // commit to the old value
        let flat: Box<[MacVerifier<F>]> = iter::empty()
            .chain(addr.iter().copied())
            .chain(
                verifier
                    .verifier
                    .input(
                        &mut ch,
                        &mut verifier.rng,
                        self.space.dim_value() + self.dim_chal,
                    )
                    .unwrap(),
            )
            .collect();
        debug_assert_eq!(flat.len(), self.dim());

        // extract value
        let value: Box<[_]> =
            flat[self.space.dim_addr()..self.space.dim_addr() + self.space.dim_value()].into();
        debug_assert_eq!(value.len(), self.space.dim_value());

        // add to reads
        self.rds.push(flat);
        value
    }

    pub fn insert(
        &mut self,
        verifier: &mut DietMacAndCheeseVerifier<V, F, C>,
        addr: &[MacVerifier<F>],
        value: &[MacVerifier<F>],
    ) {
        debug_assert_eq!(addr.len(), self.space.dim_addr());
        debug_assert_eq!(value.len(), self.space.dim_value());

        let mut ch = TxChannel::new(verifier.channel.clone(), &mut self.tx);

        // sample challenge
        let flat: Box<_> = iter::empty()
            .chain(addr.iter().copied())
            .chain(value.iter().copied())
            .chain((0..self.dim_chal).map(|_| verifier.input_public(ch.challenge()).unwrap()))
            .collect();

        // add to list of writes
        self.wrs.push(flat);
    }

    pub fn finalize(mut self, verifier: &mut DietMacAndCheeseVerifier<V, F, C>) {
        let mut pre: Box<[_]> = iter::repeat(V::default())
            .take(self.dim())
            .map(|x| verifier.input_public(x).unwrap())
            .collect();

        // remove every address from the bag
        for addr in self.space.enumerate() {
            let addr: Vec<_> = addr
                .into_iter()
                .map(|x| verifier.input_public(x).unwrap())
                .collect();

            pre[..self.space.dim_addr()].copy_from_slice(&addr);
            self.wrs.push(pre.clone());

            self.remove(verifier, &addr);
        }

        let chal_cmbn = V::random(&mut verifier.rng);
        let chal_perm1 = V::random(&mut verifier.rng);
        let chal_perm2 = V::random(&mut verifier.rng);
        verifier.channel.write_serializable(&chal_cmbn).unwrap();
        verifier.channel.write_serializable(&chal_perm1).unwrap();
        verifier.channel.write_serializable(&chal_perm2).unwrap();
        verifier.channel.flush().unwrap();

        let wrs = collapse_vecs(verifier, &self.wrs, chal_cmbn).unwrap();
        let rds = collapse_vecs(verifier, &self.rds, chal_cmbn).unwrap();

        self.wrs.clear();
        self.wrs.shrink_to_fit();

        self.rds.clear();
        self.rds.shrink_to_fit();

        // run permutation check
        assert_eq!(self.rds.len(), self.wrs.len());

        permutation(verifier, chal_perm1, &wrs, &rds).unwrap();
        permutation(verifier, chal_perm2, &wrs, &rds).unwrap();
    }
}
