// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl result <user>`: the result file verbatim, or `{"state":"absent"}`.

use serde_json::json;

use super::{check_user, Output};
use crate::paths::Layout;
use crate::util::CtlError;

pub fn run(layout: &Layout, user: &str) -> Result<Output, CtlError> {
    check_user(user)?;
    match std::fs::read_to_string(layout.result_json(user)) {
        Ok(text) => Ok(Output::Raw(text)),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            Ok(Output::Json(json!({"state": "absent"})))
        }
        Err(e) => Err(e.into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn absent_and_present() {
        let d = tempfile::tempdir().unwrap();
        let l = Layout {
            home: d.path().into(),
        };
        assert_eq!(
            run(&l, "sofia").unwrap(),
            Output::Json(json!({"state": "absent"}))
        );
        std::fs::create_dir_all(l.state_dir("sofia")).unwrap();
        std::fs::write(l.result_json("sofia"), "{\"state\":\"done\"}").unwrap();
        assert_eq!(
            run(&l, "sofia").unwrap(),
            Output::Raw("{\"state\":\"done\"}".into())
        );
        assert_eq!(run(&l, "../x").unwrap_err().code, "bad_user");
    }
}
