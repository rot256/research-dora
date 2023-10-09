use mac_n_cheese_sieve_parser::PluginTypeArg;

use crate::circuit_ir::{FunStore, TypeId, TypeStore, WireCount};
use eyre::Result;

use super::{Plugin, PluginExecution};

#[derive(Debug, Clone, Copy)]
pub enum RamOperation {
    Read,
    Write,
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct RamV0 {
    field: TypeId,
    op: RamOperation,
}

impl RamV0 {
    pub fn field(&self) -> TypeId {
        self.field
    }

    pub fn operation(&self) -> RamOperation {
        self.op
    }
}

impl Plugin for RamV0 {
    const NAME: &'static str = "galois_ram_v0";

    fn instantiate(
        operation: &str,
        _params: &[PluginTypeArg],
        _output_counts: &[(TypeId, WireCount)],
        input_counts: &[(TypeId, WireCount)],
        _type_store: &TypeStore,
        _fun_store: &FunStore,
    ) -> Result<PluginExecution> {
        let op = match operation {
            "read" => RamOperation::Read,
            "write" => RamOperation::Write,
            _ => panic!("unsupported memory operation: \"{}\"", operation),
        };

        let mut field = None;
        for (typ, cnt) in input_counts.into_iter().copied() {
            field = Some(typ);
        }
        Ok(PluginExecution::Ram(RamV0 {
            field: field.unwrap(),
            op,
        }))
    }
}
