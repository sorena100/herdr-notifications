# Source review and fork changes

Reviewed upstream revision: `9f54f42debde9754f8d3b3d7b1fe208a64d65eef`.

## Scope and conclusion

Reviewed the complete application source (including tests), plugin manifest,
package manifest, tracked-file inventory and dependency sources in Cargo.lock.
Ran the unit tests and RustSec `cargo audit` against the lockfile. Also exercised
the release binary against an isolated D-Bus notification server: a default
body-click action runs `agent focus` for the recorded pane ID; Close and dismissal
do not run focus. The test uses a stub Herdr CLI, not the real desktop session.

No obvious malicious behavior was found in the reviewed application source:

- No application-level network uploads, telemetry, credential collection,
  downloaded executables, or runtime update mechanism.
- Notifications use the local desktop notification service; Herdr metadata is
  obtained through its CLI. Agent/workspace titles are sent to the desktop and
  may therefore be retained in notification history.
- Child processes use argv arrays, not shell interpolation of notification
  text. GNOME's optional JavaScript focus command interpolates a parsed integer
  PID, not notification text.
- File writes are deduplication state and diagnostic logs in plugin-owned state
  storage. Optional terminal activation inspects process command lines and
  environment variables through `/proc` to find desktop connection details.
- Builds use Cargo and crates.io dependencies. There is no project build script,
  custom package registry, or Git dependency in the reviewed lockfile.

This is a scoped source review, **not a security certification**. Dependency
source was not exhaustively audited. Herdr plugins run unsandboxed with the
user's permissions, including inherited environment and filesystem access.

## Findings addressed in this fork

1. **Missing notification action:** upstream only registers `close`, although
   Omarchy needs a registered `default` action for notification-body clicks.
   Register the default action except on the explicit dismissal-as-click path.
2. **Wrong Hyprland target:** upstream attempts to focus the Herdr process PID,
   which does not own the terminal window. Resolve an actual window from
   `hyprctl clients -j` along the client's parent chain and focus its address.
   No matching window is a failure, not an assumed successful focus.
3. **Missing compositor environment:** import `HYPRLAND_INSTANCE_SIGNATURE`
   from the candidate UI client and pass it to `hyprctl`. Do not combine missing
   environment values from multiple candidate clients.
4. **Dependency advisory:** upstream pins `event-listener` 5.4.1, affected by
   the RustSec informational unsoundness warning RUSTSEC-2026-0221. Update to
   5.4.2. The updated lockfile passes `cargo audit` with no vulnerabilities or
   warnings at review time. Future advisories still require rechecking.
5. **Reproducibility:** use `cargo build --release --locked` on installation.

The fork also permits opt-in window raising through plugin `config.json` so a
running server need not be restarted merely to change its inherited environment.
Regression tests cover action registration, configuration, connection-variable
propagation, parent-window resolution and malformed addresses.

## Remaining limitations

- The plugin is server-side. A local install does not deliver events from remote
  SSH servers; their desktop connections are a separate problem.
- Candidate UI clients are discovered heuristically from processes, not bound
  to the notification's exact server/client connection. With multiple Herdr
  sessions or desktop windows it may raise the wrong one. API focus may also
  affect more than one attached client. Do not treat this as precise multi-client
  routing.
- Unlike built-in client notifications, it does not suppress a notification
  simply because the pane is already visible. It has its own transition,
  deduplication and startup-quiet rules.
- Deduplication keys are pane IDs in shared plugin state, not session-qualified
  IDs. Independent local sessions can collide. State/log growth is not bounded.
- Notification waits are bounded, but external CLI/focus subprocess calls are
  not individually time-limited.
- State locking is best-effort and can proceed after a timeout. Symlink checks
  do not constitute complete filesystem hardening. Keep config/state directories
  private; do not point them at shared writable directories.
- Notification actions stop working once the listener exits (roughly 65 seconds)
  or the notification is restored from history without its original live sender.
