use eyre::Result;
use scuttlebutt::{field::FiniteField, AbstractChannel};
use swanky_field::IsSubFieldOf;

use crate::{
    dora::{comm::CommittedCrossTerms, tx::TxChannel},
    homcom::MacVerifier,
    DietMacAndCheeseVerifier,
};

use super::{
    acc::{collapse_trace, Accumulator, ComittedAcc, Trace},
    comm::CommittedWitness,
    disjunction::Disjunction,
    fiat_shamir,
    perm::permutation,
    COMPACT_MIN, COMPACT_MUL,
};

pub struct DoraVerifier<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    _ph: std::marker::PhantomData<(F, C)>,
    disj: Disjunction<V>,
    init: Vec<ComittedAcc<DietMacAndCheeseVerifier<V, F, C>>>,
    trace: Vec<Trace<DietMacAndCheeseVerifier<V, F, C>>>,
    max_trace: usize, // maximum trace len before compactification
    tx: blake3::Hasher,
}

impl<V: IsSubFieldOf<F>, F: FiniteField, C: AbstractChannel> DoraVerifier<V, F, C>
where
    F::PrimeField: IsSubFieldOf<V>,
{
    pub fn new(disj: Disjunction<V>) -> Self {
        let max_trace = std::cmp::max(disj.clauses().len() * COMPACT_MUL, COMPACT_MIN);
        Self {
            _ph: std::marker::PhantomData,
            trace: Vec::with_capacity(max_trace),
            init: vec![],
            disj,
            max_trace,
            tx: blake3::Hasher::new(),
        }
    }

    pub fn mux(
        &mut self,
        verifier: &mut DietMacAndCheeseVerifier<V, F, C>,
        input: &[MacVerifier<F>],
    ) -> Result<Vec<MacVerifier<F>>> {
        // check if we should compact the trace first
        if self.trace.len() >= self.max_trace {
            self.compact(verifier)?;
        }

        // wrap channel in transcript
        let mut ch = TxChannel::new(verifier.channel.clone(), &mut self.tx);

        // commit to new extended witness
        let wit =
            CommittedWitness::commit_verifer(&mut ch, verifier, &self.disj, input.iter().copied())?;

        // commit to cross terms
        let cxt = CommittedCrossTerms::commit_verifier(&mut ch, verifier, &self.disj)?;

        // commit to old accumulator
        let acc_old = ComittedAcc::commit_verifier(&mut ch, verifier, &self.disj)?;

        // fold
        let challenge = ch.challenge();
        let acc_new = acc_old.fold_witness(verifier, challenge, &cxt, &wit)?;

        // update trace
        self.trace.push(Trace {
            old: acc_old,
            new: acc_new,
        });

        Ok(wit.outputs().to_vec())
    }

    /// Verifies all the disjuctions and consumes the verifier.
    pub fn finalize(mut self, verifier: &mut DietMacAndCheeseVerifier<V, F, C>) -> Result<()> {
        // compact into single set of accumulators
        self.compact(verifier)?;

        // verify accumulors
        for (acc, r1cs) in self.init.into_iter().zip(self.disj.clauses()) {
            acc.verify(verifier, r1cs)?;
        }
        Ok(())
    }

    // "compact" the disjunction trace (without verification)
    //
    // Commits to all the accumulators and executes the permutation proof.
    // This reduces the trace to a single element per branch.
    fn compact(&mut self, verifier: &mut DietMacAndCheeseVerifier<V, F, C>) -> Result<()> {
        // commit to all accumulators
        let mut ch = TxChannel::new(verifier.channel.clone(), &mut self.tx);
        let mut accs = Vec::with_capacity(self.disj.clauses().len());
        for _ in self.disj.clauses() {
            accs.push(ComittedAcc::commit_verifier(&mut ch, verifier, &self.disj)?);
        }

        // challenges for permutation proof
        // obtain challenges for permutation proof
        let (chal_perm, chal_cmbn) = if fiat_shamir::<V>() {
            (ch.challenge(), ch.challenge())
        } else {
            let chal_perm = V::random(&mut verifier.rng);
            let chal_cmbn = V::random(&mut verifier.rng);
            verifier.channel.write_serializable(&chal_perm)?;
            verifier.channel.write_serializable(&chal_cmbn)?;
            verifier.channel.flush()?;
            (chal_perm, chal_cmbn)
        };

        // collapse trace into single elements
        let (mut lhs, mut rhs) = collapse_trace(verifier, &self.trace, chal_cmbn)?;

        // add initial / final accumulator to permutation proof
        for (i, (acc, r1cs)) in accs.iter_mut().zip(self.disj.clauses()).enumerate() {
            lhs.push(acc.combine(verifier, chal_cmbn)?);
            rhs.push(match self.init.get(i) {
                Some(acc) => acc.combine(verifier, chal_cmbn)?,
                None => Accumulator::init(r1cs).combine(verifier, chal_cmbn)?,
            });
        }

        // execute permutation proof
        self.trace.clear();
        self.init = accs;
        permutation(verifier, chal_perm, &lhs, &rhs)
    }
}
