// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! Checks run before a backup and by probe jobs (CLAUDE.md §5.5, D-40, D-55).

use std::collections::HashSet;
use std::io::ErrorKind as IoKind;
use std::path::{Path, PathBuf};

use crate::job::{ModuleJob, ModuleType};
use crate::paths::Os;
use crate::result::{ErrorKind, Fda};

pub const TCC_DB: &str = "/Library/Application Support/com.apple.TCC/TCC.db";
/// Entries that do not make a folder "not empty" (D-55).
const IGNORED_ENTRIES: [&str; 2] = [".DS_Store", ".localized"];

/// Full Disk Access: can this process open the system TCC database?
pub fn fda(os: Os) -> Fda {
    match os {
        Os::Linux => Fda::NotApplicable,
        Os::MacOs => match std::fs::File::open(TCC_DB) {
            Ok(_) => Fda::Granted,
            Err(_) => Fda::Denied,
        },
    }
}

/// Answers "is this path a mount point?". A trait so tests can fake it.
pub trait Mounts {
    fn is_mount_point(&self, path: &Path) -> bool;
}

/// The real mount table.
#[cfg_attr(target_os = "macos", allow(dead_code))]
pub struct SystemMounts {
    linux_points: HashSet<PathBuf>,
}

impl SystemMounts {
    pub fn load() -> SystemMounts {
        let linux_points = std::fs::read_to_string("/proc/self/mountinfo")
            .map(|t| parse_mountinfo(&t))
            .unwrap_or_default();
        SystemMounts { linux_points }
    }
}

impl Mounts for SystemMounts {
    fn is_mount_point(&self, path: &Path) -> bool {
        #[cfg(target_os = "macos")]
        {
            macos_mount_point(path)
        }
        #[cfg(not(target_os = "macos"))]
        {
            self.linux_points.contains(path)
        }
    }
}

/// macOS: `statfs` on the path reports that same path as its mount point.
#[cfg(target_os = "macos")]
fn macos_mount_point(path: &Path) -> bool {
    use std::ffi::{CStr, CString};
    use std::os::unix::ffi::OsStrExt;
    let Ok(c) = CString::new(path.as_os_str().as_bytes()) else {
        return false;
    };
    let mut st: libc::statfs = unsafe { std::mem::zeroed() };
    // SAFETY: `c` is a valid NUL-terminated string and `st` a properly sized buffer.
    if unsafe { libc::statfs(c.as_ptr(), &mut st) } != 0 {
        return false;
    }
    // SAFETY: f_mntonname is a NUL-terminated C string filled in by statfs.
    let on = unsafe { CStr::from_ptr(st.f_mntonname.as_ptr()) };
    on.to_bytes() == path.as_os_str().as_bytes()
}

/// Mount points from `/proc/self/mountinfo` (5th field, with octal escapes).
pub fn parse_mountinfo(text: &str) -> HashSet<PathBuf> {
    text.lines()
        .filter_map(|l| l.split(' ').nth(4))
        .map(|p| PathBuf::from(unescape_octal(p)))
        .collect()
}

