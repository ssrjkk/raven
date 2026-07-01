#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Command, Child, Stdio};
use std::sync::Mutex;
use tauri::Manager;

struct AppState {
  backend: Mutex<Option<Child>>,
}

fn start_backend(state: &AppState) {
  let mut backend = state.backend.lock().unwrap();
  if backend.is_some() {
    return;
  }
  let child = Command::new("python")
    .args(["-m", "main", "--no-web", "--flow-port", "18789"])
    .stdout(Stdio::null())
    .stderr(Stdio::null())
    .spawn();
  match child {
    Ok(c) => {
      *backend = Some(c);
      println!("Raven backend started (pid={})", c.id());
    }
    Err(e) => eprintln!("Failed to start backend: {}", e),
  }
}

fn stop_backend(state: &AppState) {
  let mut backend = state.backend.lock().unwrap();
  if let Some(mut c) = backend.take() {
    let _ = c.kill();
    let _ = c.wait();
    println!("Raven backend stopped");
  }
}

#[tauri::command]
fn get_flow_url() -> String {
  "http://localhost:18789".to_string()
}

fn main() {
  tauri::Builder::default()
    .manage(AppState {
      backend: Mutex::new(None),
    })
    .invoke_handler(tauri::generate_handler![get_flow_url])
    .setup(|app| {
      let state = app.state::<AppState>();
      start_backend(&state);
      Ok(())
    })
    .on_window_event(|window, event| {
      if let tauri::WindowEvent::Destroyed = event {
        let state = window.state::<AppState>();
        stop_backend(&state);
      }
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
