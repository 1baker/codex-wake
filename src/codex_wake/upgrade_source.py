"""Resolve public official Codex tags to bounded immutable source snapshots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .managed_inventory import InventoryError

COMMIT = re.compile('[0-9a-f]{40}')
VERSION = re.compile(r'\d+\.\d+\.\d+')


class OfficialSourceResolver:
    """Public network boundary used by the autonomous recipe template resolver."""
    def __init__(self, root, *, open_url=None, monotonic=None, maximum_bytes=512*1024**2, timeout_seconds=120):
        self.root = Path(root)
        self.open_url = open_url or urlopen
        self.monotonic = monotonic or time.monotonic
        if type(maximum_bytes) is not int or not 1 <= maximum_bytes <= 2*1024**3:
            raise InventoryError('invalid_configuration', 'source download bound invalid')
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
            raise InventoryError('invalid_configuration', 'source resolution timeout invalid')
        self.maximum_bytes, self.timeout_seconds = maximum_bytes, timeout_seconds

    def request(self, url, deadline):
        remaining = deadline-self.monotonic()
        if remaining <= 0:
            raise InventoryError('source_unavailable', 'official source resolution deadline exhausted')
        response = self.open_url(Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'codex-wake-upgrades'}),timeout=min(10,remaining))
        expected = urlsplit(url)
        actual = urlsplit(response.geturl())
        allowed = actual.scheme == 'https' and not actual.username and not actual.password and not actual.port
        if expected.hostname == 'api.github.com':
            allowed = allowed and actual.hostname == 'api.github.com' and actual.path == expected.path and not actual.query and not actual.fragment
        else:
            # Archive redirects are permitted only for this exact repository and
            # resolved commit, not arbitrary files on otherwise trusted hosting.
            commit = expected.path.split('/')[-1].removesuffix('.tar.gz')
            allowed = allowed and ((actual.hostname == 'github.com' and actual.path == expected.path) or
                (actual.hostname == 'codeload.github.com' and actual.path == '/openai/codex/tar.gz/'+commit)) and not actual.query and not actual.fragment
        if not allowed:
            response.close()
            raise InventoryError('source_unavailable', 'official source redirected outside pinned provenance')
        return response

    def object(self, url, deadline):
        with self.request(url,deadline) as stream:
            value = stream.read(1_000_001)
        if len(value)>1_000_000:
            raise InventoryError('source_unavailable','official tag metadata exceeds limit')
        parsed = json.loads(value)
        if not isinstance(parsed,dict) or not isinstance(parsed.get('object'),dict):
            raise InventoryError('source_unavailable','official tag metadata shape invalid')
        return parsed

    def resolve(self, version):
        if not isinstance(version,str) or VERSION.fullmatch(version) is None:
            raise InventoryError('source_unavailable','official stable version required')
        deadline = self.monotonic()+self.timeout_seconds
        tag = 'rust-v'+version
        reference = self.object('https://api.github.com/repos/openai/codex/git/ref/tags/'+tag,deadline)
        obj = reference.get('object',{})
        for _ in range(4):
            sha = obj.get('sha')
            if not isinstance(sha,str) or COMMIT.fullmatch(sha) is None:
                raise InventoryError('source_unavailable','official tag object identity invalid')
            if obj.get('type') == 'commit':break
            if obj.get('type') != 'tag':
                raise InventoryError('source_unavailable','official tag does not resolve to a commit')
            obj = self.object('https://api.github.com/repos/openai/codex/git/tags/'+sha,deadline).get('object',{})
        else:
            raise InventoryError('source_unavailable','official tag indirection exceeds limit')
        commit = obj['sha']
        url = 'https://github.com/openai/codex/archive/'+commit+'.tar.gz'
        directory = self.root / 'source-cache' / commit
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        destination = directory/'source.tar.gz'
        receipt = directory/'source.json'
        if destination.exists() and receipt.exists():
            saved = json.loads(receipt.read_text())
            hasher = hashlib.sha256();size=0
            with destination.open('rb') as stream:
                while chunk:=stream.read(1024**2):
                    size+=len(chunk)
                    if size>self.maximum_bytes or self.monotonic()>=deadline:
                        raise InventoryError('source_unavailable','cached source exceeds resource bound')
                    hasher.update(chunk)
            if saved.get('sha256') != hasher.hexdigest() or saved.get('commit') != commit:
                raise InventoryError('source_unavailable','cached official archive changed; reconciliation required')
            return dict(commit=commit,tag=tag,source=dict(official_url=url,archive_file=str(destination),sha256=hasher.hexdigest(),strip_components=1))
        if destination.exists() or receipt.exists():
            raise InventoryError('source_unavailable','partial official archive cache requires reconciliation')
        retained_bytes = sum(path.stat().st_size for path in (self.root/'source-cache').rglob('source.tar.gz') if path.is_file())
        remaining_bytes = self.maximum_bytes-retained_bytes
        if remaining_bytes <= 0:
            raise InventoryError('source_unavailable','official source cache budget exhausted')
        temporary = None
        try:
            hasher=hashlib.sha256();size=0
            with self.request(url,deadline) as stream, tempfile.NamedTemporaryFile('wb',dir=directory,delete=False) as output:
                temporary=Path(output.name);os.chmod(temporary,0o600)
                while chunk:=stream.read(1024**2):
                    if self.monotonic()>=deadline:
                        raise InventoryError('source_unavailable','official archive deadline exhausted')
                    size+=len(chunk)
                    if size>remaining_bytes:
                        raise InventoryError('source_unavailable','official source cache budget exhausted')
                    hasher.update(chunk);output.write(chunk)
                output.flush();os.fsync(output.fileno())
            if self.monotonic()>=deadline:
                raise InventoryError('source_unavailable','official archive deadline exhausted')
            if size == 0:
                raise InventoryError('source_unavailable','official archive is empty')
            # Link rather than overwrite a concurrently established immutable
            # cache. A second resolver must verify the winning bytes next pass.
            os.link(temporary,destination)
            from codex_profiles.upgrades import _atomic
            _atomic(receipt,dict(schema_version=1,commit=commit,sha256=hasher.hexdigest(),bytes=size,official_url=url))
            return dict(commit=commit,tag=tag,source=dict(official_url=url,archive_file=str(destination),sha256=hasher.hexdigest(),strip_components=1))
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
