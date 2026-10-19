"""Private adopted-child characterization and safe health receipts; no Docker proof."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import docker_clean_recovery as recovery
from tools import docker_shadow_roles as roles
from tools.docker_shadow import ShadowError
from tools.test_docker_clean_recovery import shadow as recovery_shadow, target
from tools.test_docker_shadow_lifecycle import fixture_shadow

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "ops/docker/dev/network_guard.py"
PRIVATE = "secret-cookie /private/path http://private.invalid/provider"

ADOPTED_CHILD = r'''
import contextlib,ctypes,importlib.util,io,json,os,select,signal,sys,time
from types import SimpleNamespace
from unittest.mock import Mock,patch
report={'status':'NOT_RUN','scope':'PRIVATE_CHILD_SUBREAPER','childrenStarted':0}
spec=importlib.util.spec_from_file_location('owned_guard',sys.argv[1])
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
if os.geteuid()==0:
 try: os.setgroups([]);os.setgid(10001);os.setuid(10001)
 except OSError:
  report['reason']='PRIVATE_CHILD_DROP_UNAVAILABLE';print(json.dumps(report));sys.exit(0)
report['uid']=os.getuid()
libc=ctypes.CDLL(None,use_errno=True)
if libc.prctl(36,1,0,0,0)!=0:
 print(json.dumps(report));sys.exit(0)
try:
 os.waitpid(-1,os.WNOHANG)
 print(json.dumps(report));sys.exit(0)
except ChildProcessError:
 pass
class EndLoop(Exception): pass
with contextlib.ExitStack() as stack:
 stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
 for name in ('nft','policy_state','READY'):
  stack.enter_context(patch.object(guard,name,Mock()))
 stack.enter_context(patch.object(guard,'Path',return_value=SimpleNamespace(read_text=lambda:'CapEff:\t0000000000000000')))
 for name in ('setgroups','setgid','setuid'):
  stack.enter_context(patch.object(guard.os,name,Mock()))
 stack.enter_context(patch.object(guard.os,'getuid',return_value=10001))
 stack.enter_context(patch.object(guard.time,'sleep',side_effect=EndLoop))
 try: guard.main()
 except EndLoop: pass
 if not guard.nft.called or not guard.policy_state.called or not guard.READY.write_text.called:
  raise RuntimeError('GUARD_STARTUP_NOT_EXECUTED')
report['mainInstalledIgnore']=signal.getsignal(signal.SIGCHLD)==signal.SIG_IGN
if sys.argv[2]=='control': signal.signal(signal.SIGCHLD,signal.SIG_DFL)
report.update(status='FAIL',adopted=0,autoReaped=0,waitable=0)
parent=os.getpid()
for iteration in range(3):
 read,write=os.pipe()
 bridge=os.fork()
 if bridge==0:
  try:
   os.close(read)
   if os.fork()!=0: os._exit(0)
   deadline=time.monotonic()+2
   while os.getppid()!=parent and time.monotonic()<deadline: time.sleep(.002)
   message=str(os.getpid()) if os.getppid()==parent else '0'
   os.write(write,message.encode('ascii'))
  finally: os._exit(23)
 report['childrenStarted']+=2
 os.close(write)
 try:
  if not select.select([read],[],[],3)[0]: raise RuntimeError('ADOPTION_DEADLINE')
  child=int(os.read(read,32))
 finally: os.close(read)
 try: os.waitpid(bridge,0)
 except ChildProcessError: pass
 if child<=1: raise RuntimeError('ADOPTION_NOT_OBSERVED')
 report['adopted']+=1
 deadline=time.monotonic()+2
 while time.monotonic()<deadline:
  try: waited,status=os.waitpid(child,os.WNOHANG)
  except ChildProcessError:
   report['autoReaped']+=1;break
  if waited==child:
   if os.waitstatus_to_exitcode(status)!=23: raise RuntimeError('CHILD_EXIT_MISMATCH')
   report['waitable']+=1;break
  time.sleep(.002)
 else: raise RuntimeError('REAP_DEADLINE')
try:
 os.waitpid(-1,os.WNOHANG)
 raise RuntimeError('OWNED_CHILDREN_REMAIN')
except ChildProcessError: report['remainingChildren']=0
expected='waitable' if sys.argv[2]=='control' else 'autoReaped'
if report[expected]==3: report['status']='PASS'
print(json.dumps(report))
'''


def health(output=PRIVATE, *, status="unhealthy"):
    return {"Status": status, "FailingStreak": 20 if status == "unhealthy" else 0, "Log": [{
        "Start": "2026-10-18T16:41:00.123456789Z", "End": "2026-10-18T16:41:02.123456789Z",
        "ExitCode": -1, "Output": output}]}


class GuardHealthTests(unittest.TestCase):
    def test_check_keeps_waitable_subprocess_semantics_and_all_readiness_checks(self):
        spec = importlib.util.spec_from_file_location("check_guard_only", GUARD)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        def read(path):
            value = "1" if str(path).endswith("disable_ipv6") else "Uid:\t10001\t10001\t10001\t10001\nCapEff:\t0000000000000000"
            return SimpleNamespace(read_text=lambda: value)
        with patch.object(guard, "policy_state", return_value={"policy": "VERIFIED", "blockedPackets": 1}) as policy, \
                patch.object(guard, "Path", side_effect=read), patch.object(guard, "READY") as ready, \
                patch.object(guard.signal, "signal") as changed:
            ready.read_text.return_value = guard.MARKER
            self.assertEqual(guard.check(), {"policy": "VERIFIED", "blockedPackets": 1})
            policy.assert_called_once_with()
            changed.assert_not_called()

    def test_only_last_five_bounded_classified_hashes_survive(self):
        samples = [PRIVATE, "RuntimeError: SHADOW_IPV6_ENABLED\n", "Health check exceeded timeout (2s): " + PRIVATE,
            "subprocess.TimeoutExpired: Command 'private' timed out after 5 seconds", "RuntimeError: SHADOW_KERNEL_POLICY_MISMATCH"]
        value = health()
        value["Log"] = [deepcopy(value["Log"][0]) for _ in range(7)]
        for row, output in zip(value["Log"][-5:], samples):
            row["Output"] = output
        result = roles.guard_health(value)
        self.assertEqual(len(result["lastChecks"]), 5)
        self.assertEqual([row["classification"] for row in result["lastChecks"]], ["UNCLASSIFIED",
            "SHADOW_IPV6_ENABLED", "DOCKER_HEALTH_TIMEOUT", "PROBE_SUBPROCESS_TIMEOUT", "SHADOW_KERNEL_POLICY_MISMATCH"])
        self.assertNotIn(PRIVATE, json.dumps(result))
        for row, output in zip(result["lastChecks"], samples):
            self.assertEqual(row["outputSha256"], hashlib.sha256(output.encode()).hexdigest())
            self.assertEqual(row["outputBytes"], len(output.encode()))
            self.assertEqual(set(row), {"start", "end", "exitCode", "outputBytes", "outputSha256", "classification"})

    def test_malformed_metadata_never_becomes_healthy_or_raw_error_output(self):
        malformed = [None, {"Status": []}, {**health(), "FailingStreak": False}, {**health(), "Log": None}]
        for key, value in (("ExitCode", True), ("Output", PRIVATE * 200), ("Start", PRIVATE),
                           ("End", "2026-99-18T16:41:02Z")):
            item = health(status="healthy")
            item["Log"][0][key] = value
            malformed.append(item)
        for value in malformed:
            recorded = []
            shadow = SimpleNamespace(_guard_health_recorder=recorded.append)
            with self.subTest(value=type(value).__name__), self.assertRaisesRegex(ShadowError, "HEALTH_METADATA_INVALID"):
                roles.observe_guard_health(shadow, value)
            self.assertEqual(recorded, [{"status": "INVALID", "errorCode": "SHADOW_GUARD_HEALTH_METADATA_INVALID"}])
            self.assertNotIn(PRIVATE, json.dumps(recorded))

    def test_unhealthy_snapshot_is_recorded_before_unchanged_mutation_refusal(self):
        shadow = fixture_shadow()
        observed = shadow.ownership_guard.side_effect
        before = next(observed)
        shadow.ownership_guard = Mock(return_value=before)
        guard = next(row for row in before if row["Config"]["Labels"]["com.docker.compose.service"] == "guard")
        guard["State"]["Health"] = health("RuntimeError: SHADOW_IPV6_ENABLED")
        recorded = []
        shadow._guard_health_recorder = recorded.append
        with self.assertRaisesRegex(ShadowError, "SHADOW_RETAINED_GUARD_HEALTH_INVALID"):
            shadow.up(build=False, recreate=True, application_only=True)
        shadow.compose.assert_not_called()
        self.assertEqual(recorded[0]["status"], "unhealthy")
        self.assertEqual(recorded[0]["lastChecks"][0]["classification"], "SHADOW_IPV6_ENABLED")

    def test_new_health_log_timestamps_do_not_change_retained_process_identity(self):
        from tools.test_docker_shadow_lifecycle import stack
        before, after = stack(), stack()
        for index, rows in enumerate((before, after)):
            guard = next(row for row in rows if row["Config"]["Labels"]["com.docker.compose.service"] == "guard")
            guard["State"]["Health"] = health('{"policy":"VERIFIED","blockedPackets":0}', status="healthy")
            guard["State"]["Health"]["Log"][0].update(ExitCode=0, End=f"2026-10-18T16:41:0{index + 2}Z")
        shadow, recorded = fixture_shadow(before, after), []
        shadow._guard_health_recorder = recorded.append
        result = shadow.up(build=False, recreate=True, application_only=True)
        self.assertEqual(result["before"], result["after"])
        self.assertEqual(len(recorded), 2)
        self.assertNotEqual(recorded[0], recorded[1])
        self.assertTrue(all(row["lastChecks"][0]["classification"] == "POLICY_VERIFIED" for row in recorded))

    def test_recovery_saves_rejection_evidence_immediately_and_restores_recorder(self):
        shadow, previous = recovery_shadow(), Mock()
        shadow._guard_health_recorder = previous
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            def rejected(run):
                roles.observe_guard_health(run.shadow, health())
                saved = json.loads(receipt.read_text())
                self.assertEqual(saved["guardHealth"][0]["status"], "unhealthy")
                raise ShadowError("SHADOW_RETAINED_GUARD_HEALTH_INVALID")
            with patch.object(recovery.RecoveryRun, "preflight", autospec=True, side_effect=rejected), \
                    patch.object(recovery, "ProductFlow") as flow:
                report = recovery.prove_recovery(shadow, target(), receipt)
            flow.assert_not_called()
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["errorCode"], "SHADOW_RETAINED_GUARD_HEALTH_INVALID")
            self.assertNotIn(PRIVATE, receipt.read_text())
        self.assertIs(shadow._guard_health_recorder, previous)
        previous.assert_not_called()


@unittest.skipUnless(sys.platform == "linux", "Actual adoption proof requires the Linux child-subreaper API")
class GuardChildLifecycleTests(unittest.TestCase):
    def characterize(self, mode):
        result = subprocess.run([sys.executable, "-c", ADOPTED_CHILD, str(GUARD), mode],
                                capture_output=True, text=True, timeout=12, check=False)
        self.assertEqual(result.returncode, 0, "PRIVATE_REAPER_CHARACTERIZATION_FAILED")
        self.assertFalse(result.stderr, "PRIVATE_REAPER_STDERR_MUST_BE_EMPTY")
        self.assertLess(len(result.stdout), 4096)
        value = json.loads(result.stdout)
        self.last_characterization = value
        self.assertEqual(value["status"], "PASS", "UNAVAILABLE_PRCTL_IS_NOT_RUNTIME_PASS")
        self.assertEqual(value["adopted"], 3)
        self.assertEqual(value["childrenStarted"], 6)
        self.assertEqual(value["remainingChildren"], 0)
        self.assertNotEqual(value["uid"], 0)
        return value

    def test_control_observes_waitable_adopted_children_without_ignore(self):
        value = self.characterize("control")
        self.assertEqual(value["waitable"], 3)
        self.assertEqual(value["autoReaped"], 0)

    def test_guard_main_reaps_actual_adopted_children_without_waiting(self):
        value = self.characterize("guard")
        self.assertTrue(value["mainInstalledIgnore"])
        self.assertEqual(value["autoReaped"], 3)
        self.assertEqual(value["waitable"], 0)


if __name__ == "__main__":
    unittest.main()
