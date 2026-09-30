// Verba desktop shell: spawn the FastAPI sidecar, wait for its readiness
// line on stdout AND for the TCP port to answer, then open the window.
// The sidecar entrypoint (verba/desktop/sidecar_entry.py) prints
// "VERBA_READY port=<n>" before uvicorn binds, so stdout alone is not enough.
//
// Lifecycle patterns ported from the Osusume reference app: single-instance
// lock (a second launch would race for the port and the SQLite file),
// health polling before the window opens, and a graceful shutdown on quit —
// SIGTERM alone skips uvicorn's exit handlers (and always does on Windows),
// so the shell POSTs /api/shutdown first and only then kills the child.
// Dropping the CommandChild does NOT terminate the process either.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Write;
use std::sync::Mutex;
use std::time::Duration;

use tauri::Manager;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// The running sidecar handle plus the port it announced.
struct SidecarHandle(Mutex<Option<(CommandChild, u16)>>);

fn request_shutdown(port: u16) {
    // Minimal raw HTTP: no HTTP client dependency for one best-effort call.
    if let Ok(mut stream) = std::net::TcpStream::connect(("127.0.0.1", port)) {
        let _ = stream.write_all(
            b"POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        );
        let _ = stream.flush();
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.unminimize();
                let _ = win.set_focus();
            }
        }))
        .manage(SidecarHandle(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let sidecar = handle
                    .shell()
                    .sidecar("verba-server")
                    .expect("verba-server sidecar is missing from the bundle");
                let (mut rx, child) = sidecar.spawn().expect("failed to spawn verba-server");

                let mut port = String::from("8000");
                while let Some(event) = rx.recv().await {
                    if let CommandEvent::Stdout(line) = event {
                        let text = String::from_utf8_lossy(&line);
                        if let Some(rest) = text.trim().strip_prefix("VERBA_READY port=") {
                            port = rest.trim().to_string();
                            break;
                        }
                    }
                }

                // stdout prints before uvicorn binds: poll the port (up to 15s)
                let port_num: u16 = port.parse().unwrap_or(8000);
                for _ in 0..50 {
                    if std::net::TcpStream::connect(("127.0.0.1", port_num)).is_ok() {
                        break;
                    }
                    tokio::time::sleep(Duration::from_millis(300)).await;
                }

                handle
                    .state::<SidecarHandle>()
                    .0
                    .lock()
                    .unwrap()
                    .replace((child, port_num));

                let url: tauri::Url = format!("http://127.0.0.1:{port}")
                    .parse()
                    .expect("valid url");
                let win = tauri::WebviewWindowBuilder::new(&handle, "main", tauri::WebviewUrl::External(url))
                    .title("Verba")
                    .inner_size(1200.0, 780.0)
                    .min_inner_size(375.0, 600.0)
                    .build()
                    .expect("failed to build main window");
                let _ = win.set_focus();
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Verba")
        .run(|app, event| {
            // Graceful stop then hard kill. Covers both the window-closed quit
            // (ExitRequested) and the actual exit (Exit, re-entry safe via take).
            if matches!(
                event,
                tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
            ) {
                // take() first: the MutexGuard temporary must not outlive the if-let
                let taken = app.state::<SidecarHandle>().0.lock().unwrap().take();
                if let Some((child, port)) = taken {
                    request_shutdown(port);
                    std::thread::sleep(Duration::from_millis(400));
                    let _ = child.kill();
                }
            }
        });
}
