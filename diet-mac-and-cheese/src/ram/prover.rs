use eyre::Result;

use std::{
    collections::{hash_map::Entry, HashMap},
    marker::PhantomData,
};

use scuttlebutt::{serialization::SequenceSerializer, AbstractChannel, AesRng};
use swanky_field::{FiniteField, IsSubFieldOf};

use std::iter;

use crate::{
    homcom::{FComProver, MacProver},
    ram::{collapse_vecs, perm::permutation},
    DietMacAndCheeseProver,
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

pub struct Prover<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel, M: MemorySpace<V>>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    space: M,
    _ph: PhantomData<(V, F, C, M)>,
    tx: blake3::Hasher,
    dim_chal: usize,
    memory: HashMap<Box<[V]>, Vec<V>>,
    // reads
    rds: Vec<Box<[MacProver<V, F>]>>,
    // writes
    wrs: Vec<Box<[MacProver<V, F>]>>,
}

fn commit_pub<V: IsSubFieldOf<T>, T: FiniteField>(
    values: impl Iterator<Item = V>,
) -> impl Iterator<Item = MacProver<V, T>>
where
    T::PrimeField: IsSubFieldOf<V>,
{
    values.map(|x| MacProver::new(x, T::ZERO))
}

impl<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel, M: MemorySpace<V>> Prover<V, F, C, M>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    fn dim(&self) -> usize {
        self.space.dim_addr() + self.space.dim_value() + self.dim_chal
    }

    pub fn new(space: M) -> Self {
        let bits = <V as FiniteField>::NumberOfBitsInBitDecomposition::to_usize();
        let dim_chal = (100 + bits - 1) / bits;
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
        prover: &mut DietMacAndCheeseProver<V, F, C>,
        addr: &[MacProver<V, F>],
    ) -> Box<[MacProver<V, F>]> {
        assert_eq!(addr.len(), self.space.dim_addr());
        let mut ch = TxChannel::new(prover.channel.clone(), &mut self.tx);

        // retrieve old value in memory (destructive)
        let val_addr: Box<[V]> = addr.iter().map(|v| v.value()).collect();
        let old = self
            .memory
            .remove(&val_addr)
            .unwrap_or_else(|| vec![V::default(); self.space.dim_value() + self.dim_chal]);

        debug_assert_eq!(old.len(), self.space.dim_value() + self.dim_chal);

        // concatenate addr || value || challenge
        // commit to the old value
        let flat: Box<[MacProver<V, F>]> = iter::empty()
            .chain(addr.iter().copied())
            .chain(old.into_iter().map(|x| {
                let m = prover.prover.input1(&mut ch, &mut prover.rng, x).unwrap();
                MacProver::new(x, m)
            }))
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
        prover: &mut DietMacAndCheeseProver<V, F, C>,
        addr: &[MacProver<V, F>],
        value: &[MacProver<V, F>],
    ) {
        debug_assert_eq!(addr.len(), self.space.dim_addr());
        debug_assert_eq!(value.len(), self.space.dim_value());

        // store value || challenge in local map
        match self.memory.entry(addr.iter().map(|m| m.value()).collect()) {
            Entry::Occupied(_) => {
                panic!("double entry, must remove entry first")
            }
            Entry::Vacant(entry) => {
                let mut ch = TxChannel::new(prover.channel.clone(), &mut self.tx);

                // sample challenge
                let flat: Box<_> = iter::empty()
                    .chain(addr.iter().copied())
                    .chain(value.iter().copied())
                    .chain(commit_pub((0..self.dim_chal).map(|_| ch.challenge())))
                    .collect();

                // add to local map
                entry.insert(
                    flat[self.space.dim_addr()..]
                        .iter()
                        .map(|m| m.value())
                        .collect(),
                );

                // add to list of writes
                self.wrs.push(flat);
            }
        }
    }

    pub fn finalize(mut self, prover: &mut DietMacAndCheeseProver<V, F, C>) {
        // insert initial values into the bag

        let mut pre: Box<[MacProver<V, F>]> =
            commit_pub(iter::repeat(V::default()).take(self.dim())).collect();

        // remove every address from the bag
        for addr in self.space.enumerate() {
            let addr: Vec<_> = commit_pub(addr.into_iter()).collect();

            pre[..self.space.dim_addr()].copy_from_slice(&addr);
            self.wrs.push(pre.clone());

            self.remove(prover, &addr);
        }

        // run permutation check
        assert_eq!(self.rds.len(), self.wrs.len());

        prover.channel.flush().unwrap();
        let chal_cmbn = prover.channel.read_serializable::<V>().unwrap();
        let chal_perm1 = prover.channel.read_serializable::<V>().unwrap();
        let chal_perm2 = prover.channel.read_serializable::<V>().unwrap();

        let wrs = collapse_vecs(prover, &self.wrs, chal_cmbn).unwrap();
        let rds = collapse_vecs(prover, &self.rds, chal_cmbn).unwrap();

        self.wrs.clear();
        self.wrs.shrink_to_fit();

        self.rds.clear();
        self.rds.shrink_to_fit();

        permutation(prover, chal_perm1, &wrs, &rds).unwrap();
        permutation(prover, chal_perm2, &wrs, &rds).unwrap();
    }
}
