use clap::Parser;

use diet_mac_and_cheese::backend_trait::BackendT;
use diet_mac_and_cheese::ram::{self, Bounded};
use diet_mac_and_cheese::{DietMacAndCheeseProver, DietMacAndCheeseVerifier};
use eyre::Result;
use log::info;
use pretty_env_logger;
use scuttlebutt::channel::{CntReader, CntWriter};
use scuttlebutt::{AesRng, Channel};
use std::env;
use std::io::{BufReader, BufWriter};
use std::net::{TcpListener, TcpStream};
use std::time::Instant;
use swanky_field_f61p::F61p;

use scuttlebutt::AbstractChannel;

use clap::{Subcommand, ValueEnum};
use ocelot::svole::{
    LpnParams, LPN_EXTEND_LARGE, LPN_EXTEND_MEDIUM, LPN_EXTEND_SMALL, LPN_SETUP_LARGE,
    LPN_SETUP_MEDIUM, LPN_SETUP_SMALL,
};

const DEFAULT_ADDR: &str = "127.0.0.1:5527";
const DEFAULT_LPN: LpnSize = LpnSize::Medium;

/// Lpn params as small, medium or large.
#[derive(Copy, Clone, PartialEq, Eq, PartialOrd, Ord, Debug, ValueEnum)]
pub(crate) enum LpnSize {
    Small,
    Medium,
    Large,
}

/// Map an `LpnSize` to a pair of Lpn parameters for the init and extension phase.
#[allow(dead_code)] // This is _not_ dead code, but the compiler thinks it is (it is used in `dietmc_zki.rs`)
pub(crate) fn map_lpn_size(lpn_param: &LpnSize) -> (LpnParams, LpnParams) {
    match lpn_param {
        LpnSize::Small => {
            return (LPN_SETUP_SMALL, LPN_EXTEND_SMALL);
        }
        LpnSize::Medium => {
            return (LPN_SETUP_MEDIUM, LPN_EXTEND_MEDIUM);
        }
        LpnSize::Large => {
            return (LPN_SETUP_LARGE, LPN_EXTEND_LARGE);
        }
    }
}

#[derive(Subcommand)]
pub(crate) enum Prover {
    Prover,
}

/// Cli.
#[derive(Parser)]
#[clap(name = "Dora RAM")]
#[clap(version = "0.1")]
pub(crate) struct Cli {
    /// Set addr for tcp connection
    #[clap(default_value_t = DEFAULT_ADDR.to_string(), short, long)]
    pub connection_addr: String,

    /// Select lpn parameter
    #[clap(value_enum, default_value_t = DEFAULT_LPN, long)]
    pub lpn: LpnSize,

    /// No batching for check_zero
    #[arg(long)]
    pub nobatching: bool,

    /// ram cells
    #[clap(long)]
    pub ram_size: usize,

    /// ram steps
    #[clap(long)]
    pub ram_steps: usize,

    /// ram runs
    #[clap(long, default_value = "1")]
    pub ram_runs: usize,

    #[clap(long)]
    pub prover: bool,
}

