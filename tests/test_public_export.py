"""Offline packaging checks; no Docker, network or model inference is performed."""
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_https', ROOT / 'scripts/prepare_https.py')
https = importlib.util.module_from_spec(spec)
spec.loader.exec_module(https)


class ExportTests(unittest.TestCase):
    def test_runtime_allowlist_is_complete(self):
        paths = json.loads((ROOT / 'runtime-files.json').read_text())
        self.assertEqual(len(paths), len(set(paths)))
        for name in paths:
            self.assertTrue((ROOT / name).is_file(), name)
            self.assertNotIn('..', Path(name).parts)
        for dockerfile in ROOT.glob('framework/services/**/Dockerfile.*'):
            if dockerfile.name.endswith('.dockerignore'):
                continue
            for line in dockerfile.read_text().splitlines():
                if line.startswith('COPY '):
                    for source in shlex.split(line)[1:-1]:
                        self.assertIn(source, paths, str(dockerfile) + ': ' + source)

    def test_json_inputs_parse(self):
        for file in ROOT.glob('framework/**/*.json'):
            self.assertIsInstance(json.loads(file.read_text()), dict, str(file))

    def test_public_license_and_no_old_verifier(self):
        self.assertIn('MIT License', (ROOT / 'LICENSE').read_text())
        self.assertIn('Copyright (c) 2026 AIMEC', (ROOT / 'LICENSE').read_text())
        self.assertFalse((ROOT / 'framework/scripts/verify_bc091_browser.py').exists())

    def test_hostname_validation(self):
        self.assertEqual(https.hostname('Demo.Example.com'), 'demo.example.com')
        for host in ['localhost', 'https://example.com', 'user@example.com',
                     'example.com:443', 'example.com/path', 'a..com', '-a.com']:
            with self.assertRaises(ValueError, msg=host):
                https.hostname(host)


@unittest.skipUnless(shutil.which('git'), 'Git required for release preparation tests')
class GitReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        paths = json.loads((ROOT / 'runtime-files.json').read_text())
        for name in paths + ['runtime-files.json']:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Export test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'Isolated test fixture')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args])

    def test_prepare_exact_release_without_deployment(self):
        release, identity = https.prepare(self.root, 'demo.example.com')
        self.assertTrue(identity['verified_git_source'])
        self.assertEqual(identity['source_commit'], self.git('rev-parse', 'HEAD').decode().strip())
        self.assertEqual(len(identity['source_digest']), 64)
        self.assertEqual(json.loads((release / 'framework/deploy/bc092/build-identity.json').read_text()), identity)
        overlay = json.loads((release / 'https.json').read_text())
        self.assertEqual(overlay['services']['alpha']['environment']['AIMEC_DEMO_PUBLIC_ORIGIN'],
                         'https://demo.example.com')
        self.assertEqual(overlay['services']['https']['ports'], ['80:80', '443:443'])
        self.assertEqual((release / 'release.env').stat().st_mode & 0o777, 0o600)

    def test_dirty_tracked_source_rejected(self):
        with (self.root / 'docker-compose.bc094-business-demo.yml').open('a') as file:
            file.write('\n# uncommitted change\n')
        with self.assertRaises(subprocess.CalledProcessError):
            https.prepare(self.root, 'demo.example.com')
        self.assertFalse((self.root / '.releases').exists())

    def test_untracked_files_not_exported(self):
        (self.root / 'private-local-note.txt').write_text('Synthetic excluded fixture')
        release, _ = https.prepare(self.root, 'demo.example.com')
        self.assertFalse((release / 'private-local-note.txt').exists())


if __name__ == '__main__':
    unittest.main()
