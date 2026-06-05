use serde::Serialize;
use sysinfo::{System, Disks};
use anyhow::Result;

#[derive(Serialize)]
pub struct SystemInfo {
    pub hostname: String,
    pub os: String,
    pub kernel: String,
    pub cpu_brand: String,
    pub cpu_cores: usize,
    pub memory_total: u64,
    pub memory_used: u64,
    pub memory_percent: f64,
    pub disk_total: u64,
    pub disk_used: u64,
    pub uptime: u64,
    pub processes: Vec<ProcessInfo>,
}

#[derive(Serialize)]
pub struct ProcessInfo {
    pub pid: u32,
    pub name: String,
    pub cpu: f32,
    pub memory: f64,
    pub status: String,
}

#[derive(Serialize)]
pub struct DaemonStatus {
    pub running: bool,
    pub pid: Option<u32>,
    pub version: &'static str,
}

pub async fn get_system_info() -> Result<SystemInfo> {
    let mut sys = System::new_all();
    sys.refresh_all();
    tokio::task::yield_now().await;

    let hostname = System::host_name().unwrap_or_default();
    let os = System::long_os_version().unwrap_or_default();
    let kernel = System::kernel_version().unwrap_or_default();

    let cpu = sys.cpus().first().map(|c| c.brand().to_string()).unwrap_or_default();
    let cores = sys.cpus().len();

    let memory_total = sys.total_memory();
    let memory_used = sys.used_memory();
    let memory_percent = if memory_total > 0 {
        (memory_used as f64 / memory_total as f64) * 100.0
    } else {
        0.0
    };

    let mut disk_total = 0u64;
    let mut disk_used = 0u64;
    for disk in Disks::new() {
        disk_total += disk.total_space();
        disk_used += disk.total_space() - disk.available_space();
    }

    let uptime = System::uptime();

    let processes: Vec<ProcessInfo> = sys
        .processes()
        .iter()
        .take(50)
        .map(|(pid, p)| ProcessInfo {
            pid: pid.as_u32(),
            name: p.name().to_string_lossy().to_string(),
            cpu: p.cpu_usage(),
            memory: p.memory() as f64 / 1024.0 / 1024.0,
            status: format!("{:?}", p.status()),
        })
        .collect();

    Ok(SystemInfo {
        hostname,
        os,
        kernel,
        cpu_brand: cpu,
        cpu_cores: cores,
        memory_total,
        memory_used,
        memory_percent,
        disk_total,
        disk_used,
        uptime,
        processes,
    })
}

pub async fn get_status() -> Result<DaemonStatus> {
    let pid = std::fs::read_to_string("/var/run/ravend.pid")
        .ok()
        .and_then(|s| s.trim().parse().ok());

    Ok(DaemonStatus {
        running: pid.is_some(),
        pid,
        version: env!("CARGO_PKG_VERSION"),
    })
}

pub async fn stop_daemon() -> Result<()> {
    let pid_path = if cfg!(target_family = "unix") {
        "/var/run/ravend.pid"
    } else {
        "C:\\ProgramData\\ravend\\ravend.pid"
    };
    let pid_str = std::fs::read_to_string(pid_path)?;
    let pid: u32 = pid_str.trim().parse()?;
    #[cfg(target_family = "unix")]
    nix::sys::signal::kill(
        nix::unistd::Pid::from_raw(pid as i32),
        nix::sys::signal::Signal::SIGTERM,
    )?;
    #[cfg(target_family = "windows")]
    {
        std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/F"])
            .status()?;
    }
    std::fs::remove_file(pid_path)?;
    println!("Daemon {} stopped", pid);
    Ok(())
}
