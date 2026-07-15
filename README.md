# drive-offload

Keep a nearly-full local disk clear by pushing completed downloads to Google
Shared Drives automatically.

> ⚖️ Use only with content you have the right to store.

> 📖 **[Read the case study](CASE-STUDY.md)** — how this was designed and
> built through orchestrated AI agents.

There are two modes. **Watcher** (`offloader.py`) monitors a dedicated folder
that Motrix / a torrent client downloads into; once a download finishes it
`rclone move`s the file (or torrent directory) to a Shared Drive and deletes it
locally, freeing the space. It knows a download is finished because aria2 (the
engine inside Motrix) keeps a `<filename>.aria2` control file next to each
in-progress download and deletes that control file on completion — so "no
`.aria2` sibling + size stable for a while" means done. **Stream** (`stream-dl`)
is for direct download links: it pipes the URL straight into cloud storage via
`rclone copyurl`, using essentially **zero local disk** (nothing lands on your
drive at all).

> ⚠️ The watcher **deletes** whatever it successfully uploads. Point it only at
> a dedicated subfolder such as `~/Downloads/Offload` — never your home folder,
> `/`, `~/Downloads` itself, etc. The daemon refuses to start otherwise.

## 1. Configure rclone (one remote)

You need **one** rclone remote pointed at your Google account. The `todrive`
tool then addresses individual Shared Drives dynamically by ID, so you do *not*
configure a remote per drive. Run `rclone config` and answer:

- `n` — new remote
- name: `gdrive`
- storage: `drive` (Google Drive)
- client id / client secret: leave **blank** (press Enter)
- scope: `1` (full access)
- service account file: leave **blank**
- Edit advanced config: `no`
- Use auto config: `yes` — a browser opens for Google OAuth; sign in and allow
- **Configure this as a Shared Drive (Team Drive)?** → **`no`** — leave it on
  your regular My Drive root; `todrive` reaches each Shared Drive by ID.

That single `gdrive` remote is all `todrive`, `stream-dl`, and the watcher need.

## 2. Configure this tool

On first run, `offloader.py` writes a default `config.json` next to itself and
exits. Edit it:

```json
{
  "watch_dirs": ["~/Downloads/Offload"],
  "remotes": ["gdrive1:", "gdrive2:", "gdrive3:"],
  "remote_subdir": "Offload",
  "poll_seconds": 10,
  "stable_seconds": 20,
  "delete_after_upload": true,
  "exclude_names": [".DS_Store"],
  "exclude_extensions": [".aria2", ".part", ".crdownload", ".tmp", ".download"],
  "rclone_flags": ["--drive-chunk-size", "64M", "--transfers", "4", "--retries", "3", "--low-level-retries", "10"],
  "log_file": "offload.log"
}
```

Remote names must end with `:` (e.g. `gdrive1:`). Files land in
`<remote>:<remote_subdir>/`.

## 3. Point Motrix at the watch folder

```sh
mkdir -p ~/Downloads/Offload
```

In Motrix → **Preferences → Basic → Default Path**, set it to
`~/Downloads/Offload` (or set it per-task). Torrents that download as a
directory are moved as a single unit.

## 4. Test, then install

Dry run first (records sizes, then reports what it *would* move — never
deletes):

```sh
python3 offloader.py --once --dry-run
```

When happy, install the background LaunchAgent (runs at login, restarts if it
dies):

```sh
./install-agent.sh
```

Logs: `offload.log` (app log), `launchd.out.log` / `launchd.err.log` (launchd).
Remove it later with `./uninstall-agent.sh`.

## Named shared drives (todrive)

`todrive` addresses Google **Shared Drives by name**, creating them on demand.
Give each show or category its own 100 GB shared drive — one for `My Show S01`,
another for `Documentaries`, and so on — without pre-configuring an rclone
remote for each. It uses the single `gdrive` remote plus rclone's
connection-string syntax (`gdrive,team_drive=<ID>:`) under the hood.

```sh
# list your shared drives (name + id)
./todrive list

# create a new shared drive
./todrive new "My Show S01"

# upload local files/dirs into a shared drive (creates it if missing).
# the last argument is the drive name; the shell expands the glob.
./todrive up ~/Downloads/Offload/My.Show.S01.* "My Show S01"

# --keep copies instead of moving (leaves the local files in place)
./todrive up ~/Movies/thing.mkv "Archive" --keep

# per-drive storage usage against the 100 GB cap (add --json for a script)
./todrive du
```

```
NAME              USED       %CAP  OBJECTS
Documentaries     21.1 GB   21.1%  25
Movies            87.3 GB   87.3%  1204
TV Archive       173.5 GB  173.5%  9821  (grandfathered)

3 shared drives · 281.9 GB total · cap 100 GB/drive
```

Directories are moved as a single unit (contents land under
`…team_drive=<ID>:<dirname>/`). `up` auto-creates the target drive if it does
not exist. `resolve` just prints the connection string, which is how `stream-dl`
targets a named drive.

