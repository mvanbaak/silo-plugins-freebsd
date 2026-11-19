import json
import os
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFICIAL = os.path.join(REPO_ROOT, "scripts", "official-catalog.jq")
EXTRAS = os.path.join(REPO_ROOT, "scripts", "extras-catalog.jq")


def make_feed(plugins):
    return {"plugins": plugins}


def entry(pid, repo="https://github.com/example/repo"):
    return {"manifest": {"plugin_id": pid, "version": "1.0.0"}, "repo_url": repo}


DEFAULTS = ["silo.tmdb", "silo.tvdb", "silo.theintrodb"]
EXTRA_IDS = ["community.kometa-sync"]

_ABSENT = object()


class CatalogFilterTests(unittest.TestCase):
    def run_filter(self, filter_name, arg, feed, extra=_ABSENT, extra_text=None):
        with tempfile.TemporaryDirectory() as d:
            cmd = ["jq", "-n"]
            if feed is not _ABSENT:
                path = os.path.join(d, "feed.json")
                with open(path, "w") as f:
                    json.dump(feed, f)
                cmd += ["--slurpfile", arg, path]
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

    def run_extras(self, extra=_ABSENT, extra_text=None):
        return self.run_filter(EXTRAS, "extra", _ABSENT, extra, extra_text)

    def ids(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return [p["manifest"]["plugin_id"] for p in json.loads(r.stdout)["plugins"]]

    def test_official_keeps_only_official_feed(self):
        official = make_feed([entry(i) for i in DEFAULTS] + [entry("silo.mdblist")])
        self.assertEqual(self.ids(self.run_official(official)),
                         DEFAULTS + ["silo.mdblist"])

    def test_extras_keeps_all_extra_plugins(self):
        extra = make_feed([entry(i) for i in EXTRA_IDS])
        self.assertEqual(self.ids(self.run_extras(extra)), EXTRA_IDS)

    def test_extras_passes_entries_through_unchanged(self):
        extra = make_feed([entry("community.kometa-sync",
                                 "https://github.com/BEisem/silo-plex-artwork-sync")])
        r = self.run_extras(extra)
        self.assertEqual(self.ids(r), ["community.kometa-sync"])
        self.assertEqual(json.loads(r.stdout)["plugins"][0], extra["plugins"][0])

    def test_outputs_do_not_overlap(self):
        official = make_feed([entry(i) for i in DEFAULTS])
        extra = make_feed([entry(i) for i in EXTRA_IDS])
        official_ids = self.ids(self.run_official(official))
        extra_ids = self.ids(self.run_extras(extra))
        self.assertEqual(set(official_ids) & set(extra_ids), set())

    def test_duplicate_id_in_official_fails(self):
        official = make_feed([entry(i) for i in DEFAULTS] + [entry("silo.mdblist"),
                                                            entry("silo.mdblist")])
        self.assertNotEqual(self.run_official(official).returncode, 0)

    def test_duplicate_id_in_extras_fails(self):
        extra = make_feed([entry("community.kometa-sync"), entry("community.kometa-sync")])
        self.assertNotEqual(self.run_extras(extra).returncode, 0)

    def test_malformed_extras_fails(self):
        cases = [
            {"plugins": "nope"},
            make_feed([{"manifest": {"plugin_id": "x"}}]),
            make_feed(["nope"]),
            [],
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                self.assertNotEqual(self.run_extras(extra).returncode, 0)

    def test_empty_extras_yields_empty_plugins(self):
        cases = [
            self.run_extras(make_feed([])),
            self.run_extras(extra_text=""),
        ]
        for r in cases:
            self.assertEqual(json.loads(r.stdout), {"plugins": []}, r.stderr)

    def test_missing_extras_yields_empty_plugins(self):
        r = self.run_extras()
        self.assertEqual(json.loads(r.stdout), {"plugins": []}, r.stderr)

    def test_malformed_official_fails(self):
        self.assertNotEqual(self.run_official({"plugins": "nope"}).returncode, 0)
        bad = make_feed([entry("silo.mdblist"), {"manifest": {"plugin_id": "x"}}])
        self.assertNotEqual(self.run_official(bad).returncode, 0)

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
