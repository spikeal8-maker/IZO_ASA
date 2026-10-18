"""An isolated Linux subreaper for the D3 browser, including detached Chromium children."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


CHILD_BYTES = 65536


class ProcessFailure(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def children():
    """Only children owned by this isolated supervisor; never search by process name."""
    with Path(f"/proc/self/task/{os.getpid()}/children").open("rb") as source:
        raw = source.read(CHILD_BYTES + 1)
    truncated = len(raw) > CHILD_BYTES
    if truncated:
        raw = raw[:CHILD_BYTES]
        # A partial decimal PID must never become a different signal target.
        boundary = raw.rfind(b" ")
        if boundary < 0:
            raise ProcessFailure("D3_PROCESS_CHILD_DATA_INVALID")
        raw = raw[:boundary + 1]
    tokens = raw.split()
    if any(not token.isdigit() or len(token) > 10 for token in tokens):
        raise ProcessFailure("D3_PROCESS_CHILD_DATA_INVALID")
    result = [int(value) for value in tokens]
    if len(set(result)) != len(result) or any(pid <= 1 or pid > 2147483647 or pid == os.getpid() for pid in result):
        raise ProcessFailure("D3_PROCESS_CHILD_DATA_INVALID")
    return result, len(result) > 256 or truncated, truncated


def private_scope():
    if sys.platform != "linux":
        raise ProcessFailure("D3_PROCESS_SCOPE_INVALID")
    try:
        with os.scandir("/proc/self/task") as entries:
            tids = [entry.name for _, entry in zip(range(2), entries)]
        pending, overflow, truncated = children()
    except (OSError, ValueError, ProcessFailure):
        raise ProcessFailure("D3_PROCESS_PROC_UNAVAILABLE") from None
    if tids != [str(os.getpid())] or pending or overflow or truncated:
        raise ProcessFailure("D3_PROCESS_SCOPE_INVALID")


def reap(process, known, signalled, deadline):
    count = 0
    while time.monotonic() < deadline:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            known.clear()
            signalled.clear()
            break
        if pid == 0:
            break
        if process is not None and pid == process.pid:
            process.returncode = os.waitstatus_to_exitcode(status)
        known.discard(pid)
        signalled.pop(pid, None)  # A newly adopted child may later reuse this number.
        count += 1
    return count


def drain(process):
    """Node may create detached sessions. Subreaper adoption still keeps them owned."""
    started = time.monotonic()
    deadline = started + 5
    report = {"status": "FAIL", "childrenAtShutdown": None, "termSignals": 0,
              "killSignals": 0, "reaped": 0, "remainingChildren": None,
              "rawChildrenBeforeReap": None, "reapedBeforeSignal": 0,
              "remainingUnknown": False, "overflow": False, "errors": []}
    known, signalled = set(), {}
    first = True
    def error(code):
        if code not in report["errors"]:
            report["errors"].append(code)
    while time.monotonic() < deadline:
        failed_read = False
        try:
            pending, overflow, truncated = children()
            known.update(pending)
            report["overflow"] |= overflow
            report["remainingUnknown"] |= truncated
            if first:
                report["rawChildrenBeforeReap"] = len(pending)
                try:
                    report["reapedBeforeSignal"] = reap(process, known, signalled, deadline)
                    report["reaped"] += report["reapedBeforeSignal"]
                except Exception:
                    error("D3_PROCESS_CHILD_REAP_FAILED")
                pending, overflow, truncated = children()
                known.update(pending)
                report["overflow"] |= overflow
                report["remainingUnknown"] |= truncated
                report["childrenAtShutdown"] = len(known)
            report["remainingChildren"] = len(pending)
            if not pending and not known:
                break
        except Exception:
            failed_read = report["remainingUnknown"] = True
            report["remainingChildren"] = None
            error("D3_PROCESS_CHILD_READ_FAILED")
            if process is not None and process.returncode is None:
                known.add(process.pid)  # Popen still owns this unreaped child.
        first = False
        chosen = signal.SIGKILL if failed_read or time.monotonic() >= started + 2 else signal.SIGTERM
        for pid in tuple(known):
            if time.monotonic() >= deadline:
                break
            if chosen in signalled.get(pid, ()):
                continue
            # SIGCHLD is default and this private supervisor has the only waiter.
            try:
                os.kill(pid, chosen)
                report["termSignals" if chosen == signal.SIGTERM else "killSignals"] += 1
                signalled.setdefault(pid, set()).add(chosen)
            except ProcessLookupError:
                pass
            except Exception:
                error("D3_PROCESS_CHILD_SIGNAL_FAILED")
        try:
            report["reaped"] += reap(process, known, signalled, deadline)
        except Exception:
            error("D3_PROCESS_CHILD_REAP_FAILED")
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(.02, remaining))
    if (report["remainingChildren"] == 0 and not known and not report["remainingUnknown"]
            and not report["overflow"] and not report["errors"]):
        report["status"] = "PASS"
    return report


def empty_report():
    return {"status": "FAIL", "timedOut": False, "nodeReturncode": None,
            "scope": "PRIVATE_LINUX_SUBREAPER", "cleanup": {"status": "NOT_RUN"}}


def interrupted(_signal, _frame):
    raise ProcessFailure("D3_BROWSER_PROCESS_INTERRUPTED")


def work_timeout(_signal, _frame):
    raise ProcessFailure("D3_BROWSER_PROCESS_TIMEOUT")


def supervise(command, payload, *, cwd, timeout=140):
    """Call only inside a new dedicated Python process, before it has other children."""
    report, process, admitted, handlers = empty_report(), None, False, {}
    started = time.monotonic()
    try:
        if not isinstance(payload, bytes) or len(payload) > 16384:
            raise ProcessFailure("D3_PROCESS_SCOPE_INVALID")
        if type(timeout) not in (int, float) or not 0 < timeout <= 140:
            raise ProcessFailure("D3_PROCESS_DEADLINE_INVALID")
        private_scope()
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            prepared = libc.prctl(36, 1, 0, 0, 0) == 0
        except Exception:
            prepared = False
        if not prepared:
            raise ProcessFailure("D3_PROCESS_SUBREAPER_UNAVAILABLE")
        admitted = True
        for name, handler in ((signal.SIGCHLD, signal.SIG_DFL), (signal.SIGTERM, interrupted),
                              (signal.SIGINT, interrupted), (signal.SIGALRM, work_timeout)):
            handlers[name] = signal.signal(name, handler)
        deadline = started + timeout
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProcessFailure("D3_BROWSER_PROCESS_TIMEOUT")
        signal.setitimer(signal.ITIMER_REAL, remaining)
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, cwd=cwd, start_new_session=True)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProcessFailure("D3_BROWSER_PROCESS_TIMEOUT")
        process.communicate(payload, timeout=remaining)
    except subprocess.TimeoutExpired:
        report["timedOut"] = True
        report["errorCode"] = "D3_BROWSER_PROCESS_TIMEOUT"
    except ProcessFailure as error:
        report["errorCode"] = error.code
        report["timedOut"] = error.code == "D3_BROWSER_PROCESS_TIMEOUT"
    except BaseException:
        report["errorCode"] = "D3_BROWSER_PROCESS_FAILED"
    finally:
        payload = b""
        if admitted:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0)
            except BaseException:
                report["errorCode"] = "D3_PROCESS_SIGNAL_CLEANUP_FAILED"
            for name in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM):
                try:
                    signal.signal(name, signal.SIG_IGN)
                except BaseException:
                    report["errorCode"] = "D3_PROCESS_SIGNAL_CLEANUP_FAILED"
            try:
                report["cleanup"] = drain(process)
            except BaseException:
                report["cleanup"] = {"status": "FAIL", "remainingUnknown": True,
                                     "errorCode": "D3_PROCESS_CLEANUP_FAILED"}
            try:
                if process is not None and process.stdin and not process.stdin.closed:
                    process.stdin.close()
            except BaseException:
                report["errorCode"] = "D3_PROCESS_STDIN_CLOSE_FAILED"
            for name, handler in handlers.items():
                try:
                    signal.signal(name, handler)
                except BaseException:
                    report["errorCode"] = "D3_PROCESS_SIGNAL_RESTORE_FAILED"
        report["nodeReturncode"] = process.returncode if process is not None else None
        report["seconds"] = round(time.monotonic() - started, 3)
    if (report["nodeReturncode"] == 0 and not report["timedOut"] and "errorCode" not in report
            and report["cleanup"]["status"] == "PASS" and report["cleanup"]["childrenAtShutdown"] == 0):
        report["status"] = "PASS"
    elif "errorCode" not in report:
        report["errorCode"] = "D3_BROWSER_PROCESS_OR_CHILD_CLEANUP_FAILED"
    return report


def main():
    report, directory = empty_report(), None
    try:
        if len(sys.argv) != 3:
            raise ProcessFailure("D3_PROCESS_ARGUMENTS_INVALID")
        directory = Path(sys.argv[2]).resolve()
        if not directory.is_dir():
            directory = None
            raise ProcessFailure("D3_PROCESS_TARGET_INVALID")
        script = Path(sys.argv[1]).resolve()
        if script != Path(__file__).resolve().with_name("docker_d3_chat_video.mjs") or not script.is_file():
            raise ProcessFailure("D3_PROCESS_TARGET_INVALID")
        payload = sys.stdin.buffer.read(16385)
        report = supervise(["node", str(script)], payload, cwd=script.parents[1])
    except ProcessFailure as error:
        report["errorCode"] = error.code
    except BaseException:
        report["errorCode"] = "D3_PROCESS_INPUT_FAILED"
    if directory is not None:
        try:
            descriptor = os.open(directory / "browser-process.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(report, output, indent=2)
                output.write("\n")
        except Exception:
            report.update(status="FAIL", errorCode="D3_PROCESS_RECEIPT_FAILED")
    print(json.dumps(report))  # Fixed fields only; still available if writing the private receipt fails.
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
