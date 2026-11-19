import json
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

_DEFAULT = object()


def make_source_repo(root, version, with_makefile=False, with_gosum=False):
    src = os.path.join(root, "src.git")
    os.makedirs(src, exist_ok=True)
    subprocess.run(["git", "init", "--bare", "-b", "main", src], check=True, capture_output=True)
    work = os.path.join(root, "work")
    os.makedirs(work)
    subprocess.run(["git", "clone", src, work], check=True, capture_output=True)
    with open(os.path.join(work, "main.go"), "w") as f:
        f.write('package main\nimport "fmt"\nvar version string\nfunc main(){fmt.Println(version)}\n')
    with open(os.path.join(work, "go.mod"), "w") as f:
        f.write('module example.com/testplugin\n\ngo 1.21\n')
    files = ["main.go", "go.mod"]
    if with_gosum:
        # Some plugins ship their sums; those builds must not be retargeted.
        with open(os.path.join(work, "go.sum"), "w"):
            pass
        files.append("go.sum")
    if with_makefile:
        # Mirrors plugins that patch a dependency in a prepare step and build
        # through their own Makefile.
        with open(os.path.join(work, "Makefile"), "w") as f:
            f.write('prepare:\n\t@true\n\nbuild: prepare\n'
                    '\tCGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=$(VERSION)" -o plugin .\n')
        files.append("Makefile")
    subprocess.run(["git", "-C", work, "add"] + files, check=True, capture_output=True)
    subprocess.run(["git", "-C", work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", work, "tag", f"v{version}"], check=True, capture_output=True)
    subprocess.run(["git", "-C", work, "push", "origin", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", work, "push", "origin", f"v{version}"], check=True, capture_output=True)
    # default branch may be master; ensure main
    return src


def make_upstream(root, plugin_id, version, repo_url, name="upstream.json"):
    manifest = {
        "plugin_id": plugin_id,
        "version": version,
        "silo_api_version": "v1",
        "supported_platforms": [{"os": "linux", "arch": "amd64"}],
        "capabilities": [],
    }
    upstream = {"plugins": [{"manifest": manifest, "repo_url": repo_url}]}
    path = os.path.join(root, name)
    with open(path, "w") as f:
        json.dump(upstream, f)
    return path


class BuildCatalogTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = self._tmpdir.name
        self.addCleanup(self._tmpdir.cleanup)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        os.makedirs(os.path.join(self.repo, "scripts"))
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shutil.copy(os.path.join(repo_root, "scripts", "build-catalog.sh"),
                    os.path.join(self.repo, "scripts", "build-catalog.sh"))
        os.chmod(os.path.join(self.repo, "scripts", "build-catalog.sh"), 0o755)
        self.version = "1.2.3"
        self.src = make_source_repo(self.tmp, self.version)
        self.repo_url = "https://github.com/example/test-plugin"
        self.gitconfig = os.path.join(self.tmp, "gitconfig")
        with open(self.gitconfig, "w") as f:
            f.write('[url "file://%s"]\n    insteadOf = https://github.com/example/test-plugin.git\n' % self.src)
        self.upstream = make_upstream(self.tmp, "test.plugin", self.version, self.repo_url)
        # existing manifest default
        self.existing = os.path.join(self.repo, "manifest.json")
        with open(self.existing, "w") as f:
            json.dump({"plugins": []}, f)

    def run_script(self, arches="amd64", bundle_url=None, force=False, existing=_DEFAULT,
                   manifest=None, built=None, upstream=None, go=None):
        env = dict(os.environ)
        env["GIT_CONFIG_GLOBAL"] = self.gitconfig
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["ARCHES"] = arches
        env["UPSTREAM"] = "file://" + (upstream or self.upstream)
        env["GO"] = go or "go"
        if bundle_url:
            env["BUNDLE_URL"] = bundle_url
        if force:
            env["FORCE"] = "1"
        if manifest:
            env["MANIFEST"] = manifest
        if built:
            env["BUILT"] = built
        if existing is _DEFAULT:
            existing = self.existing
        args = [os.path.join(self.repo, "scripts", "build-catalog.sh"),
                "https://example.com/releases/download/test"]
        if existing:
            args.append(existing)
        r = subprocess.run(args, cwd=self.repo, env=env, capture_output=True, text=True)
        return r

    def read_built(self, path=None):
        p = path or os.path.join(self.repo, "built.txt")
        if not os.path.exists(p):
            return ""
        with open(p) as f:
            return f.read()

    def read_manifest(self, path=None):
        with open(path or os.path.join(self.repo, "manifest.json")) as f:
            return json.load(f)

    def test_unsigned_migration_rebuilds(self):
        # existing entry same version but no bundle_url
        entry = {
            "manifest": {"plugin_id": "test.plugin", "version": self.version, "silo_api_version": "v1",
                         "supported_platforms": [{"os": "freebsd", "arch": "amd64"}], "capabilities": []},
            "repo_url": self.repo_url,
            "binaries": {"freebsd/amd64": {"url": "old", "checksum": "old"}},
        }
        with open(self.existing, "w") as f:
            json.dump({"plugins": [entry]}, f)
        r = self.run_script(bundle_url="https://example.com/bundle.json")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(self.read_built().strip(), "expected build")
        m = self.read_manifest()
        e = m["plugins"][0]
        self.assertEqual(e["bundle_url"], "https://example.com/bundle.json")
        self.assertNotEqual(e["binaries"]["freebsd/amd64"]["url"], "old")

    def test_signed_reuse_no_build(self):
        entry = {
            "manifest": {"plugin_id": "test.plugin", "version": self.version, "silo_api_version": "v1",
                         "supported_platforms": [{"os": "freebsd", "arch": "amd64"}], "capabilities": []},
            "repo_url": self.repo_url,
            "binaries": {"freebsd/amd64": {"url": "old", "checksum": "old"}},
            "bundle_url": "https://example.com/bundle.json",
        }
        with open(self.existing, "w") as f:
            json.dump({"plugins": [entry]}, f)
        r = self.run_script(bundle_url="https://example.com/bundle.json")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.read_built().strip(), "")
        m = self.read_manifest()
        self.assertEqual(m["plugins"][0]["binaries"]["freebsd/amd64"]["url"], "old")
        self.assertEqual(m["plugins"][0]["bundle_url"], "https://example.com/bundle.json")

    def test_missing_arch_rebuilds_all(self):
        entry = {
            "manifest": {"plugin_id": "test.plugin", "version": self.version, "silo_api_version": "v1",
                         "supported_platforms": [{"os": "freebsd", "arch": "amd64"}], "capabilities": []},
            "repo_url": self.repo_url,
            "binaries": {"freebsd/amd64": {"url": "old", "checksum": "old"}},
            "bundle_url": "https://example.com/bundle.json",
        }
        with open(self.existing, "w") as f:
            json.dump({"plugins": [entry]}, f)
        r = self.run_script(arches="amd64 arm64", bundle_url="https://example.com/bundle.json")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        built = self.read_built().strip().splitlines()
        self.assertEqual(len(built), 2)

    def test_exact_tag_failure_skips(self):
        # version with no tag
        bad_version = "9.9.9"
        self.upstream = make_upstream(self.tmp, "test.plugin", bad_version, self.repo_url)
        entry = {"plugins": []}
        with open(self.existing, "w") as f:
            json.dump(entry, f)
        # update upstream path in env by overriding run
        r = subprocess.run([os.path.join(self.repo, "scripts", "build-catalog.sh"),
                            "https://example.com/releases/download/test", self.existing],
                           cwd=self.repo, env={**os.environ, "GIT_CONFIG_GLOBAL": self.gitconfig, "GIT_CONFIG_NOSYSTEM": "1", "ARCHES": "amd64", "UPSTREAM": "file://" + self.upstream, "GO": "go"},
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.read_built().strip(), "")

    def test_partial_build_failure_no_entry(self):
        # Use an arch that cannot build (invalid GOARCH) alongside amd64
        entry = {"plugins": []}
        with open(self.existing, "w") as f:
            json.dump(entry, f)
        r = subprocess.run([os.path.join(self.repo, "scripts", "build-catalog.sh"),
                            "https://example.com/releases/download/test", self.existing],
                           cwd=self.repo, env={**os.environ, "GIT_CONFIG_GLOBAL": self.gitconfig, "GIT_CONFIG_NOSYSTEM": "1", "ARCHES": "amd64 bogus", "UPSTREAM": "file://" + self.upstream,
                                            "GO": "go", "BUNDLE_URL": "https://example.com/bundle.json"},
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        # should not record partial build
        self.assertEqual(self.read_built().strip(), "")
        with open(self.existing) as f:
            m = json.load(f)
        self.assertEqual(m["plugins"], [])
        self.assertFalse(os.path.exists(os.path.join(self.repo, "dist", "test.plugin-freebsd-amd64")))

    def test_invalid_inputs_rejected(self):
        cases = [
            ("bad/id", self.version, self.repo_url, ["amd64"]),
            ("test.plugin", "1.0.0 bad", self.repo_url, ["amd64"]),
            ("test.plugin", self.version, "/tmp/evil", ["amd64"]),
            ("test.plugin", self.version, "https://evil.example.com/x", ["amd64"]),
            ("test.plugin", self.version, "https://github.com/example/test-plugin/extra", ["amd64"]),
            ("test.plugin", self.version, "https://github.com/example/test-plugin?x=1", ["amd64"]),
            ("test.plugin", self.version, self.repo_url, ["amd64", "bogus"]),
        ]
        for bad_id, bad_version, bad_repo, arches in cases:
            with self.subTest(id=bad_id, version=bad_version, repo=bad_repo, arches=arches):
                upstream = make_upstream(self.tmp, bad_id, bad_version, bad_repo)
                # use a distinct upstream file per case
                entry = {"plugins": []}
                existing = os.path.join(self.tmp, "existing-%s.json" % abs(hash((bad_id, bad_version, bad_repo, tuple(arches)))))
                with open(existing, "w") as f:
                    json.dump(entry, f)
                before = Path(existing).read_bytes()
                dist = os.path.join(self.repo, "dist")
                os.makedirs(dist, exist_ok=True)
                pre_files = set(os.listdir(dist))
                built = os.path.join(self.repo, "built.txt")
                if os.path.exists(built):
                    os.remove(built)
                r = subprocess.run([os.path.join(self.repo, "scripts", "build-catalog.sh"),
                                    "https://example.com/releases/download/test", existing],
                                   cwd=self.repo, env={**os.environ, "GIT_CONFIG_GLOBAL": self.gitconfig,
                                                      "GIT_CONFIG_NOSYSTEM": "1", "ARCHES": " ".join(arches),
                                                      "UPSTREAM": "file://" + upstream, "GO": "go",
                                                      "BUNDLE_URL": "https://example.com/bundle.json"},
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                self.assertEqual(Path(existing).read_bytes(), before)
                _built = os.path.join(self.repo, "built.txt")
                self.assertEqual(Path(_built).read_text().strip() if os.path.exists(_built) else "", "")
                self.assertEqual(set(os.listdir(dist)), pre_files)

    def test_no_change_behavior(self):
        entry = {
            "manifest": {"plugin_id": "test.plugin", "version": self.version, "silo_api_version": "v1",
                         "supported_platforms": [{"os": "freebsd", "arch": "amd64"}], "capabilities": []},
            "repo_url": self.repo_url,
            "binaries": {"freebsd/amd64": {"url": "old", "checksum": "old"}},
            "bundle_url": "https://example.com/bundle.json",
        }
        with open(self.existing, "w") as f:
            json.dump({"plugins": [entry]}, f)
        r = self.run_script(bundle_url="https://example.com/bundle.json")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.read_built().strip(), "")


    # Two catalogs in one run: separate manifests and build lists, shared dist.
    def test_two_manifests_share_dist_but_not_build_lists(self):
        official = make_upstream(self.tmp, "test.plugin", self.version, self.repo_url,
                                 "upstream-official.json")
        community = make_upstream(self.tmp, "test.community", self.version, self.repo_url,
                                  "upstream-community.json")
        official_manifest = os.path.join(self.repo, "manifest.json")
        community_manifest = os.path.join(self.repo, "community-manifest.json")
        official_built = os.path.join(self.repo, "built-official.txt")
        community_built = os.path.join(self.repo, "built-community.txt")
        bundle = "https://example.com/bundle.json"

        r = self.run_script(bundle_url=bundle, existing=official_manifest,
                            manifest=official_manifest, built=official_built, upstream=official)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        r = self.run_script(bundle_url=bundle, existing=community_manifest,
                            manifest=community_manifest, built=community_built, upstream=community)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

        self.assertEqual([p["manifest"]["plugin_id"]
                          for p in self.read_manifest(official_manifest)["plugins"]], ["test.plugin"])
        self.assertEqual([p["manifest"]["plugin_id"]
                          for p in self.read_manifest(community_manifest)["plugins"]], ["test.community"])
        self.assertTrue(self.read_built(official_built).strip())
        self.assertTrue(self.read_built(community_built).strip())
        self.assertEqual(self.read_built(official_built).split()[0], "test.plugin")
        self.assertEqual(self.read_built(community_built).split()[0], "test.community")
        self.assertTrue(os.path.exists(os.path.join(self.repo, "dist", "test.plugin-freebsd-amd64")))
        self.assertTrue(os.path.exists(os.path.join(self.repo, "dist", "test.community-freebsd-amd64")))

    def test_prepare_step_builds_through_plugin_makefile(self):
        shutil.rmtree(self.src)
        shutil.rmtree(os.path.join(self.tmp, "work"))
        self.src = make_source_repo(self.tmp, self.version, with_makefile=True)
        r = self.run_script(bundle_url="https://example.com/bundle.json")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(self.read_built().strip())
        entry = self.read_manifest()["plugins"][0]
        self.assertEqual(entry["manifest"]["plugin_id"], "test.plugin")
        self.assertIn("freebsd/amd64", entry["binaries"])

    def test_manifest_only_selection_keeps_default_built_path(self):
        # MANIFEST alone: existing defaults to it, built.txt default still used.
        community_manifest = os.path.join(self.repo, "community-manifest.json")
        r = self.run_script(bundle_url="https://example.com/bundle.json", existing=None,
                            manifest=community_manifest)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(os.path.exists(community_manifest))
        self.assertTrue(self.read_built().strip())
        self.assertEqual(self.read_manifest(community_manifest)["plugins"][0]["manifest"]["plugin_id"],
                         "test.plugin")

    def fake_go(self):
        log = os.path.join(self.tmp, "go-args.log")
        path = os.path.join(self.tmp, "fake-go")
        with open(path, "w") as f:
            f.write('#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s"\nexec "%s" "$@"\n'
                    % (log, shutil.which("go")))
        os.chmod(path, 0o755)
        return path

    def go_args(self):
        with open(os.path.join(self.tmp, "go-args.log")) as f:
            return f.read()

    def test_missing_go_sum_builds_with_mod_mod(self):
        r = self.run_script(bundle_url="https://example.com/bundle.json", go=self.fake_go())
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(self.read_built().strip())
        self.assertIn("-mod=mod", self.go_args())

    def test_shipped_go_sum_builds_without_mod_mod(self):
        shutil.rmtree(self.src)
        shutil.rmtree(os.path.join(self.tmp, "work"))
        self.src = make_source_repo(self.tmp, self.version, with_gosum=True)
        r = self.run_script(bundle_url="https://example.com/bundle.json", go=self.fake_go())
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(self.read_built().strip())
        self.assertNotIn("-mod=mod", self.go_args())


if __name__ == "__main__":
    unittest.main()