**`up` refuses incomplete downloads.** Because a move deletes the local copy,
`todrive up` scans each path first and blocks anything that looks like an
in-progress download — a `.part` / `.aria2` / `.!qb` / `.crdownload` /
`.download` name anywhere in the payload, or an aria2 control-file sibling.
Override with `--allow-partial` if you really mean it. After a successful
directory **move**, the emptied local folder tree is removed too (rclone only
deletes files), so offloads no longer leave husk directories behind; `--keep`
copies never delete or remove anything.

### Storage & overflow (the 100 GB cap)

Google caps each Shared Drive at **100 GB** (decimal — `100 × 1000³` bytes).
`todrive du` reports every drive's usage against that cap by summing its file
sizes via one Drive API `files.list` scan (no per-drive API exposes used bytes
directly). On large accounts Google's `allDrives` listing occasionally returns a
5xx mid-pagination, so `du` retries and then falls back to a reliable per-drive
scan. A drive created **before** the cap existed can sit above 100 GB — it shows
its real size and a `>100%` `(grandfathered)` tag, and is otherwise left
completely alone (never shrunk, blocked, or warned about).

**`up` routes around a full drive automatically.** Before uploading, `todrive`
checks whether the payload fits the target; if not — or if rclone hits a quota
error mid-upload — it routes to an **overflow drive named `<drive> overflow`**
(then `<drive> overflow 2`, `overflow 3`, …), creating it on demand. The
predictable naming keeps overflow drives sorted next to their parent so you can
find and consolidate them by hand. Pass `--no-overflow` to disable this and use
the single named drive exactly as before. An oversized payload that can't fit
*any* 100 GB drive fails that item up front (without minting a drive) while the
rest of a multi-file `up` continues.

If your Google Workspace admin blocks creating shared drives via the API,
`todrive new` reports an HTTP 403 and asks you to create the drive manually in
the Drive web UI (**New → Shared drive**), after which every command finds it by
name.

## Menu bar app

`offload_app.py` is a macOS menu-bar companion for Motrix and Transmission.
Instead of blindly auto-uploading everything (the watcher's job), it **asks per
download** where it should go, the moment a download starts:

- **Keep on Mac** — leave it where Motrix put it, do nothing.
- **Shared Drive…** — pick an existing Google Shared Drive from a list…
- **➕ New shared drive…** — …or type a new name, created automatically.

When that download finishes, the chosen upload runs via `todrive up` (which
deletes the local copy after a verified upload), and you get a macOS
notification on start, success (`freed 3.4 GiB`), and failure.

**Uploads start the moment the download hits 100% — seeding doesn't delay
them.** aria2 keeps a finished torrent's status `active` for as long as it
seeds, so a naive "wait for complete" would wait out the entire seeding window
(hours, or forever). The app normalizes that: fully-downloaded means done
(every piece is already hash-verified at that point), the torrent is paused,
and the upload begins within one 3-second poll.

**…but never before the payload is actually whole on disk.** An engine's
"done" can lie: Transmission transiently reports `leftUntilDone == 0` while it
is still *verifying* (status 1/2), before it renames `<name>.part` to its
final name — and acting on that once uploaded a hole-filled `.mkv.part` and
deleted the local copy (the 2026-07-06 incident). Two independent guards now
sit between "engine says complete" and the destructive `rclone move`:
a verifying Transmission torrent is never treated as complete, and a
**payload-readiness gate** checks the disk itself before every dispatch —
every selected file in the torrent must exist under its final name, no
incomplete-download marker (`.part`, `.aria2`, `.!qb`, `.crdownload`,
`.download`) may appear anywhere in the payload, and the on-disk size must
cover the expected size. A not-ready payload is simply re-checked on the next
3-second poll (logged once as `NOTREADY`/`READY`, with a single notification
if it stays stuck past 30 minutes) — the decision is never consumed, so
nothing is lost by waiting.

It talks to the aria2 engine embedded in Motrix over Motrix's local JSON-RPC
(default `127.0.0.1:16800`, no secret — the defaults, so no setup needed; port
and secret are read from `~/Library/Application Support/Motrix/system.json` if
you changed them). If Motrix isn't running the icon just shows idle and it
reconnects when Motrix appears.

### Transmission

The menu-bar app watches **Transmission** too, alongside Motrix — run either or
both. It works out of the box once Transmission's remote access is on:
**Transmission → Settings/Preferences → Remote tab → “Enable remote access”**
(default port `9091`). If you turn on authentication there, add the matching
credentials to `config.json` (the same file the watcher uses — the app only
reads it, never writes it):

```json
{
  "transmission_rpc_port": 9091,
  "transmission_rpc_user": "",
  "transmission_rpc_pass": ""
}
```

All three keys are optional; the defaults are port `9091` and no auth. The app
speaks Transmission's RPC directly (stdlib `urllib`, including the
`X-Transmission-Session-Id` CSRF handshake), so no extra dependency is needed.

