#!/usr/bin/env python3
"""Prepare a verified HTTPS build context from this public repository's Git HEAD.

Does not start containers, request certificates, or alter an existing deployment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def hostname(value):
    if len(value) > 253 or '.' not in value or not all(
        re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', part)
        for part in value.split('.')
    ):
        raise ValueError('Use a DNS hostname without scheme, port, path or credentials')
    return value.lower()


def prepare(root, host):
    host = hostname(host)
    commit = git(root, 'rev-parse', 'HEAD').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected a SHA-1 Git commit')
    subprocess.run(['git', '-C', str(root), 'diff', '--quiet', 'HEAD', '--'], check=True)
    paths = json.loads(git(root, 'show', commit + ':runtime-files.json'))
    files = {}
    for name in paths:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or name.startswith('.') and name != '.dockerignore':
            raise ValueError('Unsafe runtime path')
        files[name] = git(root, 'show', commit + ':' + name)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    parent = root / '.releases'
    parent.mkdir(exist_ok=True)
    release = Path(tempfile.mkdtemp(prefix=commit[:12] + '-', dir=parent))
    release.chmod(0o755)
    for name, data in files.items():
        target = release / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644)
    identity = {'schema_version': '1.0', 'source_commit': commit, 'source_digest': digest,
                'verified_git_source': True, 'verification_method': 'git_show_exact_committed_runtime_inputs'}
    (release / 'framework/deploy/bc092/build-identity.json').write_text(json.dumps(identity) + '\n')
    (release / 'SOURCE-MANIFEST.json').write_text(json.dumps({**identity, 'files_sha256': hashes}, indent=2) + '\n')
    overlay = {
        'services': {
            'alpha': {'environment': {'AIMEC_DEMO_PUBLIC_ORIGIN': 'https://' + host}},
            'https': {
                'image': 'caddy:2.11.3-alpine', 'restart': 'unless-stopped',
                'ports': ['80:80', '443:443'],
                'environment': {'AIMEC_DEMO_HOSTNAME': host},
                'volumes': ['./framework/deploy/bc092/Caddyfile:/etc/caddy/Caddyfile:ro',
                            'public-tls-data:/data', 'public-tls-config:/config'],
                'networks': ['demo-ingress'], 'mem_limit': '128m', 'pids_limit': 64,
                'security_opt': ['no-new-privileges:true'],
                'depends_on': {'alpha': {'condition': 'service_healthy'}},
            },
        },
        'volumes': {'public-tls-data': {}, 'public-tls-config': {}},
    }
    (release / 'https.json').write_text(json.dumps(overlay, indent=2) + '\n')
    (release / 'release.env').write_text(
        'AIMEC_DEMO_SOURCE_COMMIT=' + commit + '\nAIMEC_LLM_MODEL=qwen3:1.7b\n'
        'AIMEC_OLLAMA_MEMORY=4g\nAIMEC_OLLAMA_CPUS=2.0\nAIMEC_DEMO_PORT=127.0.0.1:8020\n')
    os.chmod(release / 'release.env', 0o600)
    return release, identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hostname', required=True)
    args = parser.parse_args()
    release, identity = prepare(ROOT, args.hostname)
    print(json.dumps({'release_directory': str(release), **identity}, indent=2))
    command = ['docker', 'compose', '--project-directory', str(release),
               '--env-file', str(release / 'release.env'), '-p', 'aimec-webmcp-public',
               '-f', str(release / 'docker-compose.bc094-business-demo.yml'),
               '-f', str(release / 'https.json'), 'up', '-d', '--build', '--wait', '--wait-timeout', '900']
    print('\nOn your approved dedicated host, after checking DNS and free ports 80/443:')
    print(shlex.join(command))
    print('\nKeep the release directory and all Docker volumes. Nothing was deployed by this script.')


if __name__ == '__main__':
    main()
