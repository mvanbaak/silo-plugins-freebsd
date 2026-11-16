import json
import os
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILTER = os.path.join(REPO_ROOT, "scripts", "merge-upstream.jq")


def make_feed(plugins):
    return {"plugins": plugins}


def entry(pid, repo="https://github.com/example/repo"):
    return {"manifest": {"plugin_id": pid, "version": "1.0.0"}, "repo_url": repo}


class MergeUpstreamTests(unittest.TestCase):
    def run_merge(self, official, community):
        d = tempfile.mkdtemp()
        op = os.path.join(d, "official.json")
        cp = os.path.join(d, "community.json")
        with open(op, "w") as f:
            json.dump(official, f)
        with open(cp, "w") as f:
            json.dump(community, f)
        r = subprocess.run(
            ["jq", "-n", "--slurpfile", "official", op, "--slurpfile", "community", cp, "-f", FILTER],
            capture_output=True, text=True,
        )
        return r

    def test_approved_community_only(self):
        official_ids = ["silo.tmdb", "silo.tvdb", "silo.theintrodb", "silo.tmdb2" if False else "silo.tmdb"]
        # use realistic official set including defaults
        official = make_feed([entry("silo.tmdb"), entry("silo.tvdb"), entry("silo.theintrodb"), entry("silo.mdblist")])
        community = make_feed([
            entry("silo.requests.arr", "https://github.com/Silo-Community/silo-plugins-requests-arr"),
            entry("silo.requests.seerr", "https://github.com/Silo-Community/silo-plugins-requests-seerr"),
            entry("ironicbadger.network-access.tailscale", "https://github.com/Silo-Community/silo-plugin-tailscale"),
            entry("silo.watchprovider.scrob", "https://github.com/Silo-Community/silo-plugin-watchprovider-scrob"),
        ])
        r = self.run_merge(official, community)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        ids = [p["manifest"]["plugin_id"] for p in out["plugins"]]
        self.assertEqual(ids, ["silo.tmdb", "silo.tvdb", "silo.theintrodb", "silo.mdblist", "silo.requests.arr", "silo.requests.seerr"])
        self.assertNotIn("ironicbadger.network-access.tailscale", ids)
        self.assertNotIn("silo.watchprovider.scrob", ids)

    def test_duplicate_id_fails(self):
        official = make_feed([entry("silo.tmdb"), entry("silo.tvdb"), entry("silo.theintrodb"), entry("silo.requests.arr")])
        community = make_feed([entry("silo.requests.arr")])
        r = self.run_merge(official, community)
        self.assertNotEqual(r.returncode, 0)

    def test_malformed_official_fails(self):
        r = self.run_merge({"plugins": "nope"}, make_feed([]))
        # community empty array? need defaults; but malformed official should fail first
        self.assertNotEqual(r.returncode, 0)

    def test_malformed_community_fails(self):
        official = make_feed([entry("silo.tmdb"), entry("silo.tvdb"), entry("silo.theintrodb")])
        r = self.run_merge(official, {"plugins": [{"manifest": {"plugin_id": "x"}}]})
        self.assertNotEqual(r.returncode, 0)

    def test_empty_official_fails(self):
        official = make_feed([])
        community = make_feed([entry("silo.requests.arr")])
        r = self.run_merge(official, community)
        self.assertNotEqual(r.returncode, 0)

    def test_missing_default_metadata_fails(self):
        official = make_feed([entry("silo.mdblist")])
        community = make_feed([])
        r = self.run_merge(official, community)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
