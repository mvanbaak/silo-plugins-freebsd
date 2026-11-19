import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "scripts" / "silocatalog"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "kometa-manifest.protojson.json"


def run_tool(*args):
    # go run resolves the committed go.mod/go.sum; the fixture keeps it offline.
    return subprocess.run(["go", "run", ".", *args], cwd=TOOL, capture_output=True, text=True)


def read_json(path):
    with open(path) as f:
        return json.load(f)


class SiloCatalogTests(unittest.TestCase):
    def test_normalize_turns_enum_names_into_numbers(self):
        r = run_tool("normalize", str(FIXTURE))
        self.assertEqual(r.returncode, 0, r.stderr)
        manifest = json.loads(r.stdout)
        self.assertEqual(manifest["plugin_id"], "community.kometa-sync")
        self.assertEqual(manifest["version"], "0.5.0")
        controls = [f["control"] for s in manifest["global_config_schema"]
                    for f in s.get("admin_form", {}).get("fields", [])]
        self.assertEqual(controls, [1, 3, 3, 1, 3, 4, 5, 5, 5, 5])

    def test_normalize_rejects_unknown_fields(self):
        with open(FIXTURE) as f:
            manifest = json.load(f)
        manifest["no_such_field"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json") as tmp:
            json.dump(manifest, tmp)
            tmp.flush()
            r = run_tool("normalize", tmp.name)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown field", r.stderr)

    def test_check_rejects_string_enums(self):
        with open(FIXTURE) as f:
            manifest = json.load(f)
        index = {"plugins": [{"manifest": manifest,
                              "repo_url": "https://github.com/BEisem/silo-plex-artwork-sync"}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json") as tmp:
            json.dump(index, tmp)
            tmp.flush()
            r = run_tool("check", tmp.name)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cannot unmarshal string", r.stderr)

    def test_check_accepts_repository_catalogs(self):
        path = ROOT / "manifest.json"
        r = run_tool("check", str(path))
        self.assertEqual(r.returncode, 0, r.stderr)
        entries = read_json(path)["plugins"]
        self.assertEqual(r.stdout.splitlines()[0], "%d entries" % len(entries))
        expected = ["%s %s" % (e["manifest"]["plugin_id"], e["manifest"]["version"])
                    for e in entries]
        self.assertEqual(r.stdout.splitlines()[1:], expected)


if __name__ == "__main__":
    unittest.main()
