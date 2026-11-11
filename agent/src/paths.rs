// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! Where the agent and its files live (CLAUDE.md §5.1).

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::util::CtlError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Os {
    MacOs,
    Linux,
}

impl Os {
    pub fn current() -> Os {
        if cfg!(target_os = "macos") {
            Os::MacOs
        } else {
            Os::Linux
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Os::MacOs => "darwin",
            Os::Linux => "linux",
        }
    }
}

pub const MACOS_EXECUTABLE: &str = "/Applications/BNBackupAgent.app/Contents/MacOS/bn-backup-agent";
pub const MACOS_RSYNC: &str = "/Applications/BNBackupAgent.app/Contents/Resources/rsync";
pub const MACOS_HOME: &str = "/Library/Application Support/BNBackupAgent";
pub const LINUX_EXECUTABLE: &str = "/usr/bin/bn-backup-agent";
pub const LINUX_RSYNC: &str = "/usr/bin/rsync";
pub const LINUX_HOME: &str = "/var/lib/bn-backup-agent";
pub const SUDOERS_FILE: &str = "/etc/sudoers.d/bn-backup-agent";
pub const LABEL_PREFIX: &str = "ar.bleiben.bn-backup-agent";
pub const CONTROL_KEY_COMMENT: &str = "bn-backup-server";

/// The absolute path of the agent executable (what sudoers and the control key name).
pub fn executable(os: Os) -> &'static str {
    match os {
        Os::MacOs => MACOS_EXECUTABLE,
        Os::Linux => LINUX_EXECUTABLE,
    }
}

/// The rsync the agent runs. Debug builds may override it for tests.
pub fn rsync_path() -> PathBuf {
    #[cfg(debug_assertions)]
    if let Ok(p) = std::env::var("BN_BACKUP_AGENT_RSYNC") {
        return PathBuf::from(p);
    }
    PathBuf::from(match Os::current() {
        Os::MacOs => MACOS_RSYNC,
        Os::Linux => LINUX_RSYNC,
    })
}

/// The agent home `$AH`. `BN_BACKUP_AGENT_HOME` is honoured only in debug builds.
pub fn agent_home() -> PathBuf {
    #[cfg(debug_assertions)]
    if let Ok(p) = std::env::var("BN_BACKUP_AGENT_HOME") {
        return PathBuf::from(p);
    }
    PathBuf::from(match Os::current() {
        Os::MacOs => MACOS_HOME,
        Os::Linux => LINUX_HOME,
    })
}

/// Files inside the agent home.
#[derive(Debug, Clone)]
pub struct Layout {
    pub home: PathBuf,
}

impl Layout {
    pub fn system() -> Layout {
        Layout { home: agent_home() }
    }

    pub fn agent_toml(&self) -> PathBuf {
        self.home.join("agent.toml")
    }
    pub fn known_hosts(&self) -> PathBuf {
        self.home.join("server_known_hosts")
    }
    pub fn users_dir(&self) -> PathBuf {
        self.home.join("users")
    }
    pub fn user_dir(&self, user: &str) -> PathBuf {
        self.users_dir().join(user)
    }
    pub fn job_json(&self, user: &str) -> PathBuf {
        self.user_dir(user).join("job.json")
    }
    pub fn state_dir(&self, user: &str) -> PathBuf {
        self.user_dir(user).join("state")
    }
    pub fn result_json(&self, user: &str) -> PathBuf {
        self.state_dir(user).join("result.json")
    }
    pub fn key(&self, user: &str) -> PathBuf {
        self.state_dir(user).join("id_ed25519")
    }
    pub fn key_pub(&self, user: &str) -> PathBuf {
        self.state_dir(user).join("id_ed25519.pub")
    }
    pub fn rsync_log(&self, user: &str, module: &str) -> PathBuf {
        self.state_dir(user).join(format!("rsync-{module}.log"))
    }
    pub fn verify_log(&self, user: &str, module: &str) -> PathBuf {
        self.state_dir(user)
            .join(format!("rsync-{module}-verify.log"))
    }
    pub fn agent_log(&self, user: &str) -> PathBuf {
        self.state_dir(user).join("agent.log")
    }

    /// Users that have been added: a folder with a push key.
    pub fn users(&self) -> Vec<String> {
        let mut out: Vec<String> = std::fs::read_dir(self.users_dir())
            .map(|rd| {
                rd.filter_map(|e| e.ok())
                    .filter_map(|e| e.file_name().into_string().ok())
                    .filter(|u| self.key(u).exists())
                    .collect()
            })
            .unwrap_or_default();
        out.sort();
        out
    }

    pub fn load_config(&self) -> Result<AgentConfig, CtlError> {
        AgentConfig::load(&self.agent_toml())
    }
}

/// `agent.toml`, written by `ctl setup`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AgentConfig {
    pub server_host: String,
    pub server_port: u16,
    pub server_user: String,
    pub admin_user: String,
    pub host_name: String,
}

impl AgentConfig {
    pub fn load(path: &Path) -> Result<AgentConfig, CtlError> {
        let text = std::fs::read_to_string(path).map_err(|_| {
            CtlError::new(
                "not_configured",
                "the agent is not set up yet (run bn-backup hosts bootstrap on the server)",
            )
        })?;
        toml::from_str(&text)
            .map_err(|e| CtlError::new("not_configured", format!("agent.toml is invalid: {e}")))
    }

    pub fn to_toml(&self) -> String {
        toml::to_string(self).unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn layout_paths() {
        let l = Layout {
            home: PathBuf::from("/x"),
        };
        assert_eq!(
            l.result_json("sofia"),
            PathBuf::from("/x/users/sofia/state/result.json")
        );
        assert_eq!(
            l.rsync_log("sofia", "docs"),
            PathBuf::from("/x/users/sofia/state/rsync-docs.log")
        );
    }

    #[test]
    fn agent_config_round_trip() {
        let c = AgentConfig {
            server_host: "macmini.home.lan".into(),
            server_port: 22,
            server_user: "ariel".into(),
            admin_user: "ariel".into(),
            host_name: "athena".into(),
        };
        let back: AgentConfig = toml::from_str(&c.to_toml()).unwrap();
        assert_eq!(back, c);
    }
}
