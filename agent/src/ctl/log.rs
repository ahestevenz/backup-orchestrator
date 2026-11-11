// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl log <user> <module>`: the last 2000 lines of the module's rsync log.

use serde_json::json;

use super::{check_user, Output};
use crate::paths::Layout;
use crate::util::{tail_lines, valid_module_name, CtlError};

pub const MAX_LINES: usize = 2000;

pub fn run(layout: &Layout, user: &str, module: &str) -> Result<Output, CtlError> {
    check_user(user)?;
    if !valid_module_name(module) {
        return Err(CtlError::new(
            "bad_module",
            format!("invalid module name {module:?}"),
        ));
    }
    let lines = match tail_lines(&layout.rsync_log(user, module), MAX_LINES) {
        Ok(l) => l,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Vec::new(),
        Err(e) => return Err(e.into()),
    };
    Ok(Output::Json(json!({"lines": lines})))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tail_and_validation() {
        let d = tempfile::tempdir().unwrap();
        let l = Layout {
            home: d.path().into(),
        };
        std::fs::create_dir_all(l.state_dir("sofia")).unwrap();
        let text: String = (0..2500).map(|i| format!("line {i}\n")).collect();
        std::fs::write(l.rsync_log("sofia", "docs"), text).unwrap();
        let Output::Json(v) = run(&l, "sofia", "docs").unwrap() else {
            panic!()
        };
        let lines = v["lines"].as_array().unwrap();
        assert_eq!(lines.len(), MAX_LINES);
        assert_eq!(lines[0], "line 500");
        assert_eq!(
            run(&l, "sofia", "../../etc/x").unwrap_err().code,
            "bad_module"
        );
        let Output::Json(v) = run(&l, "sofia", "none").unwrap() else {
            panic!()
        };
        assert_eq!(v["lines"].as_array().unwrap().len(), 0);
    }
}