// Run with relation in text format
fn run_text(args: &Cli) -> Result<()> {
    let start = Instant::now();

    info!("time reading ins/wit/rel: {:?}", start.elapsed());

    let (lpn_setup, lpn_expand) = map_lpn_size(&args.lpn);

    match args.prover {
        false => {
            // Verifier mode
            let listener = TcpListener::bind(&args.connection_addr)?;
            match listener.accept() {
                Ok((stream, _addr)) => {
                    info!("connection received");
                    let reader = BufReader::new(stream.try_clone()?);
                    let writer = BufWriter::new(stream);

                    let reader = CntReader::new(reader);
                    let writer = CntWriter::new(writer);

                    let rng = AesRng::new();
                    let mut channel = Channel::new(reader, writer);

                    let start = Instant::now();

                    let mut verifier: DietMacAndCheeseVerifier<F61p, F61p, _> =
                        DietMacAndCheeseVerifier::init(
                            &mut channel,
                            rng,
                            lpn_setup,
                            lpn_expand,
                            args.nobatching,
                        )
                        .unwrap();

                    info!("init time: {:?}", start.elapsed());
                    let start = Instant::now();

                    for run in 0..args.ram_runs {
                        info!("run {}/{}", run, args.ram_runs);

                        let mut ram = ram::Verifier::<F61p, F61p, _, _, 1, 1, 3, 2, 4>::new(
                            &mut verifier,
                            Bounded::new(args.ram_size),
                        );

                        for _i in 0..args.ram_steps {
                            let addr = verifier.input_private(None).unwrap();
                            let value = ram.remove(&mut verifier, &[addr]).unwrap();
                            ram.insert(&mut verifier, &[addr], &value).unwrap();
                        }
                        info!("finalizing ram");
                        ram.finalize(&mut verifier).unwrap();
                    }
                    info!("finalizing verifier");
                    verifier.finalize().unwrap();

                    info!("ram-size {}", args.ram_size);
                    info!("ram-steps {}", args.ram_steps);
                    info!("ram-runs {}", args.ram_runs);
                    info!("time ram exec: {:?}", start.elapsed());
                    let sent = channel.clone().writer().borrow().count();
                    let recv = channel.clone().reader().borrow().count();
                    info!("bytes sent: {}", sent);
                    info!("bytes recv: {}", recv);
                    info!("bytes total: {}", sent + recv);
                    info!("VERIFIER DONE!");
                }
                Err(e) => info!("couldn't get client: {:?}", e),
            }
        }
        true => {
            // Prover mode
            let stream;
            loop {
                let c = TcpStream::connect(args.connection_addr.clone());
                match c {
                    Ok(s) => {
                        stream = s;
                        break;
                    }
                    Err(_) => {}
                }
            }

            let reader = BufReader::new(stream.try_clone()?);
            let writer = BufWriter::new(stream);

            let reader = CntReader::new(reader);
            let writer = CntWriter::new(writer);

            let mut channel = Channel::new(reader, writer);

            let rng = AesRng::new();
            let start = Instant::now();

            let mut prover: DietMacAndCheeseProver<F61p, F61p, _> = DietMacAndCheeseProver::init(
                &mut channel,
                rng,
                lpn_setup,
                lpn_expand,
                args.nobatching,
            )
            .unwrap();

            info!("init time: {:?}", start.elapsed());
            let start = Instant::now();

            for run in 0..args.ram_runs {
                info!("run {}/{}", run, args.ram_runs);

                // create ram
                let mut ram = ram::Prover::<F61p, F61p, _, _, 1, 1, 3, 2, 4>::new(
                    &mut prover,
                    Bounded::new(args.ram_size),
                );

                // insert/remove random values
                for _i in 0..args.ram_steps {
                    let addr = rand::random::<u32>() % (args.ram_size as u32);
                    let addr = F61p::try_from(addr as u128).unwrap();
                    let addr = prover.input_private(Some(addr.into())).unwrap();
                    let value = ram.remove(&mut prover, &[addr]).unwrap();
                    ram.insert(&mut prover, &[addr], &value).unwrap();
                }
                info!("finalizing ram");
                ram.finalize(&mut prover).unwrap();
            }
            info!("finalizing prover");
            prover.finalize().unwrap();

            info!("time ram exec: {:?}", start.elapsed());
            let sent = channel.clone().writer().borrow().count();
            let recv = channel.clone().reader().borrow().count();
            info!("ram-size {}", args.ram_size);
            info!("ram-steps {}", args.ram_steps);
            info!("ram-runs {}", args.ram_runs);

            info!("bytes sent: {}", sent);
            info!("bytes recv: {}", recv);
            info!("bytes total: {}", sent + recv);
            info!("PROVER DONE!");
        }
    }
    Ok(())
}

fn run(args: &Cli) -> Result<()> {
    if args.prover {
        info!("prover mode");
    } else {
        info!("verifier mode");
    }
    info!("addr: {:?}", args.connection_addr);
    info!("lpn: {:?}", args.lpn);

    run_text(args)
}

fn main() -> Result<()> {
    // if log-level `RUST_LOG` not already set, then set to info
    match env::var("RUST_LOG") {
        Ok(val) => println!("loglvl: {}", val),
        Err(_) => env::set_var("RUST_LOG", "info"),
    };

    pretty_env_logger::init_timed();

    let cli = Cli::parse();

    run(&cli)
}
