use eyre::Result;

use std::{
    collections::{hash_map::Entry, HashMap},
    marker::PhantomData,
};

use rustc_hash::FxHashMap;

use scuttlebutt::{serialization::SequenceSerializer, AbstractChannel, AesRng};
use swanky_field::{FiniteField, IsSubFieldOf};

use std::iter;

use crate::{
    homcom::{FComProver, MacProver},
    ram::{collapse_vecs, perm::permutation, PRE_ALLOC_MEM, PRE_ALLOC_STEPS},
    DietMacAndCheeseProver,
};

use generic_array::typenum::Unsigned;

use super::{tx::TxChannel, MemorySpace};

trait MemParams {
    const DIM_ADDR: usize;
    const DIM_VALUE: usize;
}

pub struct Prover<
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
    _ph: PhantomData<(V, F, C, M)>,
    ch: TxChannel<C>,
    memory: FxHashMap<[V; SIZE_ADDR], [V; SIZE_STORE]>,
    // reads
    rds: Vec<[MacProver<V, F>; SIZE_DIM]>,
    // writes
    wrs: Vec<[MacProver<V, F>; SIZE_DIM]>,
}

#[inline(always)]
fn commit_pub<V: IsSubFieldOf<T>, T: FiniteField, const N: usize>(
    values: &[V; N],
) -> [MacProver<V, T>; N]
where
    T::PrimeField: IsSubFieldOf<V>,
{
    values.map(|x| MacProver::new(x, T::ZERO))
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
    > Prover<V, F, C, M, SIZE_ADDR, SIZE_VALUE, SIZE_STORE, SIZE_CHAL, SIZE_DIM>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    pub fn new(prover: &mut DietMacAndCheeseProver<V, F, C>, space: M) -> Self {
        Self {
            space,
            rds: Vec::with_capacity(PRE_ALLOC_MEM + PRE_ALLOC_STEPS),
            wrs: Vec::with_capacity(PRE_ALLOC_MEM + PRE_ALLOC_STEPS),
            memory: Default::default(),
            ch: TxChannel::new(prover.channel.clone(), Default::default()),
            _ph: Default::default(),
        }
    }

    /// Read is a destructive operation which "r"
    pub fn remove(
        &mut self,
        prover: &mut DietMacAndCheeseProver<V, F, C>,
        addr: &[MacProver<V, F>; SIZE_ADDR],
    ) -> [MacProver<V, F>; SIZE_VALUE] {
        // retrieve old value in memory (destructive)
        let val_addr = addr.map(|e| e.value());
        let old = self
            .memory
            .remove(&val_addr)
            .unwrap_or_else(|| [V::default(); SIZE_STORE]);

        // concatenate addr || value || challenge
        // commit to the old value
        let mut flat: [MacProver<V, F>; SIZE_DIM] = [Default::default(); SIZE_DIM];

        for (i, elem) in iter::empty()
            .chain(addr.iter().copied())
            .chain(old.into_iter().map(|x| {
                let m = prover
                    .prover
                    .input1(&mut self.ch, &mut prover.rng, x)
                    .unwrap();
                MacProver::new(x, m)
            }))
            .enumerate()
        {
            flat[i] = elem;
        }

        // add to reads
        self.rds.push(flat);
        flat[SIZE_ADDR..SIZE_ADDR + SIZE_VALUE].try_into().unwrap()
    }

    pub fn insert(
        &mut self,
        prover: &mut DietMacAndCheeseProver<V, F, C>,
        addr: &[MacProver<V, F>; SIZE_ADDR],
        value: &[MacProver<V, F>; SIZE_VALUE],
    ) {
        debug_assert_eq!(addr.len(), self.space.dim_addr());
        debug_assert_eq!(value.len(), self.space.dim_value());

        // store value || challenge in local map
        match self.memory.entry(addr.map(|m| m.value())) {
            Entry::Occupied(_) => {
                panic!("double entry, must remove entry first")
            }
            Entry::Vacant(entry) => {
                // sample challenge
                let mut flat: [MacProver<V, F>; SIZE_DIM] = [Default::default(); SIZE_DIM];
                for (i, elem) in iter::empty()
                    .chain(addr.iter().copied())
                    .chain(value.iter().copied())
                    .chain(commit_pub(&self.ch.challenge::<_, SIZE_CHAL>()))
                    .enumerate()
                {
                    flat[i] = elem;
                }

                // add to local map
                let store: &[_; SIZE_STORE] = flat[self.space.dim_addr()..].try_into().unwrap();
                entry.insert(store.map(|m| m.value()));

                // add to list of writes
                self.wrs.push(flat);
            }
        }
    }

    pub fn finalize(mut self, prover: &mut DietMacAndCheeseProver<V, F, C>) {
        // insert initial values into the bag
        let mut pre: [MacProver<V, F>; SIZE_DIM] = commit_pub(&[V::default(); SIZE_DIM]);

        // remove every address from the bag
        for addr in self.space.enumerate() {
            let addr = commit_pub(&addr.try_into().unwrap());

            pre[..self.space.dim_addr()].copy_from_slice(&addr);
            self.wrs.push(pre.clone());

            self.remove(prover, &addr);
        }

        // run permutation check
        assert_eq!(self.rds.len(), self.wrs.len());

        prover.channel.flush().unwrap();
        let chal_cmbn = prover.channel.read_serializable::<V>().unwrap();
        let chal_perm1 = prover.channel.read_serializable::<V>().unwrap();

        println!("collapse 1");
        let wrs = collapse_vecs(prover, &self.wrs, chal_cmbn).unwrap();

        println!("collapse 2");
        let rds = collapse_vecs(prover, &self.rds, chal_cmbn).unwrap();

        println!("clear");
        self.wrs.clear();
        self.wrs.shrink_to_fit();

        self.rds.clear();
        self.rds.shrink_to_fit();

        println!("permutation");
        permutation(prover, chal_perm1, &wrs, &rds).unwrap();
    }
}
