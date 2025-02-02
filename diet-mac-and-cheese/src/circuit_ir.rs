//! This module contains types pertaining to the internal representation of the
//! SIEVE Circuit IR.

use crate::{
    fields::modulus_to_type_id,
    plugins::{DisjunctionV0, Plugin, PluginBody, PluginType, RamV0},
};
use eyre::{bail, eyre, Result};
use log::debug;
use mac_n_cheese_sieve_parser::{Number, PluginTypeArg};
use std::{
    cmp::max,
    collections::{BTreeMap, VecDeque},
};

/// The wire index.
pub type WireId = u64;
/// A count of the number of wires.
pub type WireCount = u64;
/// The type index.
///
/// This is a value `< 256` that is associated with a specific Circuit IR
/// [`@type`](`TypeSpecification`).
pub type TypeId = u8;
/// An inclusive range of [`WireId`]s.
pub type WireRange = (WireId, WireId);

/// The conversion gate representation. The first [`TypeId`]-[`WireRange`]
/// pairing denotes the _output_ of the conversion, and the second pairing
/// denotes the _input_ of the conversion.
pub type ConvGate = (TypeId, WireRange, TypeId, WireRange);
/// The call gate representation. The [`String`] denotes the function name, the
/// first [`Vec`] denotes the _output_ wires, and the second [`Vec`] denotes the
/// _input_ wires.
pub type CallGate = (String, Vec<WireRange>, Vec<WireRange>);

/// The internal circuit representation gate types.
///
/// Most gates take a [`TypeId`] as their first argument, which denotes the
/// Circuit IR type associated with the given gate. In addition, the [`WireId`]
/// ordering for gates is generally: `<out> <in> ...`; that is, the first
/// [`WireId`] denotes the _output_ of the gate.
// This enum should fit in 32 bytes.
// Using `Box<Number>` for this reason.
#[derive(Clone, Debug)]
pub enum GateM {
    /// Store the given element in [`WireId`].
    Constant(TypeId, WireId, Box<Number>),
    /// Assert that the element in [`WireId`] is zero.
    AssertZero(TypeId, WireId),
    Copy(TypeId, WireId, WireId),
    /// Adds the elements in the latter two [`WireId`]s together, storing the
    /// result in the first [`WireId`].
    Add(TypeId, WireId, WireId, WireId),
    Sub(TypeId, WireId, WireId, WireId),
    Mul(TypeId, WireId, WireId, WireId),
    AddConstant(TypeId, WireId, WireId, Box<Number>),
    MulConstant(TypeId, WireId, WireId, Box<Number>),
    Instance(TypeId, WireId),
    Witness(TypeId, WireId),
    /// Does field conversion.
    Conv(Box<ConvGate>),
    New(TypeId, WireId, WireId),
    Delete(TypeId, WireId, WireId),
    Call(Box<CallGate>),
    Challenge(TypeId, WireId),
    Comment(String),
}

#[test]
fn size_of_gate_m_less_than_32_bytes() {
    // Enforce that `GateM` fits in 32 bytes.
    assert!(std::mem::size_of::<GateM>() <= 32);
}

impl GateM {
    /// Return the [`TypeId`] associated with this gate.
    pub(crate) fn type_id(&self) -> TypeId {
        use GateM::*;
        match self {
            Constant(ty, _, _)
            | AssertZero(ty, _)
            | Copy(ty, _, _)
            | Add(ty, _, _, _)
            | Sub(ty, _, _, _)
            | Mul(ty, _, _, _)
            | AddConstant(ty, _, _, _)
            | MulConstant(ty, _, _, _)
            | New(ty, _, _)
            | Delete(ty, _, _)
            | Instance(ty, _)
            | Witness(ty, _)
            | Challenge(ty, _) => *ty,
            Conv(_) | Call(_) => todo!(),
            Comment(_) => panic!("There's no `TypeId` associated with a comment!"),
        }
    }

