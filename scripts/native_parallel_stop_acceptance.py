"""Opt-in UID1017 two-active-tools Stop acceptance using a synthetic loopback provider.

Run with the installed Wake Python environment; no model credentials are needed.
--omit-stop is an intentional negative control: exit1 plus tool_continued_after_stop
proves the marker assertion detects missing cancellation. No exhaustive scheduler
interleaving or queued-tool cancellation proof is implied. Never run in working state.
"""

import argparse, json, os, time, subprocess, threading, hashlib, sys, signal, shlex, stat
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from codex_wake.native_protocol import native_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--expected-native-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--omit-stop", action="store_true")
    args = parser.parse_args()
    if os.getuid() != 1017:
        parser.error("Run only in the isolated codex-daemon-test UID1017 account")
    binary = args.native.resolve(strict=True)
    if hashlib.sha256(binary.read_bytes()).hexdigest() != args.expected_native_sha256:
        parser.error("native executable hash differs from expected package")
    os.umask(0o077)
    base = args.output.absolute()
    base.mkdir(mode=0o700)
    home = base / "home"
    home.mkdir()
    work = base / "work"
    work.mkdir()
    report = {
        "state": "running",
        "native_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "external_provider_calls": 0,
        "calls": 0,
        "mode": "omit_stop" if args.omit_stop else "stop",
        "scope": "two already-active tools; not exhaustive scheduling proof",
        "started_monotonic": time.monotonic(),
    }

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            try:
                size = int(self.headers["Content-Length"])
                if not 0 < size <= 8 * 1024 * 1024:
                    raise ValueError("provider input size bound exceeded")
                body = json.loads(self.rfile.read(size))
                report["calls"] += 1
                if report["calls"] != 1:
                    raise RuntimeError("unexpected extra provider request")
                names = []
                for tool in body.get("tools", []):
                    if tool.get("type") == "namespace":
                        names.extend(t["name"] for t in tool.get("tools", []))
                    elif tool.get("name"):
                        names.append(tool["name"])
                report["tool_names"] = names
                name = next(
                    (
                        x
                        for x in ["exec_command", "shell_command", "shell"]
                        if x in names
                    ),
                    None,
                )
                if not name:
                    raise RuntimeError("fixture has no advertised local tool")
                rows = [
                    dict(type="response.created", response=dict(id="isolated-stop"))
                ]
                for n in range(2):
                    code = (
                        "from pathlib import Path;import os,time;p=Path("
                        + repr(str(work))
                        + ");(p/"
                        + repr("started" + str(n))
                        + ").write_text(str(os.getpid()));\nwhile not (p/'release').exists():time.sleep(.01)\n(p/"
                        + repr("late" + str(n))
                        + ").write_text('ran after release')"
                    )
                    cmd = shlex.join([sys.executable, "-c", code])
                    if name == "exec_command":
                        args = {
                            "cmd": cmd,
                            "yield_time_ms": 10000,
                            "max_output_tokens": 100,
                        }
                    elif name == "shell_command":
                        args = {"command": cmd, "timeout_ms": 10000}
                    else:
                        args = {
                            "command": [sys.executable, "-c", code],
                            "timeout_ms": 10000,
                        }
                    rows.append(
                        dict(
                            type="response.output_item.done",
                            item=dict(
                                type="function_call",
                                name=name,
                                call_id="tool-" + str(n),
                                arguments=json.dumps(args),
                            ),
                        )
                    )
                rows.append(
                    dict(
                        type="response.completed",
                        response=dict(
                            id="isolated-stop",
                            usage=dict(
                                input_tokens=10,
                                input_tokens_details=dict(cached_tokens=0),
                                output_tokens=1,
                                total_tokens=11,
                            ),
                        ),
                    )
                )
                data = "".join(
                    "event: " + r["type"] + "\ndata: " + json.dumps(r) + "\n\n"
                    for r in rows
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                report["provider_error"] = str(e)
                self.send_error(500)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    (home / "config.toml").write_text(
        'model="gpt-5.4"\nmodel_provider="isolated"\napproval_policy="never"\nsandbox_mode="danger-full-access"\n[model_providers.isolated]\nname="Isolated stop probe"\nbase_url="http://127.0.0.1:'
        + str(server.server_port)
        + '/v1"\nwire_api="responses"\nrequires_openai_auth=false\nrequest_max_retries=0\nstream_max_retries=0\nsupports_websockets=false\n'
    )
    log = (base / "native.log").open("w")
    sock = base / "native.sock"
    env = {
        k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TERM") if k in os.environ
    }
    env["CODEX_HOME"] = str(home)
    proc = subprocess.Popen(
        [str(binary), "app-server", "--listen", "unix://" + str(sock)],
        cwd=work,
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )

    def rpc(method, **params):
        report["last_rpc"] = method
        report["socket_lstat"] = [sock.lstat().st_mode, sock.lstat().st_uid]
        report["euid"] = os.geteuid()
        return native_request(
            "unix://" + str(sock.resolve(strict=True)), str(binary), method, params, 10
        )

    def process_state(pid):
        try:
            return (
                (Path("/proc") / str(pid) / "stat")
                .read_text()
                .rsplit(")", 1)[1]
                .split()[0]
            )
        except (FileNotFoundError, ProcessLookupError):
            return "absent"
        except PermissionError:
            return "unknown"

    def wait(fn, label, seconds=15):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if fn():
                return
            if proc.poll() is not None:
                raise RuntimeError("native exited")
            if "provider_error" in report:
                raise RuntimeError(report["provider_error"])
            time.sleep(0.03)
        raise TimeoutError(label)

    try:

        def socket_ready():
            try:
                return (
                    stat.S_ISSOCK(sock.stat().st_mode)
                    and sock.stat().st_uid == os.getuid()
                )
            except FileNotFoundError:
                return False

        wait(socket_ready, "owned native socket")
        tid = rpc("thread/start", cwd=str(work))["thread"]["id"]
        report["thread"] = tid
        turn = rpc(
            "turn/start",
            threadId=tid,
            input=[
                dict(
                    type="text", text="Run the two local fixture commands concurrently."
                )
            ],
        )["turn"]["id"]
        report["turn"] = turn
        wait(
            lambda: all((work / ("started" + str(n))).exists() for n in range(2)),
            "both tools concurrently started",
        )
        pids = [int((work / ("started" + str(n))).read_text()) for n in range(2)]
        report["tool_pids"] = pids
        if not args.omit_stop:
            report["interrupt"] = rpc("turn/interrupt", threadId=tid, turnId=turn)
        else:
            report["negative_control"] = "Stop omitted"

        def terminal():
            rows = rpc(
                "thread/turns/list", threadId=tid, limit=20, itemsView="notLoaded"
            )["data"]
            v = next((x for x in rows if x["id"] == turn), {})
            report["turn_status"] = v.get("status")
            return v.get("status") == "interrupted"

        if not args.omit_stop:
            wait(terminal, "exact turn interrupted", 5)
        (work / "release").touch()

        def dead(pid):
            return process_state(pid) in ("absent", "Z")

        wait(lambda: all(dead(p) for p in pids), "both owned tools terminated", 5)
        assert not any((work / ("late" + str(n))).exists() for n in range(2)), (
            "tool_continued_after_stop"
        )
        assert report["calls"] == 1, "new provider call after Stop"
        report["state"] = "passed"
        report["both_tools_dead"] = True
        report["no_post_stop_tool_marker"] = True
    except Exception as error:
        report["state"] = "failed"
        report["error"] = str(error)
    finally:
        (work / "release").touch()
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
        server.shutdown()
        server.server_close()
        log.close()
        report["native_reaped"] = proc.poll() is not None
        report["elapsed_seconds"] = round(
            time.monotonic() - report.pop("started_monotonic"), 3
        )
        report["post_cleanup_tool_states"] = {
            str(pid): process_state(pid) for pid in report.get("tool_pids", [])
        }
        if any(
            state not in ("absent", "Z")
            for state in report["post_cleanup_tool_states"].values()
        ):
            report["state"] = "failed"
            report["error"] = "owned_tool_cleanup_unconfirmed"
        (base / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    return 0 if report["state"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
