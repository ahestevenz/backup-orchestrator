// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl ping`: no side effects.

use super::{ok, Output};
use crate::util::CtlError;

pub fn run() -> Result<Output, CtlError> {
    Ok(ok())
}
