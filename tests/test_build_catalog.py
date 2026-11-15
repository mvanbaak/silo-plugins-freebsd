import json
import os
import shutil
import subprocess
import tempfile
import unittest


def make_source_repo(root, version):
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
    subprocess.run(["git", "-C", work, "add", "main.go", "go.mod"], check=True, capture_output=True)
    subprocess.run(["git", "-C", work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", work, "tag", f"v{version}"], check=True, capture_output=True)
    subprocess.run(["git", "-C", work, "push", "origin", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", work, "push", "origin", f"v{version}"], check=True, capture_output=True)
    # default branch may be master; ensure main
    return src


def make_upstream(root, plugin_id, version, repo_url):
    manifest = {
        "plugin_id": plugin_id,
        "version": version,
        "silo_api_version": "v1",
        "supported_platforms": [{"os": "linux", "arch": "amd64"}],
        "capabilities": [],
    }
    upstream = {"plugins": [{"manifest": manifest, "repo_url": repo_url}]}
    path = os.path.join(root, "upstream.json")
    with open(path, "w") as f:
        json.dump(upstream, f)
    return path


class BuildCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
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

    def run_script(self, arches="amd64", bundle_url=None, force=False, existing=None):
        env = dict(os.environ)
        env["GIT_CONFIG_GLOBAL"] = self.gitconfig
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["ARCHES"] = arches
        env["UPSTREAM"] = "file://" + self.upstream
        env["GO"] = "go"
        if bundle_url:
            env["BUNDLE_URL"] = bundle_url
        if force:
            env["FORCE"] = "1"
        args = [os.path.join(self.repo, "scripts", "build-catalog.sh"),
                "https://example.com/releases/download/test", existing or self.existing]
        r = subprocess.run(args, cwd=self.repo, env=env, capture_output=True, text=True)
        return r

    def read_built(self):
        p = os.path.join(self.repo, "built.txt")
        if not os.path.exists(p):
            return ""
        return open(p).read()

    def read_manifest(self):
        return json.load(open(os.path.join(self.repo, "manifest.json")))

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
        envup = None
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
        m = json.load(open(self.existing))
        self.assertEqual(m["plugins"], [])
        self.assertFalse(os.path.exists(os.path.join(self.repo, "dist", "test-plugin-freebsd-amd64")))

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
                before = open(existing, "rb").read()
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
                self.assertEqual(open(existing, "rb").read(), before)
                self.assertEqual(open(os.path.join(self.repo, "built.txt")).read().strip() if os.path.exists(os.path.join(self.repo, "built.txt")) else "", "")
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


if __name__ == "__main__":
    unittest.main()
