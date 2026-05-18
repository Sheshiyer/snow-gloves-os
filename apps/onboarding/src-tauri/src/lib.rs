use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::{AppHandle, Emitter};

#[derive(Serialize)]
struct DoctorCheck { status: String, label: String }

#[derive(Serialize)]
struct DoctorReport {
    ok: bool, total: usize, passed: usize, failed: usize,
    checks: Vec<DoctorCheck>, raw: String,
}

fn repo_root() -> PathBuf {
    // apps/onboarding/src-tauri → repo root is two levels up
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..").canonicalize()
        .unwrap_or_else(|_| PathBuf::from("."))
}

fn strip_ansi(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\u{1b}' {
            // ESC [ ... m
            while let Some(&n) = chars.peek() { chars.next(); if n == 'm' { break; } }
        } else { out.push(c); }
    }
    out
}

#[tauri::command]
fn run_doctor() -> Result<DoctorReport, String> {
    let root = repo_root();
    let out = Command::new("bash").arg("scripts/doctor.sh").current_dir(&root)
        .output().map_err(|e| format!("failed to spawn doctor: {e}"))?;
    let raw = strip_ansi(&format!("{}{}",
        String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr)));
    let mut checks = Vec::new();
    let (mut passed, mut failed) = (0usize, 0usize);
    for line in raw.lines() {
        let t = line.trim_start();
        let (status, label) = if t.starts_with("✓ ") { passed += 1; ("ok", t.trim_start_matches("✓ ")) }
            else if t.starts_with("✗ ") { failed += 1; ("err", t.trim_start_matches("✗ ")) }
            else if t.starts_with("! ") { ("warn", t.trim_start_matches("! ")) }
            else { continue; };
        checks.push(DoctorCheck { status: status.into(), label: label.into() });
    }
    let total = checks.len();
    Ok(DoctorReport { ok: out.status.success() && failed == 0, total, passed, failed, checks, raw })
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct CreateTenantArgs {
    slug: String,
    business: String,
    company_id: Option<String>,
    sources: Vec<String>,
}

#[derive(Serialize)]
struct CreateTenantResult { path: String, sources_added: usize, company_bound: bool }

fn write_sources_yaml(root: &Path, slug: &str, sources: &[String]) -> std::io::Result<()> {
    let p = root.join("tenants").join(slug).join("sources.yaml");
    let mut s = format!("tenant: {slug}\nsources:\n");
    for src in sources { s.push_str(&format!("  - path: {src}\n    type: filesystem\n")); }
    if sources.is_empty() { s.push_str("  []\n"); }
    std::fs::write(p, s)
}

fn patch_company_id(root: &Path, slug: &str, cid: &str) -> std::io::Result<()> {
    let p = root.join("tenants").join(slug).join("MANIFEST.yaml");
    let txt = std::fs::read_to_string(&p)?;
    let new = txt.replace("company_id: \"\"", &format!("company_id: \"{cid}\""));
    std::fs::write(p, new)
}

#[tauri::command]
fn create_tenant(args: CreateTenantArgs) -> Result<CreateTenantResult, String> {
    let root = repo_root();
    let tdir = root.join("tenants").join(&args.slug);
    if tdir.exists() {
        return Err(format!("tenant already exists: {}", tdir.display()));
    }
    let out = Command::new("bash")
        .arg("scripts/tenant_new.sh").arg(&args.slug).arg(&args.business)
        .current_dir(&root).output()
        .map_err(|e| format!("spawn failed: {e}"))?;
    if !out.status.success() {
        return Err(format!("tenant_new failed: {}", String::from_utf8_lossy(&out.stderr)));
    }
    write_sources_yaml(&root, &args.slug, &args.sources)
        .map_err(|e| format!("sources.yaml write: {e}"))?;
    let mut bound = false;
    if let Some(cid) = args.company_id.as_ref().filter(|s| !s.is_empty()) {
        patch_company_id(&root, &args.slug, cid).map_err(|e| format!("manifest patch: {e}"))?;
        bound = true;
    }
    Ok(CreateTenantResult {
        path: tdir.display().to_string(),
        sources_added: args.sources.len(),
        company_bound: bound,
    })
}

#[tauri::command]
fn list_tenants() -> Result<Vec<String>, String> {
    let dir = repo_root().join("tenants");
    if !dir.exists() { return Ok(vec![]); }
    let mut out = Vec::new();
    for e in std::fs::read_dir(&dir).map_err(|e| e.to_string())? {
        let e = e.map_err(|e| e.to_string())?;
        if e.file_type().map(|t| t.is_dir()).unwrap_or(false) {
            if let Some(n) = e.file_name().to_str() {
                if !n.starts_with('_') { out.push(n.into()); }
            }
        }
    }
    Ok(out)
}

#[tauri::command]
async fn run_smoke(app: AppHandle) -> Result<(), String> {
    use std::io::{BufRead, BufReader};
    use std::process::Stdio;
    let root = repo_root();
    let mut child = Command::new("make").arg("smoke").current_dir(&root)
        .stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn().map_err(|e| format!("spawn make smoke: {e}"))?;
    if let Some(out) = child.stdout.take() {
        let app2 = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(out).lines().flatten() {
                let _ = app2.emit("smoke-line", line);
            }
        });
    }
    if let Some(err) = child.stderr.take() {
        let app2 = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(err).lines().flatten() {
                let _ = app2.emit("smoke-line", format!("[stderr] {line}"));
            }
        });
    }
    let status = child.wait().map_err(|e| format!("wait: {e}"))?;
    let _ = app.emit("smoke-line",
        format!("\n— smoke {}", if status.success() {"complete ✅"} else {"FAILED ✗"}));
    Ok(())
}

#[tauri::command]
fn open_repo() -> Result<(), String> {
    let root = repo_root();
    #[cfg(target_os = "macos")] let cmd = ("open", root.display().to_string());
    #[cfg(target_os = "linux")] let cmd = ("xdg-open", root.display().to_string());
    #[cfg(target_os = "windows")] let cmd = ("explorer", root.display().to_string());
    Command::new(cmd.0).arg(cmd.1).spawn().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn quit_app(app: AppHandle) { app.exit(0); }

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![
            run_doctor, create_tenant, list_tenants, run_smoke, open_repo, quit_app
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
