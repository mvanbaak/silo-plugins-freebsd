import json
import os
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFICIAL = os.path.join(REPO_ROOT, "scripts", "official-catalog.jq")
COMMUNITY = os.path.join(REPO_ROOT, "scripts", "community-catalog.jq")


def make_feed(plugins):
    return {"plugins": plugins}


def entry(pid, repo="https://github.com/example/repo"):
    return {"manifest": {"plugin_id": pid, "version": "1.0.0"}, "repo_url": repo}


DEFAULTS = ["silo.tmdb", "silo.tvdb", "silo.theintrodb"]
COMMUNITY_IDS = [
    "silo.requests.arr",
    "silo.requests.seerr",
    "ironicbadger.network-access.tailscale",
    "silo.watchprovider.scrob",
]

_ABSENT = object()


class CatalogFilterTests(unittest.TestCase):
    def run_filter(self, filter_name, arg, feed, extra=_ABSENT, extra_text=None):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "feed.json")
            with open(path, "w") as f:
                json.dump(feed, f)
            cmd = ["jq", "-n", "--slurpfile", arg, path]
            if extra is not _ABSENT:
                extra_path = os.path.join(d, "extra.json")
                with open(extra_path, "w") as f:
                    if extra_text is not None:
                        f.write(extra_text)
                    else:
                        json.dump(extra, f)
                cmd += ["--slurpfile", "extra", extra_path]
            cmd += ["-f", filter_name]
            r = subprocess.run(cmd, capture_output=True, text=True)
        return r

    def run_official(self, feed):
        return self.run_filter(OFFICIAL, "official", feed)

    def run_community(self, feed, extra=_ABSENT, extra_text=None):
        return self.run_filter(COMMUNITY, "community", feed, extra, extra_text)

    def ids(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return [p["manifest"]["plugin_id"] for p in json.loads(r.stdout)["plugins"]]

    def test_official_keeps_only_official_feed(self):
        official = make_feed([entry(i) for i in DEFAULTS] + [entry("silo.mdblist")])
        self.assertEqual(self.ids(self.run_official(official)),
                         DEFAULTS + ["silo.mdblist"])

    def test_community_keeps_all_community_plugins(self):
        community = make_feed([entry(i) for i in COMMUNITY_IDS])
        self.assertEqual(self.ids(self.run_community(community)), COMMUNITY_IDS)

    def test_outputs_do_not_overlap(self):
        official = make_feed([entry(i) for i in DEFAULTS])
        community = make_feed([entry(i) for i in COMMUNITY_IDS])
        official_ids = self.ids(self.run_official(official))
        community_ids = self.ids(self.run_community(community))
        self.assertEqual(set(official_ids) & set(community_ids), set())

    def test_duplicate_id_in_official_fails(self):
        official = make_feed([entry(i) for i in DEFAULTS] + [entry("silo.mdblist"),
                                                            entry("silo.mdblist")])
        self.assertNotEqual(self.run_official(official).returncode, 0)

    def test_duplicate_id_in_community_fails(self):
        community = make_feed([entry("silo.requests.arr"), entry("silo.requests.arr")])
        self.assertNotEqual(self.run_community(community).returncode, 0)

    def test_community_appends_extras_after_feed(self):
        community = make_feed([entry(i) for i in COMMUNITY_IDS])
        extra = make_feed([entry("community.kometa-sync",
                                 "https://github.com/BEisem/silo-plex-artwork-sync")])
        r = self.run_community(community, extra)
        self.assertEqual(self.ids(r), COMMUNITY_IDS + ["community.kometa-sync"])
        self.assertEqual(json.loads(r.stdout)["plugins"][-1], extra["plugins"][0])

    def test_duplicate_id_between_feed_and_extras_fails(self):
        community = make_feed([entry(i) for i in COMMUNITY_IDS])
        extra = make_feed([entry(COMMUNITY_IDS[0])])
        self.assertNotEqual(self.run_community(community, extra).returncode, 0)

    def test_duplicate_id_between_extras_fails(self):
        community = make_feed([entry(i) for i in COMMUNITY_IDS])
        extra = make_feed([entry("community.kometa-sync"), entry("community.kometa-sync")])
        self.assertNotEqual(self.run_community(community, extra).returncode, 0)

    def test_malformed_extra_fails(self):
        community = make_feed([entry(i) for i in COMMUNITY_IDS])
        cases = [
            {"plugins": "nope"},
            make_feed([{"manifest": {"plugin_id": "x"}}]),
            make_feed(["nope"]),
            [],
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                self.assertNotEqual(self.run_community(community, extra).returncode, 0)

    def test_absent_or_empty_extra_matches_feed_only(self):
        community = make_feed([entry(i) for i in COMMUNITY_IDS])
        feed_only = json.loads(self.run_community(community).stdout)
        same = [
            self.run_community(community, make_feed([])),
            self.run_community(community, extra_text=""),
        ]
        for r in same:
            self.assertEqual(json.loads(r.stdout), feed_only, r.stderr)

    def test_malformed_official_fails(self):
        self.assertNotEqual(self.run_official({"plugins": "nope"}).returncode, 0)
        bad = make_feed([entry("silo.mdblist"), {"manifest": {"plugin_id": "x"}}])
        self.assertNotEqual(self.run_official(bad).returncode, 0)

    def test_malformed_community_fails(self):
        self.assertNotEqual(self.run_community({"plugins": "nope"}).returncode, 0)
        self.assertNotEqual(
            self.run_community({"plugins": [{"manifest": {"plugin_id": "x"}}]}).returncode, 0)

    def test_empty_official_fails(self):
        self.assertNotEqual(self.run_official(make_feed([])).returncode, 0)

    def test_missing_default_metadata_fails(self):
        self.assertNotEqual(self.run_official(make_feed([entry("silo.mdblist")])).returncode, 0)

    def test_lookalike_default_metadata_ids_fail(self):
        cases = [
            ["silo.tmdbx", "silo.tvdb", "silo.theintrodb"],
            ["silo.tmdb", "silo.tvdbx", "silo.theintrodb"],
            ["silo.tmdb", "silo.tvdb", "silo.theintrodbx"],
            ["silo.tmdbx", "silo.tvdbx", "silo.theintrodbx"],
        ]
        for ids in cases:
            with self.subTest(ids=ids):
                official = make_feed([entry(i) for i in ids] + [entry("silo.mdblist")])
                r = self.run_official(official)
                self.assertNotEqual(r.returncode, 0, r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
