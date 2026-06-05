use serde::Serialize;
use anyhow::Result;

#[derive(Serialize)]
pub struct HealthReport {
    pub status: HealthStatus,
    pub checks: Vec<HealthCheck>,
    pub timestamp: String,
}

#[derive(Serialize)]
pub enum HealthStatus {
    Healthy,
    Degraded,
    Unhealthy,
}

#[derive(Serialize)]
pub struct HealthCheck {
    pub name: String,
    pub status: String,
    pub detail: String,
    pub duration_ms: u64,
}

pub async fn check_all() -> Result<HealthReport> {
    let mut checks = Vec::new();

    // CPU check
    let start = std::time::Instant::now();
    let cpu_ok = check_cpu().await;
    checks.push(HealthCheck {
        name: "cpu".into(),
        status: if cpu_ok { "pass".into() } else { "warn".into() },
        detail: if cpu_ok { "CPU load normal".into() } else { "High CPU load detected".into() },
        duration_ms: start.elapsed().as_millis() as u64,
    });

    // Memory check
    let start = std::time::Instant::now();
    let mem_ok = check_memory().await;
    checks.push(HealthCheck {
        name: "memory".into(),
        status: if mem_ok { "pass".into() } else { "warn".into() },
        detail: if mem_ok { "Memory usage normal".into() } else { "Low memory".into() },
        duration_ms: start.elapsed().as_millis() as u64,
    });

    // Disk check
    let start = std::time::Instant::now();
    let disk_ok = check_disk().await;
    checks.push(HealthCheck {
        name: "disk".into(),
        status: if disk_ok { "pass".into() } else { "warn".into() },
        detail: if disk_ok { "Disk space OK".into() } else { "Low disk space".into() },
        duration_ms: start.elapsed().as_millis() as u64,
    });

    // API check
    let start = std::time::Instant::now();
    let api_ok = check_api().await;
    checks.push(HealthCheck {
        name: "raven_api".into(),
        status: if api_ok.0 { "pass".into() } else { "fail".into() },
        detail: api_ok.1,
        duration_ms: start.elapsed().as_millis() as u64,
    });

    let failed = checks.iter().filter(|c| c.status == "fail").count();
    let status = if failed > 0 {
        HealthStatus::Unhealthy
    } else if checks.iter().any(|c| c.status == "warn") {
        HealthStatus::Degraded
    } else {
        HealthStatus::Healthy
    };

    Ok(HealthReport {
        status,
        checks,
        timestamp: chrono_now(),
    })
}

fn chrono_now() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let dur = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
    format!("{}", dur.as_secs())
}

async fn check_cpu() -> bool {
    let mut sys = sysinfo::System::new();
    sys.refresh_cpu();
    sys.cpus().iter().any(|c| c.cpu_usage() < 90.0)
}

async fn check_memory() -> bool {
    let mut sys = sysinfo::System::new();
    sys.refresh_memory();
    let pct = sys.used_memory() as f64 / sys.total_memory() as f64 * 100.0;
    pct < 90.0
}

async fn check_disk() -> bool {
    let disk = sysinfo::Disks::new();
    for d in &disk {
        let avail_pct = d.available_space() as f64 / d.total_space() as f64 * 100.0;
        if avail_pct < 5.0 {
            return false;
        }
    }
    true
}

async fn check_api() -> (bool, String) {
    match reqwest::get("http://localhost:18888/api/status").await {
        Ok(resp) => {
            if resp.status().is_success() {
                (true, "API reachable".into())
            } else {
                (false, format!("API returned {}", resp.status()))
            }
        }
        Err(e) => (false, format!("API unreachable: {}", e)),
    }
}
