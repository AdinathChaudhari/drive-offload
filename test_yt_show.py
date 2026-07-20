#!/usr/bin/env python3
"""Headless tests for yt-show's PURE episode-assignment function
(assign_new_episodes). No yt_dlp, no filesystem, no network — yt-show imports
yt_dlp lazily (inside the functions that need it), so loading the module here
does not require yt_dlp to be installed.

    .venv/bin/python3 test_yt_show.py     (or: python3 test_yt_show.py)

show_rec is the per-show record persisted in yt_shows.json:
    {"episodes": {video_id: {"season": S, "episode": E}, ...},
     "playlists": {plid: {"season": S}, ...}}
assign_new_episodes(show_rec, plid, new_items, mode) takes the ordered new
video ids for one playlist pass and returns the (video_id, season, episode)
assignments for them, in order, WITHOUT mutating show_rec. `mode` ('same' or
'new') only matters the first time a playlist is seen; a plid already present
in show_rec['playlists'] keeps its recorded season regardless of mode.
"""
import copy
import importlib.machinery
import importlib.util
import os
import unittest

_P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yt-show")
_spec = importlib.util.spec_from_loader(
    "yt_show", importlib.machinery.SourceFileLoader("yt_show", _P))
yt_show = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(yt_show)


def _episodes_at(show_rec, plid, season, count, start=1):
    """Seed show_rec['episodes']/['playlists'] as if `count` prior videos
    (v<plid>-1 .. v<plid>-count) had already been committed to `season`,
    starting at episode `start`."""
    show_rec.setdefault("playlists", {})[plid] = {"season": season}
    eps = show_rec.setdefault("episodes", {})
    for i in range(count):
        eps["v%s-%d" % (plid, i + 1)] = {"season": season,
                                          "episode": start + i}


class TestAssignNewEpisodes(unittest.TestCase):
    def test_brand_new_show_starts_season_1(self):
        show_rec = {"episodes": {}, "playlists": {}}
        result = yt_show.assign_new_episodes(
            show_rec, "PL1", ["v1", "v2", "v3"], "same")
        self.assertEqual(result, [("v1", 1, 1), ("v2", 1, 2), ("v3", 1, 3)])

    def test_incremental_continues_from_next_episode(self):
        show_rec = {"episodes": {}, "playlists": {}}
        _episodes_at(show_rec, "PL1", season=1, count=3)   # v PL1-1..3 = ep 1-3
        result = yt_show.assign_new_episodes(
            show_rec, "PL1", ["v4", "v5"], "same")
        self.assertEqual(result, [("v4", 1, 4), ("v5", 1, 5)])

    def test_same_season_mode_new_playlist_continues_max_season(self):
        show_rec = {"episodes": {}, "playlists": {}}
        _episodes_at(show_rec, "PL1", season=1, count=5)   # max season is 1
        result = yt_show.assign_new_episodes(
            show_rec, "PL2", ["w1", "w2"], "same")
        self.assertEqual(result, [("w1", 1, 6), ("w2", 1, 7)])

    def test_new_season_mode_new_playlist_bumps_season(self):
        show_rec = {"episodes": {}, "playlists": {}}
        _episodes_at(show_rec, "PL1", season=1, count=5)   # max season is 1
        result = yt_show.assign_new_episodes(
            show_rec, "PL2", ["w1"], "new")
        self.assertEqual(result, [("w1", 2, 1)])

    def test_roll_at_100_starts_next_season(self):
        show_rec = {"episodes": {}, "playlists": {}}
        items = ["v%d" % i for i in range(1, 102)]   # 101 items
        result = yt_show.assign_new_episodes(show_rec, "PL1", items, "same")
        self.assertEqual(len(result), 101)
        self.assertEqual(result[0], ("v1", 1, 1))
        self.assertEqual(result[99], ("v100", 1, 100))
        self.assertEqual(result[100], ("v101", 2, 1))

    def test_known_playlist_keeps_recorded_season_regardless_of_mode(self):
        show_rec = {"episodes": {}, "playlists": {}}
        _episodes_at(show_rec, "PL2", season=2, count=2)   # PL2 already at S2
        # mode='new' would normally bump the season for an UNSEEN playlist,
        # but PL2 is already known -> stays at its recorded season 2.
        result = yt_show.assign_new_episodes(show_rec, "PL2", ["x1"], "new")
        self.assertEqual(result, [("x1", 2, 3)])

    def test_rollover_skips_season_occupied_by_another_playlist(self):
        # PL1 fills season 1 (E1-E100); PL2 already holds S2E1-E3. Adding new
        # PL1 videos must roll PAST the committed episodes in season 2, never
        # reusing a (season, episode) another playlist already owns.
        show_rec = {"episodes": {}, "playlists": {}}
        _episodes_at(show_rec, "PL1", season=1, count=100)   # S01E01-E100
        _episodes_at(show_rec, "PL2", season=2, count=3)     # S02E01-E03
        result = yt_show.assign_new_episodes(
            show_rec, "PL1", ["a_new1", "a_new2"], "same")
        self.assertEqual(result, [("a_new1", 2, 4), ("a_new2", 2, 5)])
        committed = {(e["season"], e["episode"])
                     for e in show_rec["episodes"].values()}
        for (_vid, s, e) in result:
            self.assertNotIn((s, e), committed)

    def test_does_not_mutate_show_rec(self):
        show_rec = {"episodes": {}, "playlists": {}}
        _episodes_at(show_rec, "PL1", season=1, count=3)
        before = copy.deepcopy(show_rec["episodes"])
        yt_show.assign_new_episodes(show_rec, "PL1", ["v4", "v5"], "same")
        self.assertEqual(show_rec["episodes"], before)


class TestDriveUsage(unittest.TestCase):
    def test_parse_counts_trash_and_computes_free(self):
        data = {"cap_bytes": 100 * 1000 ** 3, "drives": [
            {"name": "TV", "bytes": 40 * 1000 ** 3, "trash_bytes": 10 * 1000 ** 3},
            {"name": "Courses", "bytes": 0, "trash_bytes": 0},
        ]}
        u = yt_show.parse_drive_usage(data)
        self.assertEqual(u["TV"]["used"], 50 * 1000 ** 3)   # content + trash
        self.assertEqual(u["TV"]["free"], 50 * 1000 ** 3)   # cap - used
        self.assertEqual(u["TV"]["pct"], 50.0)
        self.assertEqual(u["Courses"]["free"], 100 * 1000 ** 3)

    def test_parse_no_cap_yields_none_free(self):
        u = yt_show.parse_drive_usage({"drives": [{"name": "X", "bytes": 1}]})
        self.assertIsNone(u["X"]["free"])

    def test_parse_empty_payload(self):
        self.assertEqual(yt_show.parse_drive_usage({}), {})


if __name__ == "__main__":
    unittest.main()
