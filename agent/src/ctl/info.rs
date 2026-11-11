// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl info`.

use super::Output;
use crate::paths::{Layout, Os};
use crate::util::CtlError;

pub fn run(layout: &Layout, os: Os) -> Result<Output, CtlError> {
    Ok(Output::Json(crate::info::gather(layout, os)))
}
