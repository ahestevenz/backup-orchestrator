// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl open-fda-settings`: macOS only.

use super::Output;
use crate::platform::current;
use crate::util::CtlError;

pub fn run() -> Result<Output, CtlError> {
    current::open_fda_settings().map(Output::Json)
}
