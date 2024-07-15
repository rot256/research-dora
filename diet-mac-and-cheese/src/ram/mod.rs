use std::marker::PhantomData;

use eyre::Result;
use scuttlebutt::AbstractChannel;
use swanky_field::{FiniteField, IsSubFieldOf};

use crate::{
    backend_trait::BackendT,
    homcom::{MacProver, MacVerifier},
    DietMacAndCheeseProver, DietMacAndCheeseVerifier,
};

mod perm;
mod prover;
mod tests;
mod tx;
mod verifier;

pub use prover::Prover;
pub use verifier::Verifier;

const SEP: &[u8] = b"FS_RAM";

// Expected memory size/number of steps.
// Used to compute capacities of large vectors
// (affects efficiency not correctness)
const RAM_SIZE: usize = 1 << 20;
const RAM_STEPS: usize = 1 << 24;

const PRE_ALLOC_MEM: usize = RAM_SIZE;
const PRE_ALLOC_STEPS: usize = RAM_STEPS + RAM_SIZE;

pub fn combine<'a, B: BackendT>(
    backend: &'a mut B,
    mut elems: impl Iterator<Item = &'a B::Wire>,
    x: B::FieldElement,
) -> Result<B::Wire> {
    let mut y: B::Wire = backend.copy(elems.next().unwrap())?;
    for c in elems {
        y = backend.mul_constant(&y, x)?;
        y = backend.add(&y, c)?;
    }
    Ok(y)
}

pub(super) fn collapse_vecs<'a, B: BackendT, const N: usize>(
    backend: &'a mut B,
    elems: &[[B::Wire; N]],
    x: B::FieldElement,
) -> Result<Vec<B::Wire>> {
    let mut out = Vec::with_capacity(elems.len());
    for e in elems {
        out.push(combine(backend, e.iter(), x)?);
    }
    Ok(out)
}

pub trait MemorySpace<V> {
    type Addr: AsRef<[V]>;
    type Enum: Iterator<Item = Self::Addr>;

    const DIM_ADDR: usize;
    const DIM_VALUE: usize;

    fn size(&self) -> usize;

    fn enumerate(&self) -> Self::Enum;
}

pub struct Bounded<F: FiniteField> {
    _ph: PhantomData<F>,
    bound: usize,
}

pub struct BoundedIter<F: FiniteField> {
    current: [F; 1],
    rem: usize,
}

impl<F: FiniteField> Iterator for BoundedIter<F> {
    type Item = [F; 1];

    fn next(&mut self) -> Option<Self::Item> {
        if self.rem > 0 {
            let old = self.current;
            self.current[0] += F::ONE;
            self.rem -= 1;
            Some(old)
        } else {
            None
        }
    }
}

impl<F: FiniteField> Bounded<F> {
    pub fn new(bound: usize) -> Self {
        Self {
            bound,
            _ph: Default::default(),
        }
    }
}

impl<F: FiniteField> MemorySpace<F> for Bounded<F> {
    type Addr = [F; 1];
    type Enum = BoundedIter<F>;

    const DIM_ADDR: usize = 1;
    const DIM_VALUE: usize = 1;

    fn size(&self) -> usize {
        self.bound
    }

    fn enumerate(&self) -> Self::Enum {
        BoundedIter {
            current: [F::ZERO],
            rem: self.bound,
        }
    }
}

pub struct MemoryProver<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    prover: Option<Prover<V, F, C, Bounded<V>, 1, 1, 3, 2, 4>>,
}

impl<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel> Default for MemoryProver<V, F, C>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    fn default() -> Self {
        Self { prover: None }
    }
}

impl<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel> MemoryProver<V, F, C>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    pub fn read(
        &mut self,
        dmc: &mut DietMacAndCheeseProver<V, F, C>,
        addr: &MacProver<V, F>,
    ) -> Result<MacProver<V, F>> {
        match self.prover.as_mut() {
            Some(prover) => {
                let value = prover.remove(dmc, &[*addr])?;
                prover.insert(dmc, &[*addr], &value)?;
                Ok(value[0])
            }
            None => {
                let ram = Prover::<V, F, _, _, 1, 1, 3, 2, 4>::new(dmc, Bounded::new(RAM_SIZE));
                self.prover = Some(ram);
                self.read(dmc, addr)
            }
        }
    }

    pub fn write(
        &mut self,
        dmc: &mut DietMacAndCheeseProver<V, F, C>,
        addr: &MacProver<V, F>,
        value: &MacProver<V, F>,
    ) -> Result<()> {
        match self.prover.as_mut() {
            Some(prover) => {
                prover.remove(dmc, &[*addr])?;
                prover.insert(dmc, &[*addr], &[*value])?;
                Ok(())
            }
            None => {
                let ram = Prover::<V, F, _, _, 1, 1, 3, 2, 4>::new(dmc, Bounded::new(RAM_SIZE));
                self.prover = Some(ram);
                self.write(dmc, addr, value)
            }
        }
    }

    pub fn finalize(&mut self, dmc: &mut DietMacAndCheeseProver<V, F, C>) -> Result<()> {
        match self.prover.take() {
            Some(prover) => prover.finalize(dmc),
            None => Ok(()),
        }
    }
}

pub struct MemoryVerifier<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    verifier: Option<Verifier<V, F, C, Bounded<V>, 1, 1, 3, 2, 4>>,
}

impl<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel> Default for MemoryVerifier<V, F, C>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    fn default() -> Self {
        Self { verifier: None }
    }
}

impl<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel> MemoryVerifier<V, F, C>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    pub fn read(
        &mut self,
        dmc: &mut DietMacAndCheeseVerifier<V, F, C>,
        addr: &MacVerifier<F>,
    ) -> Result<MacVerifier<F>> {
        match self.verifier.as_mut() {
            Some(verifier) => {
                let value = verifier.remove(dmc, &[*addr])?;
                verifier.insert(dmc, &[*addr], &value)?;
                Ok(value[0])
            }
            None => {
                let ram = Verifier::<V, F, _, _, 1, 1, 3, 2, 4>::new(dmc, Bounded::new(RAM_SIZE));
                self.verifier = Some(ram);
                self.read(dmc, addr)
            }
        }
    }

    pub fn write(
        &mut self,
        dmc: &mut DietMacAndCheeseVerifier<V, F, C>,
        addr: &MacVerifier<F>,
        value: &MacVerifier<F>,
    ) -> Result<()> {
        match self.verifier.as_mut() {
            Some(verifier) => {
                verifier.remove(dmc, &[*addr])?;
                verifier.insert(dmc, &[*addr], &[*value])?;
                Ok(())
            }
            None => {
                let ram = Verifier::<V, F, _, _, 1, 1, 3, 2, 4>::new(dmc, Bounded::new(RAM_SIZE));
                self.verifier = Some(ram);
                self.write(dmc, addr, value)
            }
        }
    }

    pub fn finalize(&mut self, dmc: &mut DietMacAndCheeseVerifier<V, F, C>) -> Result<()> {
        match self.verifier.take() {
            Some(verifier) => verifier.finalize(dmc),
            None => Ok(()),
        }
    }
}
