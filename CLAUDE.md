# drive-offload

Uploader/renamer + storage tooling that gets media onto Google Shared Drives
for the Drivecast ecosystem (see `drivecast/CLAUDE.md` for the sibling repos).

## yt-show

`yt-show` is a sibling CLI to `stream-dl` / `todrive`: it builds a Drivecast TV
show out of a YouTube playlist, downloading each video (via `yt-dlp`) and
uploading it as `<Show> SxxEyy - <Title>.ext` under `<Show> Season N/` on a
named Shared Drive. It reuses `renamer.py`'s canonical naming and `todrive`'s
upload leg rather than duplicating either.

Per-show incremental state (what's already downloaded/uploaded, current
season/episode cursor) lives in `yt_shows.json`, keyed by show name. Episode
numbering is per-video-ID and append-only — re-running against the same or an
additional playlist only adds new episodes; existing numbers never shift.

`assign_new_episodes` (in `yt-show`) handles the assignment/season logic —
`--new-season` vs `--same-season`, auto-rolling to the next season past
episode 100. Canonical naming (`clean_source_title` / `synth_episode` /
`plan_from_sequence`) lives in `renamer.py`; the R13 contract gate rejects bad
folder names, e.g. digit-dash-digit show names like "9-1-1".

Download/upload is pipelined: videos download sequentially, each pulled
multi-connection via aria2c, while a background thread does per-file `rclone
moveto` into `<Show> Season N/` for the previous video — a bounded queue caps
disk usage. State is written only by the uploader thread, and only after
`rclone`'s exit code is 0.

`--pick`, and every run in general, prints live per-drive capacity via
`todrive du --json`.