    /// Return the [`WireId`] associated with the output of this gate, or
    /// `None` if the gate has no output wire.
    pub(crate) fn out_wire(&self) -> Option<WireId> {
        use GateM::*;
        match self {
            Constant(_, out, _)
            | Copy(_, out, _)
            | Add(_, out, _, _)
            | Sub(_, out, _, _)
            | Mul(_, out, _, _)
            | AddConstant(_, out, _, _)
            | MulConstant(_, out, _, _)
            | Instance(_, out)
            | Witness(_, out)
            | New(_, _, out)
            | Challenge(_, out) => Some(*out),
            AssertZero(_, _) | Delete(_, _, _) | Comment(_) => None,
            Conv(c) => {
                let (_, (_, out), _, _) = c.as_ref();
                Some(*out)
            }
            Call(arg) => {
                let (_, v, _) = arg.as_ref();
                v.iter().fold(None, |acc, (_, last)| max(acc, Some(*last)))
            }
        }
    }
}

/// Specification for Circuit IR types.
///
/// This corresponds to the `@type` specifier. A type can either be a `Field` or
/// a `Plugin`.
#[derive(Clone, Debug)]
pub enum TypeSpecification {
    /// The field, stored as a [`TypeId`](std::any::TypeId).
    Field(std::any::TypeId),
    /// The plugin type.
    Plugin(PluginType),
}

/// A mapping from [`TypeId`]s to their [`TypeSpecification`]s.
///
/// This mapping contains all the types used in the circuit, accessible by their
/// [`TypeId`].
#[derive(Clone, Default)]
pub struct TypeStore(BTreeMap<TypeId, TypeSpecification>);

impl TypeStore {
    /// Insert a [`TypeId`]-[`TypeSpecification`] pair into the [`TypeStore`].
    pub(crate) fn insert(&mut self, key: TypeId, value: TypeSpecification) {
        self.0.insert(key, value);
    }

    /// Get the [`TypeSpecification`] associated with the given [`TypeId`].
    pub(crate) fn get(&self, key: &TypeId) -> eyre::Result<&TypeSpecification> {
        self.0
            .get(key)
            .ok_or_else(|| eyre!("Type ID {key} not found in `TypeStore`"))
    }

    /// Return an [`Iterator`] over the [`TypeId`]-[`TypeSpecification`] pairs
    /// in the [`TypeStore`].
    pub fn iter(&self) -> std::collections::btree_map::Iter<TypeId, TypeSpecification> {
        self.0.iter()
    }
}

impl TryFrom<Vec<mac_n_cheese_sieve_parser::Type>> for TypeStore {
    type Error = eyre::Error;

    fn try_from(
        types: Vec<mac_n_cheese_sieve_parser::Type>,
    ) -> std::result::Result<Self, Self::Error> {
        debug!("Converting Circuit IR types to `TypeStore`");
        if types.len() > 256 {
            return Err(eyre!("Too many types specified: {} > 256", types.len()));
        }
        let mut store = TypeStore::default();
        for (i, ty) in types.into_iter().enumerate() {
            let spec = match ty {
                mac_n_cheese_sieve_parser::Type::Field { modulus } => {
                    TypeSpecification::Field(modulus_to_type_id(modulus)?)
                }
                mac_n_cheese_sieve_parser::Type::ExtField { .. } => {
                    bail!("Extension fields not supported!")
                }
                mac_n_cheese_sieve_parser::Type::PluginType(ty) => {
                    TypeSpecification::Plugin(PluginType::from(ty))
                }
            };
            store.insert(i as u8, spec);
        }
        Ok(store)
    }
}

impl TryFrom<Vec<Number>> for TypeStore {
    type Error = eyre::Error;

    fn try_from(fields: Vec<Number>) -> std::result::Result<Self, Self::Error> {
        debug!("Converting vector of fields to `TypeStore`");
        if fields.len() > 256 {
            return Err(eyre!("Too many types specified: {} > 256", fields.len()));
        }
        let mut store = TypeStore::default();
        for (i, field) in fields.into_iter().enumerate() {
            let spec = TypeSpecification::Field(modulus_to_type_id(field)?);
            store.insert(i as u8, spec);
        }
        Ok(store)
    }
}

/// A bitmap of the used / set [`TypeId`]s.
///
/// A [`TypeId`] is "set" if it is used in the computation.
pub(crate) struct TypeIdMapping([bool; 256]);

