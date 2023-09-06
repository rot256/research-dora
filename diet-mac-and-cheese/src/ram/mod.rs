use std::marker::PhantomData;

use eyre::Result;
use swanky_field::FiniteField;

use crate::backend_trait::BackendT;

mod perm;
mod prover;
mod tests;
mod tx;
mod verifier;

const SEP: &[u8] = b"FS_RAM";

const PRE_ALLOC_MEM: usize = 1 << 20;
const PRE_ALLOC_STEPS: usize = 1 << 23;

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
    type Enum: Iterator<Item = Vec<V>>;

    fn enumerate(&self) -> Self::Enum;

    fn dim_addr(&self) -> usize;

    //
    fn dim_value(&self) -> usize;
}

struct Bounded<F: FiniteField> {
    _ph: PhantomData<F>,
    bound: usize,
}

struct BoundedIter<F: FiniteField> {
    current: F,
    rem: usize,
}

impl<F: FiniteField> Iterator for BoundedIter<F> {
    type Item = Vec<F>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.rem > 0 {
            let old = self.current;
            self.current += F::ONE;
            self.rem -= 1;
            Some(vec![old])
        } else {
            None
        }
    }
}

impl<F: FiniteField> Bounded<F> {
    fn new(bound: usize) -> Self {
        Self {
            bound,
            _ph: Default::default(),
        }
    }
}

impl<F: FiniteField> MemorySpace<F> for Bounded<F> {
    type Enum = BoundedIter<F>;

    fn enumerate(&self) -> Self::Enum {
        BoundedIter {
            current: F::ZERO,
            rem: self.bound,
        }
    }

    fn dim_addr(&self) -> usize {
        1
    }

    fn dim_value(&self) -> usize {
        1
    }
}
