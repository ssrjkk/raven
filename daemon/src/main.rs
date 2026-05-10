use std::path::PathBuf;
use clap::{Parser, Subcommand};
use anyhow::Result;

mod system;
mod health;
mod api;

#[derive(Parser)]
#[command(name = "ravend", version = "0.1.0", about = "Raven AI system daemon")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Start the daemon
    Start {
        /// HTTP API port
        #[arg(short, long, default_value = "18999")]
        port: u16,
        /// Log file path
        #[arg(short, long, default_value = "/var/log/ravend.log")]
        log: PathBuf,
    },
    /// Stop the daemon
    Stop,
    /// Show daemon status
    Status,
    /// Run system health check
    Health,
    /// Print system info
    Info,
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    let cli = Cli::parse();

    match cli.command {
        Commands::Start { port, log } => {
            log::info!("Starting ravend on port {}, log: {}", port, log.display());
            api::serve(port).await?;
        }
        Commands::Stop => {
            system::stop_daemon().await?;
        }
        Commands::Status => {
            let status = system::get_status().await?;
            println!("{}", serde_json::to_string_pretty(&status)?);
        }
        Commands::Health => {
            let report = health::check_all().await?;
            println!("{}", serde_json::to_string_pretty(&report)?);
        }
        Commands::Info => {
            let info = system::get_system_info().await?;
            println!("{}", serde_json::to_string_pretty(&info)?);
        }
    }

    Ok(())
}
