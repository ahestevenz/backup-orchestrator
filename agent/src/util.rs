// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! Small helpers: atomic writes, time stamps, name checks, errors.

use std::fs;
use std::io::{Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use nix::unistd::{chown, Gid, Uid};
use serde_json::{json, Value};
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

/// An error reported by a `ctl` command as `{"error": code, "message": text}`.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{code}: {message}")]
pub struct CtlError {
    pub code: String,
    pub message: String,
}

impl CtlError {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        CtlError {
            code: code.to_string(),
            message: message.into(),
        }
    }

    pub fn internal(message: impl Into<String>) -> Self {
        CtlError::new("internal", message)
    }

    pub fn to_json(&self) -> Value {
        json!({"error": self.code, "message": self.message})
    }
}

impl From<std::io::Error> for CtlError {
    fn from(e: std::io::Error) -> Self {
        CtlError::internal(e.to_string())
    }
}

impl From<anyhow::Error> for CtlError {
    fn from(e: anyhow::Error) -> Self {
        CtlError::internal(format!("{e:#}"))
    }
}

/// UTC time as RFC 3339 with a Z suffix, for result files.
pub fn now_rfc3339() -> String {
    let now = OffsetDateTime::now_utc()
        .replace_nanosecond(0)
        .unwrap_or(OffsetDateTime::now_utc());
    now.format(&Rfc3339).unwrap_or_default()
}

pub fn is_root() -> bool {
    nix::unistd::geteuid().is_root()
}

/// Account names: letters, digits, `_`, `.` and `-`, not starting with `.` or `-`.
pub fn valid_user_name(name: &str) -> bool {
    let b = name.as_bytes();
    !b.is_empty()
        && b.len() <= 32
        && (b[0].is_ascii_alphanumeric() || b[0] == b'_')
        && b.iter()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'.' | b'-'))
}

/// Module names: config modules are `[A-Za-z0-9_-]`, generated host-config
/// modules (`<user>-<host>`) may also contain `.` from the user name.
pub fn valid_module_name(name: &str) -> bool {
    let b = name.as_bytes();
    !b.is_empty()
        && b.len() <= 128
        && b[0] != b'.'
        && b.iter()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'.' | b'-'))
}

/// Host keys from the server config: `[a-z0-9][a-z0-9-]{0,62}`.
pub fn valid_host_key(name: &str) -> bool {
    let b = name.as_bytes();
    !b.is_empty()
        && b.len() <= 63
        && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit())
        && b.iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'-')
}

/// Write `data` to `path` through a temporary file in the same folder and a
/// rename, then set mode and (optionally) owner.
pub fn atomic_write(
    path: &Path,
    data: &[u8],
    mode: u32,
    owner: Option<(Uid, Gid)>,
) -> std::io::Result<()> {
    let dir = path.parent().unwrap_or_else(|| Path::new("."));
    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("file");
    let tmp = dir.join(format!(".{name}.{}.tmp", std::process::id()));
    let result = (|| {
        let mut f = fs::File::create(&tmp)?;
        f.write_all(data)?;
        f.sync_all()?;
        fs::set_permissions(&tmp, fs::Permissions::from_mode(mode))?;
        if let Some((uid, gid)) = owner {
            chown(&tmp, Some(uid), Some(gid)).map_err(std::io::Error::from)?;
        }
        fs::rename(&tmp, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&tmp);
    }
    result
}

/// Create a folder if missing and set its mode and owner.
pub fn ensure_dir(path: &Path, mode: u32, owner: Option<(Uid, Gid)>) -> std::io::Result<()> {
    fs::create_dir_all(path)?;
    fs::set_permissions(path, fs::Permissions::from_mode(mode))?;
    if let Some((uid, gid)) = owner {
        chown(path, Some(uid), Some(gid)).map_err(std::io::Error::from)?;
    }
    Ok(())
}

/// Read at most `limit` bytes; more is an error.
pub fn read_capped(reader: &mut dyn Read, limit: usize) -> Result<Vec<u8>, CtlError> {
    let mut buf = Vec::new();
    reader
        .take(limit as u64 + 1)
        .read_to_end(&mut buf)
        .map_err(|e| CtlError::new("bad_job", format!("cannot read the job: {e}")))?;
    if buf.len() > limit {
        return Err(CtlError::new("bad_job", "the job is larger than 1 MiB"));
    }
    Ok(buf)
}

/// The last `n` lines of a file.
pub fn tail_lines(path: &Path, n: usize) -> std::io::Result<Vec<String>> {
    let text = fs::read(path)?;
    let text = String::from_utf8_lossy(&text);
    let lines: Vec<&str> = text.lines().collect();
    let start = lines.len().saturating_sub(n);
    Ok(lines[start..].iter().map(|s| s.to_string()).collect())
}

/// Run a program and return (success, stdout, stderr).
pub fn run_cmd(program: &str, args: &[&str]) -> (bool, String, String) {
    match std::process::Command::new(program).args(args).output() {
        Ok(out) => (
            out.status.success(),
            String::from_utf8_lossy(&out.stdout).into_owned(),
            String::from_utf8_lossy(&out.stderr).into_owned(),
        ),
        Err(e) => (false, String::new(), e.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn user_names() {
        for ok in ["ariel", "sofia", "john.doe", "_svc", "a-b", "x1"] {
            assert!(valid_user_name(ok), "{ok}");
        }
        for bad in ["", ".x", "-x", "../etc", "a/b", "a b", &"x".repeat(33)] {
            assert!(!valid_user_name(bad), "{bad}");
        }
    }

    #[test]
    fn module_names() {
        assert!(valid_module_name("sofia-documents"));
        assert!(valid_module_name("john.doe-athena"));
        assert!(!valid_module_name(".probe"));
        assert!(!valid_module_name("../x"));
        assert!(!valid_module_name("a/b"));
    }

    #[test]
    fn host_keys() {
        assert!(valid_host_key("athena"));
        assert!(valid_host_key("b-c"));
        assert!(!valid_host_key("Athena"));
        assert!(!valid_host_key("-x"));
    }

    #[test]
    fn atomic_write_replaces() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("f.json");
        atomic_write(&p, b"one", 0o644, None).unwrap();
        atomic_write(&p, b"two", 0o600, None).unwrap();
        assert_eq!(fs::read_to_string(&p).unwrap(), "two");
        let mode = fs::metadata(&p).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
        assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
    }

    #[test]
    fn capped_read() {
        let mut small: &[u8] = b"abc";
        assert_eq!(read_capped(&mut small, 3).unwrap(), b"abc");
        let mut big: &[u8] = b"abcd";
        assert_eq!(read_capped(&mut big, 3).unwrap_err().code, "bad_job");
    }
}