impl TypeIdMapping {
    /// Set the associated [`TypeId`].
    pub(crate) fn set(&mut self, ty: TypeId) {
        self.0[ty as usize] = true;
    }

    /// Set the [`TypeId`]s associated with a given [`GateM`].
    pub(crate) fn set_from_gate(&mut self, gate: &GateM) {
        use GateM::*;
        match gate {
            Constant(ty, _, _)
            | AssertZero(ty, _)
            | Copy(ty, _, _)
            | Add(ty, _, _, _)
            | Sub(ty, _, _, _)
            | Mul(ty, _, _, _)
            | AddConstant(ty, _, _, _)
            | MulConstant(ty, _, _, _)
            | Instance(ty, _)
            | Witness(ty, _)
            | New(ty, _, _)
            | Delete(ty, _, _)
            | Challenge(ty, _) => {
                self.set(*ty);
            }
            Call(_) | Comment(_) => {}
            Conv(c) => {
                let (ty1, _, ty2, _) = c.as_ref();
                self.set(*ty1);
                self.set(*ty2);
            }
        }
    }

    /// Convert [`TypeIdMapping`] to a [`Vec`] containing the set [`TypeId`]s.
    fn to_type_ids(self) -> Vec<TypeId> {
        self.0
            .iter()
            .enumerate()
            .filter_map(|(i, b)| {
                if *b {
                    Some(i.try_into().expect("Index should be less than 256"))
                } else {
                    None
                }
            })
            .collect()
    }
}

impl Default for TypeIdMapping {
    fn default() -> Self {
        Self([false; 256]) // There are only 256 possible `TypeId`s
    }
}

impl From<&GatesBody> for TypeIdMapping {
    fn from(gates: &GatesBody) -> Self {
        let mut mapping = TypeIdMapping::default();
        for g in gates.gates.iter() {
            mapping.set_from_gate(g);
        }
        mapping
    }
}

/// A body of computation containing a sequence of [`GateM`]s.
#[derive(Clone, Debug)]
#[repr(transparent)]
pub(crate) struct GatesBody {
    gates: Vec<GateM>,
}

impl GatesBody {
    /// Create a new [`GatesBody`].
    pub(crate) fn new(gates: Vec<GateM>) -> Self {
        Self { gates }
    }

    pub(crate) fn gates(&self) -> &[GateM] {
        &self.gates
    }

    /// Return the maximum [`WireId`] found, or `None` if no [`WireId`] was found.
    pub(crate) fn output_wire_max(&self) -> Option<WireId> {
        self.gates
            .iter()
            .fold(None, |acc, x| max(acc, x.out_wire()))
    }
}

/// The body of a Circuit IR function.
///
/// The function body can be either a sequence of gates or a plugin.
#[derive(Clone)]
pub(crate) enum FunctionBody {
    /// The function body as a sequence of gates.
    Gates(GatesBody),
    /// The function body as a plugin.
    Plugin(PluginBody),
}

/// Collected information associated with a Circuit IR function.
#[derive(Clone)]
pub(crate) struct CompiledInfo {
    /// Count of wires for output/input arguments to the function.
    pub(crate) args_count: Option<WireId>,
    // The maximum [`WireId`] in the function body.
    pub(crate) body_max: Option<WireId>,
    /// [`TypeId`]s encountered in the function body.
    pub(crate) type_ids: Vec<TypeId>,
}

/// A Circuit IR function declaration.
#[derive(Clone)]
pub struct FuncDecl {
    /// The function body.
    body: FunctionBody,
    /// A [`Vec`] containing pairings of [`TypeId`]s and their associated output
    /// [`WireCount`].
    pub(crate) output_counts: Vec<(TypeId, WireCount)>,
    /// A [`Vec`] containing pairings of [`TypeId`]s and their associated input
    /// [`WireCount`].
    pub(crate) input_counts: Vec<(TypeId, WireCount)>,
    pub(crate) compiled_info: CompiledInfo, // pub(crate) to ease logging
}

