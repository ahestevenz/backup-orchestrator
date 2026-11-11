# Third-party notices

bleiben Backup Orchestrator includes or depends on the software below. Each
keeps its own license; none of them is covered by the PolyForm Noncommercial
license of this project or by the policy in `LICENSING.md`.

## rsync 3.4.1 and rrsync

- **What:** `rsync`, bundled inside the macOS agent package
  (`BNBackupAgent.app/Contents/Resources/rsync`), and its `rrsync` script,
  shipped inside the server package (`bn_backup/vendor/rrsync`).
- **License:** GNU General Public License, version 3 or later
  (GPL-3.0-or-later). The full text is next to each copy: `rsync-COPYING` in
  the macOS app, `bn_backup/vendor/COPYING` in the server package.
- **Source code:** the exact source used to build them is attached to every
  release as `rsync-3.4.1.tar.gz`. It is also available from
  <https://download.samba.org/pub/rsync/src/>.
- **Copyright:** Andrew Tridgell, Paul Mackerras, Wayne Davison and the rsync
  contributors.

On Linux the agent does not bundle rsync; it uses the distribution's `rsync`
package.

## Libraries

<!-- BEGIN generated: do not edit by hand. CI regenerates this section from
     the dependency trees (scripts/third_party_notices.py). -->

### Server (Python)

| Package | License |
| --- | --- |
| loguru | MIT |
| pydantic | MIT |
| PyYAML | MIT |
| ruamel.yaml | MIT |

### Agent (Rust)

| Crate | License |
| --- | --- |
| anyhow | MIT OR Apache-2.0 |
| clap | MIT OR Apache-2.0 |
| libc | MIT OR Apache-2.0 |
| nix | MIT |
| serde | MIT OR Apache-2.0 |
| serde_json | MIT OR Apache-2.0 |
| shell-words | MIT OR Apache-2.0 |
| thiserror | MIT OR Apache-2.0 |
| time | MIT OR Apache-2.0 |
| toml | MIT OR Apache-2.0 |

<!-- END generated -->
