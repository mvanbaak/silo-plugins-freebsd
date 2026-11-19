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


class CatalogFilterTests(unittest.TestCase):
    def run_filter(self, filter_name, arg, feed):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "feed.json")
            with open(path, "w") as f:
                json.dump(feed, f)
            r = subprocess.run(
                ["jq", "-n", "--slurpfile", arg, path, "-f", filter_name],
                capture_output=True, text=True,
            )
        return r

    def run_official(self, feed):
        return self.run_filter(OFFICIAL, "official", feed)

    def run_community(self, feed):
        return self.run_filter(COMMUNITY, "community", feed)

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
