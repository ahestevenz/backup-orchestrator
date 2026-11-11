// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl stop <user>`.

use super::{check_user, ok, Output};
use crate::platform::current;
use crate::util::CtlError;

pub fn run(user: &str) -> Result<Output, CtlError> {
    check_user(user)?;
    current::stop(user)?;
    Ok(ok())
}
