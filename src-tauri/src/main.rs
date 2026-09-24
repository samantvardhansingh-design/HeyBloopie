// Prevents additional console window on Windows in release builds
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::Command;
use tauri::{
    image::Image,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

fn toggle_overlay(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

fn open_overlay(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
        let _ = app.emit("open_overlay", ());
    }
}

fn open_settings(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
        let _ = app.emit("open_settings", ());
    }
}

fn run_python_cmd(code: &str) -> Result<String, String> {
    let output = Command::new("python")
        .args(["-c", code])
        .output()
        .map_err(|e| format!("Failed to invoke python: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

#[tauri::command]
fn check_onboarding_needed() -> bool {
    let script = "from python import memory; val = memory.get_preference('active_provider'); print('false' if val else 'true')";
    match run_python_cmd(script) {
        Ok(res) => res.to_lowercase() == "true",
        Err(_) => true,
    }
}

#[tauri::command]
fn set_tray_ready(app: AppHandle, ready: bool) -> Result<(), String> {
    if let Some(tray) = app.tray_by_id("main_tray") {
        let icon_bytes = if ready {
            include_bytes!("../icons/tray-blue.png").to_vec()
        } else {
            include_bytes!("../icons/tray-grey.png").to_vec()
        };
        let tooltip = if ready {
            "HeyBloopie (Ready)"
        } else {
            "HeyBloopie (Not Configured)"
        };
        if let Ok(img) = Image::from_bytes(&icon_bytes) {
            let _ = tray.set_icon(Some(img));
        }
        let _ = tray.set_tooltip(Some(tooltip));
    }
    Ok(())
}

#[tauri::command]
fn validate_provider_key(provider: String, key: String) -> Result<serde_json::Value, String> {
    let script = format!(
        "import asyncio, json; from python.provider import validate_provider_key; res = asyncio.run(validate_provider_key({:?}, {:?})); print(json.dumps(res))",
        provider, key
    );
    let output = run_python_cmd(&script)?;
    serde_json::from_str(&output).map_err(|e| e.to_string())
}

#[tauri::command]
fn check_ollama() -> Result<serde_json::Value, String> {
    let script = "import asyncio, json; from python.provider import check_ollama; res = asyncio.run(check_ollama()); print(json.dumps(res))";
    let output = run_python_cmd(script)?;
    serde_json::from_str(&output).map_err(|e| e.to_string())
}

#[tauri::command]
fn get_preferences() -> Result<serde_json::Value, String> {
    let script = "import json; from python import memory; print(json.dumps(memory.get_all_preferences()))";
    let output = run_python_cmd(script)?;
    serde_json::from_str(&output).map_err(|e| e.to_string())
}

#[tauri::command]
fn set_preference(key: String, value: String) -> Result<bool, String> {
    let script = format!(
        "from python import memory; memory.set_preference({:?}, {:?}); print('true')",
        key, value
    );
    let res = run_python_cmd(&script)?;
    Ok(res == "true")
}

#[tauri::command]
fn get_action_log(limit: Option<usize>) -> Result<serde_json::Value, String> {
    let lim = limit.unwrap_or(50);
    let script = format!(
        "import json; from python import memory; tasks = memory.get_recent_tasks(limit={}); print(json.dumps(tasks))",
        lim
    );
    let output = run_python_cmd(&script)?;
    serde_json::from_str(&output).map_err(|e| e.to_string())
}

#[tauri::command]
fn export_action_log(path: Option<String>) -> Result<serde_json::Value, String> {
    let script = if let Some(p) = path {
        format!(
            "import json; from python import memory; memory.export_log({:?}); print(json.dumps({{'success': True, 'path': {:?}}}))",
            p, p
        )
    } else {
        "import json, os; from python import memory; default_p = os.path.expanduser('~/heybloopie_log_export.json'); memory.export_log(default_p); print(json.dumps({'success': True, 'path': default_p}))".to_string()
    };
    let output = run_python_cmd(&script)?;
    serde_json::from_str(&output).map_err(|e| e.to_string())
}

#[tauri::command]
fn start_wake_word() -> bool {
    let script = "import threading; from python import core; threading.Thread(target=core.start_wake_word_service, daemon=True).start(); print('true')";
    let _ = run_python_cmd(script);
    true
}

#[tauri::command]
fn run_core(request: String) -> Result<serde_json::Value, String> {
    let script = format!(
        "import asyncio, json, dataclasses; from python import core; r = asyncio.run(core.run({:?})); print(json.dumps(dataclasses.asdict(r)))",
        request
    );
    let output = run_python_cmd(&script)?;
    serde_json::from_str(&output).map_err(|e| e.to_string())
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            // Context menu for System Tray:
            // 1. "Open HeyBloopie" (shows the overlay)
            // 2. "Settings" (opens the settings window)
            // 3. "Check for Updates" (calls the updater)
            // 4. "Quit"
            let open_item = MenuItem::with_id(app, "open", "Open HeyBloopie", true, None::<&str>)?;
            let settings_item = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
            let update_item = MenuItem::with_id(app, "update", "Check for Updates", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;

            let tray_menu = Menu::with_items(app, &[&open_item, &settings_item, &update_item, &quit_item])?;

            // Build System Tray (Grey when not configured, Blue when ready)
            let _tray = TrayIconBuilder::with_id("main_tray")
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => {
                        open_overlay(app);
                    }
                    "settings" => {
                        open_settings(app);
                    }
                    "update" => {
                        let _ = app.emit("check_updates", ());
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        toggle_overlay(app);
                    }
                })
                .build(app)?;

            // Register Global Hotkey: Ctrl+Shift+Space
            let hotkey: Shortcut = "Ctrl+Shift+Space".parse().expect("Valid shortcut syntax");
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_handler(move |app, shortcut, event| {
                        if shortcut == &hotkey && event.state() == ShortcutState::Pressed {
                            toggle_overlay(app);
                        }
                    })
                    .build(),
            )?;

            app.global_shortcut().register(hotkey)?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            check_onboarding_needed,
            set_tray_ready,
            validate_provider_key,
            check_ollama,
            get_preferences,
            set_preference,
            get_action_log,
            export_action_log,
            start_wake_word,
            run_core
        ])
        .run(tauri::generate_context!())
        .expect("error while running HeyBloopie application");
}
