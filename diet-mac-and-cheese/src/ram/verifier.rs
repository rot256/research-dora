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
    DietMacAndCheeseVerifier,
};

use super::{tx::TxChannel, MemorySpace, PRE_ALLOC_MEM, PRE_ALLOC_STEPS};

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

pub struct Verifier<
    V: IsSubFieldOf<F>,
    F: FiniteField,
    C: AbstractChannel,
    M: MemorySpace<V>,
    const SIZE_ADDR: usize,
    const SIZE_VALUE: usize,
    const SIZE_STORE: usize,
    const SIZE_CHAL: usize,
    const SIZE_DIM: usize,
> where
    F::PrimeField: IsSubFieldOf<V>,
{
    space: M,
    ch: TxChannel<C>,
    _ph: PhantomData<(V, F, C, M)>,
    tx: blake3::Hasher,
    // reads
    rds: Vec<[MacVerifier<F>; SIZE_DIM]>,
    // writes
    wrs: Vec<[MacVerifier<F>; SIZE_DIM]>,
}

impl<
        V: IsSubFieldOf<F>,
        F: FiniteField,
        C: AbstractChannel,
        M: MemorySpace<V>,
        const SIZE_ADDR: usize,
        const SIZE_VALUE: usize,
        const SIZE_STORE: usize,
        const SIZE_CHAL: usize,
        const SIZE_DIM: usize,
    > Verifier<V, F, C, M, SIZE_ADDR, SIZE_VALUE, SIZE_STORE, SIZE_CHAL, SIZE_DIM>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    pub fn new(verifier: &mut DietMacAndCheeseVerifier<V, F, C>, space: M) -> Self {
        Self {
            space,
            ch: TxChannel::new(verifier.channel.clone(), Default::default()),
            rds: Vec::with_capacity(PRE_ALLOC_MEM + PRE_ALLOC_STEPS),
            wrs: Vec::with_capacity(PRE_ALLOC_MEM + PRE_ALLOC_STEPS),
            tx: Default::default(),
            _ph: Default::default(),
        }
    }

    /// Read is a destructive operation which "r"
    pub fn remove(
        &mut self,
        verifier: &mut DietMacAndCheeseVerifier<V, F, C>,
        addr: &[MacVerifier<F>],
    ) -> Result<[MacVerifier<F>; SIZE_VALUE]> {
        debug_assert_eq!(addr.len(), M::DIM_ADDR);

        // concatenate addr || value || challenge
        // commit to the old value
        let mut flat = [Default::default(); SIZE_DIM];

        for (i, elem) in iter::empty()
            .chain(addr.iter().copied())
            .chain(
                verifier
                    .verifier
                    .input(&mut self.ch, &mut verifier.rng, SIZE_VALUE + SIZE_CHAL)
                    .unwrap(),
            )
            .enumerate()
        {
            flat[i] = elem;
        }

        // add to reads
        self.rds.push(flat);
        Ok(flat[SIZE_ADDR..SIZE_ADDR + SIZE_VALUE].try_into().unwrap())
    }

    pub fn insert(
        &mut self,
        verifier: &mut DietMacAndCheeseVerifier<V, F, C>,
        addr: &[MacVerifier<F>; SIZE_ADDR],
        value: &[MacVerifier<F>; SIZE_VALUE],
    ) -> Result<()> {
        debug_assert_eq!(addr.len(), M::DIM_ADDR);
        debug_assert_eq!(value.len(), M::DIM_VALUE);

        // sample challenge
        let mut flat = [Default::default(); SIZE_DIM];
        for (i, elem) in iter::empty()
            .chain(*addr)
            .chain(*value)
            .chain(
                self.ch
                    .challenge::<_, SIZE_CHAL>()
                    .map(|x| verifier.input_public(x).unwrap()),
            )
            .enumerate()
        {
            flat[i] = elem;
        }

        // add to list of writes
        self.wrs.push(flat);
        Ok(())
    }

    pub fn finalize(mut self, verifier: &mut DietMacAndCheeseVerifier<V, F, C>) -> Result<()> {
        // insert initial values into the bag
        let mut pre = [V::default(); SIZE_DIM].map(|x| verifier.input_public(x).unwrap());

        // remove every address from the bag
        for addr in self.space.enumerate() {
            let addr: Vec<_> = addr
                .as_ref()
                .iter()
                .map(|x| verifier.input_public(*x).unwrap())
                .collect();

            pre[..M::DIM_ADDR].copy_from_slice(&addr);
            self.wrs.push(pre.clone());
            self.remove(verifier, &addr)?;
        }

        let chal_cmbn = V::random(&mut verifier.rng);
        let chal_perm1 = V::random(&mut verifier.rng);
        verifier.channel.write_serializable(&chal_cmbn)?;
        verifier.channel.write_serializable(&chal_perm1)?;
        verifier.channel.flush()?;

        let wrs = collapse_vecs(verifier, &self.wrs, chal_cmbn)?;
        let rds = collapse_vecs(verifier, &self.rds, chal_cmbn)?;

        self.wrs.clear();
        self.wrs.shrink_to_fit();

        self.rds.clear();
        self.rds.shrink_to_fit();

        // run permutation check
        assert_eq!(self.rds.len(), self.wrs.len());
        permutation(verifier, chal_perm1, &wrs, &rds)
    }
}
