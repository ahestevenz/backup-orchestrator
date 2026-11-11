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
| annotated-types | MIT |
| loguru | MIT |
| pydantic | MIT |
| pydantic-core | MIT |
| pyyaml | MIT |
| ruamel-yaml | MIT |
| typing-extensions | PSF-2.0 |
| typing-inspection | MIT |

### Agent (Rust)

| Crate | License |
| --- | --- |
| anstream | Apache-2.0 OR MIT |
| anstyle | Apache-2.0 OR MIT |
| anstyle-parse | Apache-2.0 OR MIT |
| anstyle-query | Apache-2.0 OR MIT |
| anstyle-wincon | Apache-2.0 OR MIT |
| anyhow | Apache-2.0 OR MIT |
| bitflags | Apache-2.0 OR MIT |
| cfg-if | Apache-2.0 OR MIT |
| clap | Apache-2.0 OR MIT |
| clap_builder | Apache-2.0 OR MIT |
| clap_derive | Apache-2.0 OR MIT |
| clap_lex | Apache-2.0 OR MIT |
| colorchoice | Apache-2.0 OR MIT |
| deranged | Apache-2.0 OR MIT |
| equivalent | Apache-2.0 OR MIT |
| hashbrown | Apache-2.0 OR MIT |
| heck | Apache-2.0 OR MIT |
| indexmap | Apache-2.0 OR MIT |
| is_terminal_polyfill | Apache-2.0 OR MIT |
| itoa | Apache-2.0 OR MIT |
| libc | Apache-2.0 OR MIT |
| memchr | MIT OR Unlicense |
| nix | MIT |
| num-conv | Apache-2.0 OR MIT |
| once_cell_polyfill | Apache-2.0 OR MIT |
| powerfmt | Apache-2.0 OR MIT |
| proc-macro2 | Apache-2.0 OR MIT |
| quote | Apache-2.0 OR MIT |
| serde | Apache-2.0 OR MIT |
| serde_core | Apache-2.0 OR MIT |
| serde_derive | Apache-2.0 OR MIT |
| serde_json | Apache-2.0 OR MIT |
| serde_spanned | Apache-2.0 OR MIT |
| shell-words | Apache-2.0 OR MIT |
| strsim | MIT |
| syn | Apache-2.0 OR MIT |
| thiserror | Apache-2.0 OR MIT |
| thiserror-impl | Apache-2.0 OR MIT |
| time | Apache-2.0 OR MIT |
| time-core | Apache-2.0 OR MIT |
| time-macros | Apache-2.0 OR MIT |
| toml | Apache-2.0 OR MIT |
| toml_datetime | Apache-2.0 OR MIT |
| toml_parser | Apache-2.0 OR MIT |
| toml_writer | Apache-2.0 OR MIT |
| unicode-ident | (Apache-2.0 OR MIT) AND Unicode-3.0 |
| utf8parse | Apache-2.0 OR MIT |
| windows-link | Apache-2.0 OR MIT |
| windows-sys | Apache-2.0 OR MIT |
| winnow | MIT |
| zmij | MIT |

<!-- END generated -->