fn unescape_octal(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'\\'
            && i + 3 < b.len()
            && b[i + 1..i + 4].iter().all(|c| (b'0'..=b'7').contains(c))
        {
            let v = (b[i + 1] - b'0') * 64 + (b[i + 2] - b'0') * 8 + (b[i + 3] - b'0');
            out.push(v);
            i += 4;
        } else {
            out.push(b[i]);
            i += 1;
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// External-drive roots per OS (D-40).
pub fn external_roots(os: Os) -> &'static [&'static str] {
    match os {
        Os::MacOs => &["/Volumes"],
        Os::Linux => &["/media", "/run/media", "/mnt"],
    }
}

/// `None` when the path is not on an external drive; otherwise whether that
/// drive is really mounted. An existing folder is not enough (D-55).
pub fn external_drive_mounted(src: &str, os: Os, mounts: &dyn Mounts) -> Option<bool> {
    let path = Path::new(src);
    let root = external_roots(os)
        .iter()
        .map(Path::new)
        .find(|r| path.starts_with(r) && path != *r)?;
    match os {
        // The drive is /Volumes/<name>.
        Os::MacOs => {
            let name = path.strip_prefix(root).ok()?.components().next()?;
            Some(mounts.is_mount_point(&root.join(name)))
        }
        // The path itself or one of its ancestors below the root is a mount point.
        Os::Linux => Some(
            path.ancestors()
                .take_while(|a| *a != root)
                .any(|a| mounts.is_mount_point(a)),
        ),
    }
}

/// The name of the drive, for messages: `/Volumes/PhotoArchive` → `PhotoArchive`.
pub fn drive_name(src: &str, os: Os) -> String {
    let path = Path::new(src);
    for root in external_roots(os) {
        if let Ok(rest) = path.strip_prefix(root) {
            let mut parts = rest.components();
            // Linux: /media/<user>/<label>/… and /run/media/<user>/<label>/…
            let first = parts.next();
            let second = parts.next();
            let pick = match (os, *root) {
                (Os::Linux, "/media") | (Os::Linux, "/run/media") => second.or(first),
                _ => first,
            };
            if let Some(p) = pick {
                return p.as_os_str().to_string_lossy().into_owned();
            }
        }
    }
    src.to_string()
}

fn errno_kind(e: &std::io::Error, os: Os) -> ErrorKind {
    match (e.kind(), e.raw_os_error()) {
        (IoKind::NotFound, _) => ErrorKind::Missing,
        (_, Some(libc::ENOTDIR)) => ErrorKind::Missing,
        (_, Some(libc::EPERM)) if os == Os::MacOs => ErrorKind::Tcc,
        (_, Some(libc::EPERM)) | (_, Some(libc::EACCES)) => ErrorKind::Permission,
        _ => ErrorKind::Other,
    }
}

/// Check one module's source. `Ok(())` means ready to back up.
pub fn check_module(
    m: &ModuleJob,
    home: &Path,
    os: Os,
    mounts: &dyn Mounts,
) -> Result<(), (ErrorKind, String)> {
    match m.kind {
        ModuleType::HostConfig => std::fs::read_dir(home).map(|_| ()).map_err(|e| {
            (
                errno_kind(&e, os),
                format!("cannot read {}: {e}", home.display()),
            )
        }),
        ModuleType::Path => {
            let src = m.src_path.as_deref().unwrap_or("");
            if external_drive_mounted(src, os, mounts) == Some(false) {
                return Err((
                    ErrorKind::DriveMissing,
                    format!(
                        "the external drive {} is not connected",
                        drive_name(src, os)
                    ),
                ));
            }
            let entries = std::fs::read_dir(src)
                .map_err(|e| (errno_kind(&e, os), format!("cannot read {src}: {e}")))?;
            if m.expect_nonempty {
                let any = entries.filter_map(|e| e.ok()).any(|e| {
                    let n = e.file_name();
                    !IGNORED_ENTRIES.iter().any(|ign| n == *ign)
                });
                if !any {
                    return Err((
                        ErrorKind::SourceEmpty,
                        format!("{src} is empty, but its backup is not"),
                    ));
                }
            }
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct FakeMounts(Vec<&'static str>);
    impl Mounts for FakeMounts {
        fn is_mount_point(&self, path: &Path) -> bool {
            self.0.iter().any(|p| Path::new(p) == path)
        }
    }

    #[test]
    fn mac_volumes() {
        let m = FakeMounts(vec!["/", "/Volumes/PhotoArchive"]);
        assert_eq!(
            external_drive_mounted("/Volumes/PhotoArchive/Photos", Os::MacOs, &m),
            Some(true)
        );
        let none = FakeMounts(vec!["/"]);
        assert_eq!(
            external_drive_mounted("/Volumes/PhotoArchive/Photos", Os::MacOs, &none),
            Some(false)
        );
        assert_eq!(
            external_drive_mounted("/Users/sofia/Documents", Os::MacOs, &none),
            None
        );
        assert_eq!(
            drive_name("/Volumes/PhotoArchive/Photos", Os::MacOs),
            "PhotoArchive"
        );
    }

    #[test]
    fn linux_roots() {
        let m = FakeMounts(vec![
            "/",
            "/media/ariel/PhotoArchive",
            "/mnt/photos",
            "/run/media/ariel/X",
        ]);
        for (src, expect) in [
            ("/media/ariel/PhotoArchive/Photos", Some(true)),
            ("/mnt/photos/2019", Some(true)),
            ("/mnt/photos", Some(true)),
            ("/run/media/ariel/X/a", Some(true)),
            ("/mnt/other/2019", Some(false)),
            ("/media/ariel/Gone/Photos", Some(false)),
            ("/home/ariel/exports", None),
        ] {
            assert_eq!(external_drive_mounted(src, Os::Linux, &m), expect, "{src}");
        }
        // /mnt itself being a mount point does not count.
        let only_root = FakeMounts(vec!["/mnt"]);
        assert_eq!(
            external_drive_mounted("/mnt/photos/x", Os::Linux, &only_root),
            Some(false)
        );
        assert_eq!(
            drive_name("/media/ariel/PhotoArchive/Photos", Os::Linux),
            "PhotoArchive"
        );
        assert_eq!(drive_name("/mnt/photos/2019", Os::Linux), "photos");
    }

    #[test]
    fn mountinfo_parsing() {
        let text = "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n\
                    40 22 8:17 / /media/ariel/Photo\\040Archive rw - ext4 /dev/sdb1 rw\n";
        let set = parse_mountinfo(text);
        assert!(set.contains(Path::new("/")));
        assert!(set.contains(Path::new("/media/ariel/Photo Archive")));
    }

    fn module(src: &str, expect_nonempty: bool) -> ModuleJob {
        ModuleJob {
            name: "m".into(),
            kind: ModuleType::Path,
            src_path: Some(src.into()),
            excludes: vec![],
            expect_nonempty,
        }
    }

    #[test]
    fn existing_but_unmounted_drive_folder_is_drive_missing() {
        // D-55: an empty folder where the drive is normally mounted.
        let dir = tempfile::tempdir().unwrap();
        let mnt = dir.path().join("mnt");
        std::fs::create_dir_all(mnt.join("photos/Photos")).unwrap();
        // Pretend `<tmp>/mnt` is the Linux /mnt root by checking the logic directly.
        let m = FakeMounts(vec![]);
        assert_eq!(
            external_drive_mounted("/mnt/photos/Photos", Os::Linux, &m),
            Some(false)
        );
        let r = check_module(
            &module("/mnt/photos/Photos", false),
            dir.path(),
            Os::Linux,
            &m,
        );
        assert_eq!(r.unwrap_err().0, ErrorKind::DriveMissing);
    }

    #[test]
    fn source_checks() {
        let dir = tempfile::tempdir().unwrap();
        let src = dir.path().join("Documents");
        let m = FakeMounts(vec![]);
        let p = src.to_str().unwrap();
        // Missing.
        let r = check_module(&module(p, false), dir.path(), Os::Linux, &m);
        assert_eq!(r.unwrap_err().0, ErrorKind::Missing);
        // Empty: fine unless the backup already holds data.
        std::fs::create_dir(&src).unwrap();
        std::fs::write(src.join(".DS_Store"), b"x").unwrap();
        assert!(check_module(&module(p, false), dir.path(), Os::Linux, &m).is_ok());
        let r = check_module(&module(p, true), dir.path(), Os::Linux, &m);
        assert_eq!(r.unwrap_err().0, ErrorKind::SourceEmpty);
        std::fs::write(src.join("photo.NEF"), b"x").unwrap();
        assert!(check_module(&module(p, true), dir.path(), Os::Linux, &m).is_ok());
        // Not a folder.
        let r = check_module(
            &module(&format!("{p}/photo.NEF"), false),
            dir.path(),
            Os::Linux,
            &m,
        );
        assert_eq!(r.unwrap_err().0, ErrorKind::Missing);
    }

    #[test]
    fn errno_mapping() {
        let eperm = std::io::Error::from_raw_os_error(libc::EPERM);
        let eacces = std::io::Error::from_raw_os_error(libc::EACCES);
        assert_eq!(errno_kind(&eperm, Os::MacOs), ErrorKind::Tcc);
        assert_eq!(errno_kind(&eperm, Os::Linux), ErrorKind::Permission);
        assert_eq!(errno_kind(&eacces, Os::MacOs), ErrorKind::Permission);
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn real_mac_mount_points() {
        let m = SystemMounts::load();
        assert!(m.is_mount_point(Path::new("/")));
        assert!(!m.is_mount_point(Path::new("/Users")));
        assert!(!m.is_mount_point(Path::new("/Volumes/bn-backup-test-not-there")));
    }
}
