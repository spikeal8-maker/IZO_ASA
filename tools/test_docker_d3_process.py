"""Real private detached children verify the Linux D3 supervisor's failure cleanup."""
import importlib.util
from contextlib import contextmanager, ExitStack, nullcontext
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).with_name("docker_d3_process.py")


class SupervisorTests(unittest.TestCase):
    def execute(self, code, timeout=3):
        runner = ("import importlib.util,json,sys; "
            "s=importlib.util.spec_from_file_location('owned',sys.argv[1]); "
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m); "
            "r=m.supervise([sys.executable,'-c',sys.argv[2]],b'private-stdin-canary',cwd=sys.argv[3],timeout=float(sys.argv[4])); "
            "print(json.dumps(r))")
        with tempfile.TemporaryDirectory(prefix="izo-owned-browser-test-") as directory:
            result = subprocess.run([sys.executable, "-c", runner, str(SOURCE), code, directory, str(timeout)],
                capture_output=True, text=True, timeout=10, check=True)
            self.assertNotIn("private-stdin-canary", result.stdout + result.stderr)
            value = json.loads(result.stdout)
            pid_file = Path(directory) / "descendant.pid"
            if pid_file.exists():
                pid = int(pid_file.read_text())
                self.assertFalse(Path(f"/proc/{pid}").exists(), "owned detached descendant survived")
            return value

    @unittest.skipUnless(sys.platform == "linux", "D3 installed browser executor requires Linux")
    def test_normal_child_exit_requires_no_cleanup_or_residual_children(self):
        result = self.execute("import sys;assert sys.stdin.buffer.read()==b'private-stdin-canary'")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(result["cleanup"]["childrenAtShutdown"], 0)
        self.assertEqual(result["cleanup"]["killSignals"], 0)

    @unittest.skipUnless(sys.platform == "linux", "D3 installed browser executor requires Linux")
    def test_detached_grandchild_is_reaped_and_never_counts_as_clean_success(self):
        code = ("import os,subprocess,sys,time; "
            "p=subprocess.Popen([sys.executable,'-c',\"import os,time;open('descendant.pid','w').write(str(os.getpid()));time.sleep(60)\"],start_new_session=True); "
            "time.sleep(.2)")
        result = self.execute(code)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["nodeReturncode"], 0)
        self.assertGreater(result["cleanup"]["childrenAtShutdown"], 0)
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(result["cleanup"]["remainingChildren"], 0)

    @unittest.skipUnless(sys.platform == "linux", "D3 installed browser executor requires Linux")
    def test_timeout_kills_term_ignoring_detached_child_in_its_private_scope(self):
        code = ("import subprocess,sys,time; "
            "p=subprocess.Popen([sys.executable,'-c',\"import os,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);open('descendant.pid','w').write(str(os.getpid()));time.sleep(60)\"],start_new_session=True); "
            "time.sleep(60)")
        result = self.execute(code, timeout=.4)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["timedOut"])
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertGreaterEqual(result["cleanup"]["killSignals"], 1)
        self.assertEqual(result["cleanup"]["remainingChildren"], 0)
        self.assertLess(result["seconds"], 6)

    def test_nonlinux_scope_is_rejected_before_a_child_can_launch(self):
        spec = importlib.util.spec_from_file_location("d3_private_supervisor", SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module.sys, "platform", "win32"), patch.object(module.subprocess, "Popen") as launch:
            result = module.supervise(["forbidden"], b"", cwd=Path.cwd())
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["errorCode"], "D3_PROCESS_SCOPE_INVALID")
            self.assertEqual(result["cleanup"], {"status": "NOT_RUN"})
            launch.assert_not_called()


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeSupervisorTests(unittest.TestCase):
    """No child launches or OS signals; the three real Linux cases above remain required."""
    def setUp(self):
        spec = importlib.util.spec_from_file_location("d3_fake_supervisor", SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.clock = Clock()
        self.process = SimpleNamespace(pid=101, returncode=0, stdin=SimpleNamespace(closed=True), communicate=Mock())
        self.signal = SimpleNamespace(SIGCHLD=17, SIGTERM=15, SIGINT=2, SIGALRM=14, SIGKILL=9,
            SIG_DFL=0, SIG_IGN=1, ITIMER_REAL=0, signal=Mock(return_value=0), setitimer=Mock())

    @contextmanager
    def environment(self, *, real_scope=False):
        module = self.module
        with ExitStack() as stack:
            stack.enter_context(patch.object(module, "time", self.clock))
            stack.enter_context(patch.object(module, "signal", self.signal))
            stack.enter_context(patch.object(module.sys, "platform", "linux"))
            launch = stack.enter_context(patch.object(module.subprocess, "Popen", return_value=self.process))
            libc = SimpleNamespace(prctl=Mock(return_value=0))
            stack.enter_context(patch.object(module.ctypes, "CDLL", return_value=libc))
            kill = stack.enter_context(patch.object(module.os, "kill"))
            wait = stack.enter_context(patch.object(module.os, "waitpid", return_value=(0, 0)))
            stack.enter_context(patch.object(module.os, "WNOHANG", 1, create=True))
            stack.enter_context(patch.object(module.os, "waitstatus_to_exitcode",
                side_effect=lambda status: -(status & 127) if status & 127 else status >> 8))
            read = stack.enter_context(patch.object(module, "children", return_value=([], False, False)))
            if not real_scope:
                stack.enter_context(patch.object(module, "private_scope"))
            yield SimpleNamespace(launch=launch, libc=libc, kill=kill, wait=wait, read=read)

    def run_supervisor(self, timeout=140):
        return self.module.supervise(["owned-node"], b"private-stdin-canary", cwd=Path.cwd(), timeout=timeout)

    def assert_safe_failure(self, value):
        self.assertEqual(value["status"], "FAIL")
        encoded = json.dumps(value)
        self.assertNotIn("private-stdin-canary", encoded)
        self.assertNotIn("owned-private-path", encoded)

    def test_missing_proc_returns_a_safe_failure_without_launch_or_cleanup(self):
        with self.environment(real_scope=True) as env, patch.object(self.module.os, "scandir",
                side_effect=FileNotFoundError("owned-private-path")):
            result = self.run_supervisor()
            self.assert_safe_failure(result)
            self.assertEqual(result["errorCode"], "D3_PROCESS_PROC_UNAVAILABLE")
            self.assertEqual(result["cleanup"], {"status": "NOT_RUN"})
            env.launch.assert_not_called()
            env.libc.prctl.assert_not_called()
            env.kill.assert_not_called()
            env.wait.assert_not_called()

    def test_existing_children_or_second_thread_never_admit_cleanup(self):
        pid = str(os.getpid())
        for tids, children in (([pid], [202]), ([pid, "303"], [])):
            with self.subTest(tids=tids, children=children), self.environment(real_scope=True) as env:
                env.read.return_value = (children, False, False)
                with patch.object(self.module.os, "scandir", return_value=nullcontext(iter(
                        SimpleNamespace(name=name) for name in tids))):
                    result = self.run_supervisor()
                self.assertEqual(result["errorCode"], "D3_PROCESS_SCOPE_INVALID")
                self.assertEqual(result["cleanup"]["status"], "NOT_RUN")
                env.launch.assert_not_called()
                env.libc.prctl.assert_not_called()
                env.kill.assert_not_called()
                env.wait.assert_not_called()

    def test_prctl_unavailable_is_reported_before_launch(self):
        for raises in (False, True):
            with self.subTest(raises=raises), self.environment() as env:
                env.libc.prctl.return_value = -1
                if raises:
                    env.libc.prctl.side_effect = OSError("owned-private-path")
                result = self.run_supervisor()
                self.assert_safe_failure(result)
                self.assertEqual(result["errorCode"], "D3_PROCESS_SUBREAPER_UNAVAILABLE")
                self.assertEqual(result["cleanup"]["status"], "NOT_RUN")
                env.libc.prctl.assert_called_once_with(36, 1, 0, 0, 0)
                env.launch.assert_not_called()
                env.kill.assert_not_called()

    def test_late_proc_failure_kills_only_unreaped_popen_and_preserves_unknown_failure(self):
        self.process.returncode = None
        self.process.communicate.side_effect = subprocess.TimeoutExpired("owned", 140)
        with self.environment() as env:
            env.read.side_effect = OSError("owned-private-path")
            env.wait.side_effect = [(101, 9), (0, 0)] + [(0, 0)] * 300
            result = self.run_supervisor()
            self.assert_safe_failure(result)
            self.assertTrue(result["timedOut"])
            self.assertEqual(result["nodeReturncode"], -9)
            self.assertTrue(result["cleanup"]["remainingUnknown"])
            self.assertEqual(result["cleanup"]["status"], "FAIL")
            env.kill.assert_called_once_with(101, self.signal.SIGKILL)
            self.assertLessEqual(result["seconds"], 5)

    def test_late_proc_failure_never_signals_an_already_reaped_node_pid(self):
        with self.environment() as env:
            env.read.side_effect = OSError("owned-private-path")
            result = self.run_supervisor()
            self.assert_safe_failure(result)
            self.assertTrue(result["cleanup"]["remainingUnknown"])
            env.kill.assert_not_called()

    def test_overflow_still_drains_every_observed_child_and_remains_fail(self):
        owned, dead = set(range(10000, 10257)), []
        with self.environment() as env:
            env.read.side_effect = lambda: (sorted(owned), len(owned) > 256, False)
            env.kill.side_effect = lambda pid, _sig: dead.append(pid)
            def wait(_pid, _options):
                if dead:
                    pid = dead.pop()
                    owned.remove(pid)
                    return pid, 15
                return 0, 0
            env.wait.side_effect = wait
            result = self.run_supervisor()
            self.assert_safe_failure(result)
            self.assertTrue(result["cleanup"]["overflow"])
            self.assertEqual(result["cleanup"]["reaped"], 257)
            self.assertEqual(result["cleanup"]["remainingChildren"], 0)
            self.assertEqual({call.args[0] for call in env.kill.call_args_list}, set(range(10000, 10257)))

    def test_reaped_pid_reused_by_a_new_owned_child_is_signalled_again(self):
        state, signals = {"generation": 1, "dead": False}, []
        with self.environment() as env:
            env.read.side_effect = lambda: ([202] if state["generation"] <= 2 else [], False, False)
            def kill(pid, sig):
                signals.append((state["generation"], pid, sig))
                state["dead"] = True
            def wait(_pid, _options):
                if state["dead"]:
                    state.update(generation=state["generation"] + 1, dead=False)
                    return 202, 15
                return 0, 0
            env.kill.side_effect, env.wait.side_effect = kill, wait
            result = self.run_supervisor()
            self.assertEqual(signals, [(1, 202, self.signal.SIGTERM), (2, 202, self.signal.SIGTERM)])
            self.assertEqual(result["cleanup"]["status"], "PASS")
            self.assertEqual(result["cleanup"]["reaped"], 2)

    def test_empty_snapshot_cannot_pass_while_an_observed_child_remains_unreaped(self):
        with self.environment() as env:
            calls = {"count": 0}
            def read():
                calls["count"] += 1
                return ([202] if calls["count"] == 1 else [], False, False)
            env.read.side_effect = read
            result = self.run_supervisor()
            self.assert_safe_failure(result)
            self.assertEqual(result["cleanup"]["status"], "FAIL")
            self.assertEqual(result["cleanup"]["reaped"], 0)
            self.assertEqual(result["cleanup"]["remainingChildren"], 0)
            env.kill.assert_any_call(202, self.signal.SIGKILL)
            self.assertLessEqual(result["seconds"], 5)

    def test_signal_failure_does_not_prevent_another_owned_child_from_being_reaped(self):
        owned, dead = {202, 303}, []
        with self.environment() as env:
            env.read.side_effect = lambda: (sorted(owned), False, False)
            def kill(pid, _sig):
                if pid == 202:
                    raise PermissionError("owned-private-path")
                dead.append(pid)
            def wait(_pid, _options):
                if dead:
                    pid = dead.pop()
                    owned.remove(pid)
                    return pid, 15
                return 0, 0
            env.kill.side_effect, env.wait.side_effect = kill, wait
            result = self.run_supervisor()
            self.assert_safe_failure(result)
            self.assertEqual(owned, {202})
            self.assertEqual(result["cleanup"]["reaped"], 1)
            self.assertEqual(result["cleanup"]["errors"], ["D3_PROCESS_CHILD_SIGNAL_FAILED"])

    def test_work_budget_includes_popen_overhead_and_arms_private_deadline(self):
        with self.environment() as env:
            def launch(*_args, **_kwargs):
                self.clock.now += 11
                return self.process
            env.launch.side_effect = launch
            result = self.run_supervisor()
            self.assertEqual(result["status"], "PASS")
            self.process.communicate.assert_called_once_with(b"private-stdin-canary", timeout=129)
            self.signal.setitimer.assert_any_call(self.signal.ITIMER_REAL, 140)
            self.signal.setitimer.assert_called_with(self.signal.ITIMER_REAL, 0)
            self.signal.signal.assert_any_call(self.signal.SIGCHLD, self.signal.SIG_DFL)

    def test_expired_spawn_budget_never_starts_an_additional_communicate_window(self):
        with self.environment() as env:
            def launch(*_args, **_kwargs):
                self.clock.now += 140
                return self.process
            env.launch.side_effect = launch
            result = self.run_supervisor()
            self.assertTrue(result["timedOut"])
            self.assertEqual(result["errorCode"], "D3_BROWSER_PROCESS_TIMEOUT")
            self.process.communicate.assert_not_called()
            self.assertLessEqual(result["seconds"], 145)

    def test_alarm_inside_popen_still_drains_children_adopted_by_the_admitted_scope(self):
        owned, dead = {202}, []
        with self.environment() as env:
            def launch(*_args, **_kwargs):
                self.clock.now = 140
                self.module.work_timeout(self.signal.SIGALRM, None)
            def wait(_pid, _options):
                if dead:
                    pid = dead.pop()
                    owned.remove(pid)
                    return pid, 15
                return 0, 0
            env.launch.side_effect = launch
            env.read.side_effect = lambda: (sorted(owned), False, False)
            env.kill.side_effect = lambda pid, _sig: dead.append(pid)
            env.wait.side_effect = wait
            result = self.run_supervisor()
            self.assert_safe_failure(result)
            self.assertTrue(result["timedOut"])
            self.assertIsNone(result["nodeReturncode"])
            self.assertEqual(result["cleanup"]["status"], "PASS")
            self.assertEqual(result["cleanup"]["reaped"], 1)
            self.assertEqual(owned, set())
            self.process.communicate.assert_not_called()
            self.assertLessEqual(result["seconds"], 145)

    def test_drain_or_stdin_failure_still_returns_a_safe_receipt(self):
        for cause in ("drain", "stdin"):
            with self.subTest(cause=cause), self.environment():
                with ExitStack() as stack:
                    if cause == "drain":
                        stack.enter_context(patch.object(self.module, "drain", side_effect=OSError("owned-private-path")))
                    else:
                        self.process.stdin = SimpleNamespace(closed=False, close=Mock(side_effect=BrokenPipeError("owned-private-path")))
                    result = self.run_supervisor()
                self.assert_safe_failure(result)
                self.assertIn("cleanup", result)

    def test_proc_snapshot_never_turns_a_truncated_decimal_into_a_signal_pid(self):
        with patch.object(self.module, "CHILD_BYTES", 9), patch.object(Path, "open", return_value=io.BytesIO(b"202 30345 404 ")):
            pids, overflow, truncated = self.module.children()
        self.assertEqual(pids, [202])
        self.assertTrue(overflow)
        self.assertTrue(truncated)

    def test_cli_missing_proc_writes_an_exclusive_fixed_failure_receipt(self):
        with tempfile.TemporaryDirectory(prefix="izo-supervisor-cli-") as name:
            directory = Path(name)
            script = directory / "docker_d3_chat_video.mjs"
            script.write_text("// never executed\n")
            with patch.object(self.module, "__file__", str(directory / "docker_d3_process.py")), \
                    patch.object(self.module.sys, "argv", ["supervisor", str(script), str(directory)]), \
                    patch.object(self.module.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"private-stdin-canary"))), \
                    patch.object(self.module.sys, "stdout", io.StringIO()) as output, \
                    self.environment(real_scope=True) as env, \
                    patch.object(self.module.os, "scandir", side_effect=FileNotFoundError("owned-private-path")):
                code = self.module.main()
            self.assertEqual(code, 1)
            result = json.loads((directory / "browser-process.json").read_text())
            self.assertEqual(result["errorCode"], "D3_PROCESS_PROC_UNAVAILABLE")
            self.assert_safe_failure(result)
            self.assertEqual(json.loads(output.getvalue()), result)
            env.launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
