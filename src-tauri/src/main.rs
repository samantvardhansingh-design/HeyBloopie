// Prevents additional console window on Windows in release builds
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager,
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

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            // Context menu for System Tray
            let quit_item = MenuItem::with_id(app, "quit", "Quit HeyBloopie", true, None::<&str>)?;
            let toggle_item = MenuItem::with_id(app, "toggle", "Open / Close (Ctrl+Shift+Space)", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&toggle_item, &quit_item])?;

            // Build System Tray (Grey when not configured, Blue when ready)
            let _tray = TrayIconBuilder::new()
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "quit" => {
                        app.exit(0);
                    }
                    "toggle" => {
                        toggle_overlay(app);
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
        .run(tauri::generate_context!())
        .expect("error while running HeyBloopie application");
}
