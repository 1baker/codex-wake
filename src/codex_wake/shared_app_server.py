"""Bounded read-only metadata access to an existing shared app-server.

This client deliberately has no lifecycle or turn API. Discovery must never
start a daemon, subscribe to a thread, or load a saved conversation.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat
import subprocess
import time
from typing import Any, Callable

from . import __version__
from .records import WakeError


class SharedSourceError(WakeError):
    """The shared source cannot establish a complete observation."""


class SharedAppServerReader:
    ALLOWED_METHODS = frozenset({"initialize", "thread/loaded/list", "thread/list", "thread/read"})

    def __init__(self, endpoint: str, *, timeout: float = 10.0,
                 connector: Callable[..., Any] | None = None):
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 60:
            raise WakeError("source timeout must be positive and at most 60 seconds")
        if not endpoint.startswith("unix://") or not endpoint[7:]:
            raise SharedSourceError("an explicit existing unix://PATH endpoint is required")
        self.path = Path(endpoint[7:])
        if not self.path.is_absolute():
            raise WakeError("shared app-server socket path must be absolute")
        self.timeout = timeout
        self.connector = connector
        self.connection: Any = None
        self.deadline = 0.0
        self.sequence = 0
        self.server_metadata: dict[str, Any] = {}

    def __enter__(self) -> SharedAppServerReader:
        self.deadline = time.monotonic() + self.timeout
        try:
            if self.path.is_symlink():
                from .strict_runtime import resolve_executor_endpoint
                try:
                    self.path=Path(resolve_executor_endpoint('unix://'+str(self.path))[7:])
                except WakeError as exc:
                    raise SharedSourceError(str(exc)) from exc
            info = self.path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise SharedSourceError("shared endpoint must be an owned Unix socket")
            connector = self.connector
            if connector is None:
                from websockets.sync.client import unix_connect
                connector = unix_connect
            self.connection = connector(str(self.path), open_timeout=self.remaining(),
                                        close_timeout=min(1.0, self.timeout),
                                        compression=None, max_size=4 * 1024 * 1024)
            initialization = self.request("initialize", {
                "clientInfo": {"name": "codex_wake_discovery", "version": __version__},
                "capabilities": {"experimentalApi": True},
            })
            self.server_metadata = {key: initialization.get(key) for key in ("codexHome", "userAgent", "platformFamily", "platformOs")}
            self.connection.send(json.dumps({"method": "initialized"}))
            return self
        except Exception as exc:
            self.close()
            if isinstance(exc, WakeError):
                raise
            raise SharedSourceError(f"shared app-server unavailable: {type(exc).__name__}") from None

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SharedSourceError("shared metadata observation timed out")
        return remaining

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method not in self.ALLOWED_METHODS:
            raise WakeError("discovery method is not read-only")
        if method == "thread/read" and params.get("includeTurns") is not False:
            raise WakeError("discovery excludes conversation history")
        if self.connection is None:
            raise SharedSourceError("shared connection is not open")
        self.sequence += 1
        request_id = self.sequence
        try:
            self.remaining()
            self.connection.send(json.dumps({"id": request_id, "method": method, "params": params}))
            while True:
                response = json.loads(self.connection.recv(timeout=self.remaining()))
                if not isinstance(response, dict):
                    raise SharedSourceError("invalid shared app-server response")
                if "id" not in response:
                    continue  # Unsolicited notifications never establish metadata.
                if response.get("id") != request_id:
                    raise SharedSourceError("unexpected shared response identity")
                if "error" in response:
                    raise SharedSourceError(f"shared method unavailable: {method}")
                result = response.get("result")
                if not isinstance(result, dict):
                    raise SharedSourceError("invalid shared result")
                return result
        except WakeError:
            raise
        except Exception as exc:
            raise SharedSourceError(f"shared metadata read failed: {type(exc).__name__}") from None

    def loaded_threads(self, *, maximum: int = 10000, selected_thread_id: str | None = None) -> list[dict[str, Any]]:
        if maximum <= 0:
            raise WakeError("metadata population bound must be positive")
        ids: list[str] = []
        seen: set[str] = set()
        cursors: set[str] = set()
        cursor: str | None = None
        while True:
            page = self.request("thread/loaded/list", {"limit": 100, "cursor": cursor})
            data = page.get("data")
            if not isinstance(data, list) or any(not isinstance(x, str) or not x for x in data):
                raise SharedSourceError("invalid loaded-thread page")
            for thread_id in data:
                if thread_id in seen:
                    raise SharedSourceError("loaded-thread pagination changed or repeated")
                seen.add(thread_id)
                ids.append(thread_id)
                if len(ids) > maximum:
                    raise SharedSourceError("loaded-thread population exceeds observation bound")
            cursor = page.get("nextCursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise SharedSourceError("invalid or repeated loaded-thread cursor")
            cursors.add(cursor)
        return [self.read_thread(thread_id) for thread_id in ids
                if selected_thread_id is None or thread_id == selected_thread_id]

    def saved_threads(self, cwd: str, *, maximum: int = 1000) -> list[dict[str, Any]]:
        """Complete bounded history metadata, including unloaded CLI conversations."""
        from .tab_targets import canonical
        if type(maximum) is not int or maximum <= 0:
            raise WakeError('saved-thread population bound must be positive')
        canonical_cwd = canonical(cwd)
        rows, ids, cursors = [], set(), set()
        cursor = None
        while True:
            page = self.request('thread/list', dict(cwd=canonical_cwd, cursor=cursor,
                limit=100, archived=False, sourceKinds=['cli', 'vscode', 'appServer'], sortKey='updated_at'))
            data = page.get('data')
            if not isinstance(data, list):
                raise SharedSourceError('invalid saved-thread page')
            for thread in data:
                if (not isinstance(thread, dict) or not isinstance(thread.get('id'), str)
                        or not thread['id'] or thread['id'] in ids):
                    raise SharedSourceError('saved-thread pagination changed or repeated')
                ids.add(thread['id'])
                if len(ids) > maximum:
                    raise SharedSourceError('saved-thread population exceeds observation bound')
                try:
                    if canonical(thread['cwd']) != canonical_cwd:
                        raise SharedSourceError('saved-thread CWD filter mismatch')
                except (KeyError, TypeError, ValueError, OSError):
                    raise SharedSourceError('saved-thread CWD unavailable') from None
                rows.append({key: thread[key] for key in
                    ('id', 'cwd', 'name', 'updatedAt', 'source', 'status') if key in thread})
            cursor = page.get('nextCursor')
            if cursor is None:
                return rows
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise SharedSourceError('invalid or repeated saved-thread cursor')
            cursors.add(cursor)

    def read_thread(self, thread_id: str) -> dict[str, Any]:
        result = self.request("thread/read", {"threadId": thread_id, "includeTurns": False})
        thread = result.get("thread")
        if not isinstance(thread, dict) or thread.get("id") != thread_id:
            raise SharedSourceError("shared thread identity mismatch")
        # Explicit allowlist prevents transcripts or future response fields leaking.
        return {key: thread.get(key) for key in (
            "id", "name", "cwd", "status", "source", "parentThreadId", "agentPath",
            "canAcceptDirectInput", "modelProvider", "agentNickname", "agentRole",
        )}

    def close(self) -> None:
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def __exit__(self, *_: Any) -> None:
        self.close()


def locate_shared_endpoint(*, timeout: float = 10.0, codex_cmd: str = "codex", codex_home: str | None = None) -> str:
    """Use the installed CLI's read-only locator; never bootstrap a daemon."""
    try:
        result = subprocess.run([codex_cmd, "app-server", "daemon", "version"],
                                capture_output=True, text=True, timeout=timeout, check=True,
                                **({'env':dict(os.environ,CODEX_HOME=codex_home)} if codex_home else {}))
        metadata = json.loads(result.stdout)
        if metadata.get("status") != "running":
            raise SharedSourceError("shared daemon is not running")
        path = Path(metadata["socketPath"])
        if not path.is_absolute() or path.lstat().st_uid != os.geteuid():
            raise SharedSourceError("daemon locator returned an invalid socket")
        # Codex's supported control locator is an owned symlink to its socket.
        # Only this locator resolves it; explicit endpoints still reject links.
        resolved = path.resolve(strict=True)
        info = resolved.lstat()
        if info.st_uid != os.geteuid() or not stat.S_ISSOCK(info.st_mode):
            raise SharedSourceError("daemon locator target is not an owned socket")
        return "unix://" + str(resolved)
    except WakeError:
        raise
    except Exception as exc:
        raise SharedSourceError(f"daemon locator unavailable: {type(exc).__name__}") from None
