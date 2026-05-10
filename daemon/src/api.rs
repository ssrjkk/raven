use anyhow::Result;
use axum::{
    routing::get,
    Router,
    Json,
    extract::State,
};
use crate::system;
use crate::health;

#[derive(Clone)]
struct AppState {
    start_time: std::time::Instant,
}

#[derive(Serialize)]
struct RootResponse {
    service: &'static str,
    version: &'static str,
    uptime_secs: u64,
}

pub async fn serve(port: u16) -> Result<()> {
    let state = AppState {
        start_time: std::time::Instant::now(),
    };

    let app = Router::new()
        .route("/health", get(handle_health))
        .route("/status", get(handle_status))
        .route("/info", get(handle_info))
        .with_state(state);

    let addr = format!("0.0.0.0:{}", port);
    log::info!("ravend listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}

async fn handle_health() -> Json<health::HealthReport> {
    let report = health::check_all().await.unwrap_or_else(|e| health::HealthReport {
        status: health::HealthStatus::Unhealthy,
        checks: vec![],
        timestamp: "error".into(),
    });
    Json(report)
}

async fn handle_status() -> Json<system::DaemonStatus> {
    let status = system::get_status().await.unwrap_or_else(|_| system::DaemonStatus {
        running: false,
        pid: None,
        version: "unknown",
    });
    Json(status)
}

async fn handle_info() -> Json<system::SystemInfo> {
    let info = system::get_system_info().await.unwrap_or_else(|_| system::SystemInfo {
        hostname: "unknown".into(),
        os: "unknown".into(),
        kernel: "unknown".into(),
        cpu_brand: "unknown".into(),
        cpu_cores: 0,
        memory_total: 0,
        memory_used: 0,
        memory_percent: 0.0,
        disk_total: 0,
        disk_used: 0,
        uptime: 0,
        processes: vec![],
    });
    Json(info)
}
