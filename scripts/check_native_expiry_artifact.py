"""Verify the shipped Native patch matches its accepted source, without a build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def check(root, native_repo=None):
    manifest = json.loads((root / 'patches/codex/0248-native-expiry.json').read_text())
    acceptance = json.loads((root / 'docs/dev/evidence/issue0695/service-instant-closeout.json').read_text())
    patch = root / 'patches/codex/0248-native-expiry.patch'
    problems = []
    if manifest['source_commit'] != acceptance['native_source']:
        problems.append('Native patch source differs from accepted Native source')
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest['patch_sha256']:
        problems.append('Native patch digest differs from manifest')
    if manifest.get('wire_contract') != dict(contract_version=2,
            basis='service_measurement', receipt_time_bound=False):
        problems.append('Native patch manifest lacks the accepted wire contract')
    if problems:
        raise ValueError('; '.join(problems))
    result = dict(state='passed', source=manifest['source_commit'],
        patch_sha256=manifest['patch_sha256'], reconstruction='not_requested')
    if native_repo is not None:
        with tempfile.TemporaryDirectory(prefix='native-expiry-index-') as temporary:
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / 'index'))
            command = ['git', '-C', str(native_repo)]
            subprocess.run([*command, 'read-tree', manifest['base']], env=env, check=True)
            subprocess.run([*command, 'apply', '--cached', '--check', str(patch)],
                           env=env, check=True)
            subprocess.run([*command, 'apply', '--cached', str(patch)], env=env, check=True)
            actual = subprocess.check_output([*command, 'write-tree'], env=env, text=True).strip()
            expected = subprocess.check_output([*command, 'rev-parse',
                manifest['source_commit'] + '^{tree}'], text=True).strip()
            if actual != expected:
                raise ValueError('Reconstructed Native tree differs from accepted source')
            result.update(reconstruction='exact_tree_match', tree=actual)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--native-repo', type=Path)
    options = parser.parse_args()
    try:
        print(json.dumps(check(options.repo_root.resolve(), options.native_repo)))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