/// Return the first [`WireId`] available for allocation in the `Plugin`'s
/// [`GateBody`].
///
/// Arguments:
/// - `output_counts`: A slice containing the outputs given as a tuple of
/// [`TypeId`] and [`WireCount`].
/// - `input_counts`: A slice containing the inputs given as a tuple of
/// [`TypeId`] and [`WireCount`].
pub(crate) fn first_unused_wire_id(
    output_counts: &[(TypeId, WireCount)],
    input_counts: &[(TypeId, WireCount)],
) -> WireId {
    let mut first_unused_wire_id = 0;

    for (_, wc) in output_counts.iter() {
        first_unused_wire_id += wc;
    }

    for (_, wc) in input_counts.iter() {
        first_unused_wire_id += wc;
    }

    first_unused_wire_id
}

impl FuncDecl {
    /// Instantiate a new function.
    ///
    /// * `gates` denotes a sequence of gates that makes up the function body.
    /// * `output_counts` denotes the wire counts for each [`TypeId`] used as an
    ///   output.
    /// * `input_counts` denotes the wire counts for each [`TypeId`] used as an
    ///   input.
    pub fn new_function(
        gates: Vec<GateM>,
        output_counts: Vec<(TypeId, WireCount)>,
        input_counts: Vec<(TypeId, WireCount)>,
    ) -> Self {
        let gates = GatesBody::new(gates);
        let body_max = gates.output_wire_max();
        let mut type_presence = TypeIdMapping::from(&gates);
        let mut args_count = 0;
        for (ty, wc) in output_counts.iter() {
            type_presence.set(*ty);
            args_count += wc;
        }
        for (ty, wc) in input_counts.iter() {
            type_presence.set(*ty);
            args_count += wc;
        }

        let body = FunctionBody::Gates(gates);
        let type_ids = type_presence.to_type_ids();

        FuncDecl {
            body,
            output_counts,
            input_counts,
            compiled_info: CompiledInfo {
                args_count: Some(args_count),
                body_max,
                type_ids,
            },
        }
    }

    /// Instantiate a new plugin.
    ///
    /// * `output_counts` contains the wire counts for each [`TypeId`] used as an
    ///   output.
    /// * `input_counts` contains the wire counts for each [`TypeId`] used as an
    ///   input.
    /// * `plugin_name` is the name of the plugin.
    /// * `operation` is the plugin operation.
    /// * `params` contains any associated parameters to the plugin operation.
    /// * `type_store` contains the [`TypeStore`] of the circuit.
    /// * `fun_store` contains the [`FunStore`] of the circuit.
    pub fn new_plugin(
        output_counts: Vec<(TypeId, WireCount)>,
        input_counts: Vec<(TypeId, WireCount)>,
        plugin_name: String,
        operation: String,
        params: Vec<PluginTypeArg>,
        _public_count: Vec<(TypeId, WireId)>,
        _private_count: Vec<(TypeId, WireId)>,
        type_store: &TypeStore,
        fun_store: &FunStore,
    ) -> Result<Self> {
        use crate::plugins::{GaloisPolyV0, IterV0, MuxV0, MuxV1, PermutationCheckV1, VectorsV1};

        let execution = match plugin_name.as_str() {
            MuxV0::NAME => MuxV0::instantiate(
                &operation,
                &params,
                &output_counts,
                &input_counts,
                type_store,
                fun_store,
            )?,
            MuxV1::NAME => MuxV1::instantiate(
                &operation,
                &params,
                &output_counts,
                &input_counts,
                type_store,
                fun_store,
            )?,
            PermutationCheckV1::NAME => PermutationCheckV1::instantiate(
                &operation,
                &params,
                &output_counts,
                &input_counts,
                type_store,
                fun_store,
            )?,
            IterV0::NAME => IterV0::instantiate(
                &operation,
                &params,
                &output_counts,
                &input_counts,
                type_store,
                fun_store,
            )?,
            VectorsV1::NAME => VectorsV1::instantiate(
                &operation,
                &params,
                &output_counts,
                &input_counts,
                type_store,
                fun_store,
            )?,
            GaloisPolyV0::NAME => GaloisPolyV0::instantiate(
                &operation,
                &params,
                &output_counts,
                &input_counts,
                type_store,
                fun_store,
            )?,
            DisjunctionV0::NAME => DisjunctionV0::instantiate(
                &operation,
                &params,
                &output_counts,
                &input_counts,
                type_store,
                fun_store,
            )?,
            RamV0::NAME => RamV0::instantiate(
                &operation,
                &params,
                &output_counts,
                &input_counts,
                type_store,
                fun_store,
            )?,
            name => bail!("Unsupported plugin: {name}"),
        };

        let args_count = Some(first_unused_wire_id(&output_counts, &input_counts));
        let body_max = execution.output_wire_max();

        let mut type_presence = execution.type_id_mapping();
        for (ty, _) in output_counts.iter() {
            type_presence.set(*ty);
        }
        for (ty, _) in input_counts.iter() {
            type_presence.set(*ty);
        }

        let type_ids = type_presence.to_type_ids();
        let plugin_body = PluginBody::new(plugin_name, operation, execution);

        Ok(FuncDecl {
            body: FunctionBody::Plugin(plugin_body),
            output_counts,
            input_counts,
            compiled_info: CompiledInfo {
                args_count,
                body_max,
                type_ids,
            },
        })
    }

