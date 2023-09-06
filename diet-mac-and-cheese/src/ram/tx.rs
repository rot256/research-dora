use std::io::Result;

use scuttlebutt::{field::FiniteField, AbstractChannel};

#[derive(Debug)]
pub struct TxChannel<C: AbstractChannel> {
    pub ch: C,
    pub tx: blake3::Hasher,
}

impl<'a, C: AbstractChannel> AbstractChannel for TxChannel<C> {
    fn clone(&self) -> Self
    where
        Self: Sized,
    {
        unimplemented!("Fiat-Shamir channel does not allow cloning")
    }

    fn read_bytes(&mut self, buf: &mut [u8]) -> Result<()> {
        self.ch.read_bytes(buf)?;
        self.tx.update(buf);
        Ok(())
    }

    fn write_bytes(&mut self, buf: &[u8]) -> Result<()> {
        self.tx.update(buf);
        self.ch.write_bytes(buf)
    }

    fn flush(&mut self) -> Result<()> {
        self.ch.flush()
    }
}

impl<'a, C: AbstractChannel> TxChannel<C> {
    pub fn new(ch: C, tx: blake3::Hasher) -> Self {
        Self { ch, tx }
    }

    pub fn challenge<F: FiniteField, const N: usize>(&mut self) -> [F; N] {
        let mut out: [F; N] = [F::ZERO; N];
        let mut i = 0;
        while i < N {
            let hsh = self.tx.finalize();
            let a = hsh.as_bytes()[..16].try_into().unwrap();
            out[i] = F::from_uniform_bytes(a);
            if i == N - 1 {
                break;
            }
            i += 1;

            let b = hsh.as_bytes()[16..].try_into().unwrap();
            out[i] = F::from_uniform_bytes(b);
            i += 1;
        }
        out
    }
}