Torrents show up in the same menu as Motrix downloads and get the same
per-download “where should this go?” prompt. The status line reports each engine
separately, e.g. `Motrix: connected · Transmission: not running`.

**Torrent lifecycle around an upload (both engines).** When a finished torrent
is routed to a drive, the app **stops** it first (so it isn't seeding while the
payload is moved), then uploads. On a verified success the now-dataless torrent
is **removed** from its engine (so Motrix/Transmission doesn't keep trying to
seed a deleted file or sit on a "data missing" error). On **failure** the
torrent is **resumed** — a failed offload never leaves your download stuck
paused, and the local data is intact because `todrive` only deletes after a
byte-verified upload.

> Runs under launchd too. The menu-bar app can be started by a LaunchAgent, which
> gives it a minimal `PATH` that omits Homebrew. `todrive` resolves the `rclone`
> binary itself (PATH, then `/opt/homebrew/bin`, `/usr/local/bin`, …), so uploads
> work whether the app is launched from a terminal or automatically at login.
> (Earlier versions failed here with `rclone not found on PATH`.)

### Live upload progress

While an upload runs, the menu-bar **title itself shows the percent** —
`⬆ 42%` (multiple simultaneous uploads show a count and the average,
`⬆2 40%`) — parsed live from rclone's progress stream. The menu shows each
engine's connection state, active downloads (`name — 42% (3.2 MiB/s)`), running
uploads with detail (`⬆ name → DriveName — 42% (3.2 MiB/s, ETA 2m58s)`), and a
**Recent** list of the last five finished/uploaded items. Controls:

- **Pause asking (auto-keep local)** — while on, new downloads are silently
  kept local with no dialog.
- **Upload speed limit** — Unlimited / 2 / 5 / 10 MB/s, applied to uploads via
  rclone's `RCLONE_BWLIMIT` env var (the standard `RCLONE_<FLAG>` mapping of
  `--bwlimit`). The choice persists in `app_state.json`.
- **Re-upload to Drive** — lists anything that never made it onto a Shared
  Drive: items you kept on the Mac (**including a cancelled or timed-out ask**,
  which defaults to keeping local) and uploads that gave up after repeated
  failures. Pick one, choose a drive, and it's re-queued — and only marked
  done once the upload actually lands. This is how you redirect a file you
  parked locally by mistake; re-adding the same torrent won't re-ask, because
  the per-download decision is remembered by its id.
- **Drive storage** — a submenu listing each Shared Drive's fill against the
  100 GB cap (`Movies — 87.3 GB / 100 GB · 87.3%`, `(grandfathered)` when over).
  It's refreshed on a background thread (every 15 min, after each upload, and on
  **Refresh now**), cached to `app_state.json` so it shows last-known numbers
  instantly on launch, and never blocks the menu. The per-download drive picker
  is annotated the same way (`Movies — 87% full`) so you can steer toward a
  roomy drive. When an upload overflows, the notification and **Recent** entry
  read `Movies → Movies overflow (overflow)`.
- **Open log** opens `app.log`.

Install (creates a project-local `.venv`, installs `rumps`, and registers a
login LaunchAgent that restarts the app if it dies):

```sh
./install-app.sh
```

Uninstall with `./uninstall-app.sh`. Logs: `app.log` (app), `launchd-app.out.log`
/ `launchd-app.err.log` (launchd). Decisions are remembered per download in
`decisions.json`.

### Standalone app: drive-offload.app

The menu-bar app also builds into a self-contained macOS bundle (embedded
Python + rumps + `todrive`; no repo or venv needed at runtime) with a proper
icon — see **[BUILD.md](BUILD.md)** for the py2app build, `/Applications`
install, and LaunchAgent swap. One behavioral difference: the bundled app
keeps its state (`config.json`, `decisions.json`, `app_state.json`, `app.log`)
in `~/Library/Application Support/drive-offload/` instead of next to the
script — writing inside an installed `.app` would break code signing and get
wiped on reinstall. Run from source, nothing changes.

## stream-dl usage

```sh
# use the first remote + remote_subdir from config.json
./stream-dl "https://example.com/big.iso"

# or give an explicit rclone destination
./stream-dl "https://example.com/big.iso" gdrive2:Offload/

# or stream straight into a named shared drive (created if missing)
./stream-dl "https://example.com/big.iso" --drive "My Show S01"
```

`-P` shows live progress; the final destination is printed on success.

## Watcher vs. named drives

The watcher (`offloader.py`) is **optional** — it is for an
"auto-upload-everything" workflow where anything dropped into the watch folder
is moved to cloud storage without you thinking about it. For deliberate,
per-show organization, use `todrive` (and `stream-dl --drive`) to sort uploads
into a named shared drive per show/category.