    pub(crate) fn body(&self) -> &FunctionBody {
        &self.body
    }

    pub(crate) fn input_counts(&self) -> &[(TypeId, WireCount)] {
        &self.input_counts
    }

    pub(crate) fn output_counts(&self) -> &[(TypeId, WireCount)] {
        &self.output_counts
    }
}

/// A mapping of function names to their [`FuncDecl`]s.
#[derive(Clone, Default)]
pub struct FunStore(BTreeMap<String, FuncDecl>);

impl FunStore {
    pub fn insert(&mut self, name: String, func: FuncDecl) {
        self.0.insert(name, func);
    }

    pub fn get(&self, name: &String) -> eyre::Result<&FuncDecl> {
        self.0
            .get(name)
            .ok_or_else(|| eyre!("Missing function name '{name}' in `FuncStore`"))
    }
}

// TODO: add type synonym for Vec<u8> serialized field values,
//       maybe use Box<[u8]> like in other places.
#[derive(Default)]
pub struct CircInputs {
    ins: Vec<VecDeque<Number>>,
    wit: Vec<VecDeque<Number>>,
}

impl CircInputs {
    #[inline]
    fn adjust_ins_type_idx(&mut self, type_id: usize) {
        let n = self.ins.len();
        if n <= type_id {
            for _i in n..(type_id + 1) {
                self.ins.push(Default::default());
            }
        }
    }
    #[inline]
    fn adjust_wit_type_idx(&mut self, type_id: usize) {
        let n = self.wit.len();
        if n <= type_id {
            for _i in n..(type_id + 1) {
                self.wit.push(Default::default());
            }
        }
    }

    // Return the number of instances associated with a given `type_id`
    pub fn num_instances(&self, type_id: usize) -> usize {
        self.ins[type_id].len()
    }

    // Return the number of witnesses associated with a given `type_id`
    pub fn num_witnesses(&self, type_id: usize) -> usize {
        self.wit[type_id].len()
    }

    /// Ingest instance.
    pub fn ingest_instance(&mut self, type_id: usize, instance: Number) {
        self.adjust_ins_type_idx(type_id);
        self.ins[type_id].push_back(instance);
    }

    /// Ingest witness.
    pub fn ingest_witness(&mut self, type_id: usize, witness: Number) {
        self.adjust_wit_type_idx(type_id);
        self.wit[type_id].push_back(witness);
    }

    /// Ingest instances.
    pub fn ingest_instances(&mut self, type_id: usize, instances: VecDeque<Number>) {
        self.adjust_ins_type_idx(type_id);
        self.ins[type_id] = instances;
    }

    /// Ingest witnesses.
    pub fn ingest_witnesses(&mut self, type_id: usize, witnesses: VecDeque<Number>) {
        self.adjust_wit_type_idx(type_id);
        self.wit[type_id] = witnesses;
    }

    pub fn pop_instance(&mut self, type_id: usize) -> Option<Number> {
        self.adjust_ins_type_idx(type_id);
        self.ins[type_id].pop_front()
    }

    pub fn pop_witness(&mut self, type_id: usize) -> Option<Number> {
        self.adjust_wit_type_idx(type_id);
        self.wit[type_id].pop_front()
    }
}
