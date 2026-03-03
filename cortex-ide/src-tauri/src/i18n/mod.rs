//! Internationalization (i18n) module.
//!
//! Provides locale detection, available locale metadata, and Tauri commands
//! for the frontend i18n subsystem. Translations themselves live on the
//! frontend; this module handles system-level locale detection and
//! configuration plumbing.

use serde::{Deserialize, Serialize};
use tracing::info;

// ============================================================================
// Types
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LocaleInfo {
    pub code: String,
    pub name: String,
    pub native_name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nConfig {
    pub current_locale: String,
    pub available_locales: Vec<LocaleInfo>,
}

// ============================================================================
// Helpers
// ============================================================================

/// Detect the system locale.
///
/// On Unix, checks `LANG` first, then `LC_ALL`. On Windows, tries `LANG`/`LC_ALL`
/// env vars first, then falls back to the Win32 `GetUserDefaultLocaleName` API.
/// The raw value is normalised by stripping any encoding suffix (e.g. `.UTF-8`)
/// and region qualifier (e.g. `_US`), yielding a bare language code such as
/// `"en"` or `"fr"`. Returns `"en"` when no locale can be determined.
pub fn detect_system_locale() -> String {
    // Try environment variables first (works on all platforms)
    let raw = std::env::var("LANG")
        .or_else(|_| std::env::var("LC_ALL"))
        .unwrap_or_default();

    let from_env = parse_locale_code(&raw);
    if from_env != "en" || !raw.is_empty() {
        return from_env;
    }

    // On Windows, fall back to the Win32 API when env vars are not set
    #[cfg(target_os = "windows")]
    {
        if let Some(locale) = detect_windows_locale() {
            return locale;
        }
    }

    "en".to_string()
}

/// Detect locale on Windows using the Win32 GetUserDefaultLocaleName API.
#[cfg(target_os = "windows")]
#[allow(unsafe_code)]
fn detect_windows_locale() -> Option<String> {
    use windows_sys::Win32::Globalization::GetUserDefaultLocaleName;

    let mut buf = [0u16; 85]; // LOCALE_NAME_MAX_LENGTH is 85
    // SAFETY: `buf` is a valid, stack-allocated buffer of known size and
    // `GetUserDefaultLocaleName` writes at most `buf.len()` wide chars
    // including a null terminator.
    let len = unsafe { GetUserDefaultLocaleName(buf.as_mut_ptr(), buf.len() as i32) };
    if len > 0 {
        let locale_str = String::from_utf16_lossy(&buf[..(len as usize).saturating_sub(1)]);
        // Windows returns BCP 47 tags like "en-US", extract the language part
        let language = locale_str.split('-').next().unwrap_or(&locale_str);
        if !language.is_empty() {
            return Some(language.to_lowercase());
        }
    }
    None
}

fn parse_locale_code(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed == "C" || trimmed == "POSIX" {
        return "en".to_string();
    }

    let without_encoding = trimmed.split('.').next().unwrap_or(trimmed);
    let language = without_encoding
        .split('_')
        .next()
        .unwrap_or(without_encoding);

    if language.is_empty() {
        "en".to_string()
    } else {
        language.to_lowercase()
    }
}

/// Returns the list of locales supported by the application.
pub fn get_available_locales() -> Vec<LocaleInfo> {
    vec![
        LocaleInfo {
            code: "en".to_string(),
            name: "English".to_string(),
            native_name: "English".to_string(),
        },
        LocaleInfo {
            code: "fr".to_string(),
            name: "French".to_string(),
            native_name: "Français".to_string(),
        },
        LocaleInfo {
            code: "zh".to_string(),
            name: "Chinese".to_string(),
            native_name: "中文".to_string(),
        },
        LocaleInfo {
            code: "ja".to_string(),
            name: "Japanese".to_string(),
            native_name: "日本語".to_string(),
        },
        LocaleInfo {
            code: "es".to_string(),
            name: "Spanish".to_string(),
            native_name: "Español".to_string(),
        },
        LocaleInfo {
            code: "de".to_string(),
            name: "German".to_string(),
            native_name: "Deutsch".to_string(),
        },
    ]
}

// ============================================================================
// Tauri Commands
// ============================================================================

#[tauri::command]
pub async fn i18n_detect_locale() -> Result<String, String> {
    let locale = detect_system_locale();
    info!(locale = %locale, "Detected system locale");
    Ok(locale)
}

#[tauri::command]
pub async fn i18n_get_config() -> Result<I18nConfig, String> {
    let current_locale = detect_system_locale();
    let available_locales = get_available_locales();
    info!(locale = %current_locale, count = available_locales.len(), "Built i18n config");
    Ok(I18nConfig {
        current_locale,
        available_locales,
    })
}

fn is_supported_locale(code: &str) -> bool {
    get_available_locales().iter().any(|l| l.code == code)
}

#[tauri::command]
pub async fn i18n_load_translations(locale: String) -> Result<serde_json::Value, String> {
    if !is_supported_locale(&locale) {
        return Err(format!("Unsupported locale: {}", locale));
    }
    info!(locale = %locale, "Loading translations (frontend-managed)");
    Ok(serde_json::json!({}))
}
