"""Mandatory isolated Linux secret-store verification in the exact built backend image."""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import uuid
from pathlib import Path

try:
    from tools.docker_test_bundle_format import IMAGE, SHA, plain_path, require
except ModuleNotFoundError:
    from docker_test_bundle_format import IMAGE, SHA, plain_path, require


TESTS = ("test_linux_secret_store.py", "test_linux_secret_backup.py")
CLIS = ("backup_secret_store.py", "restore_secret_store.py")
MODULES = ("app/security/secret_store.py", "app/security/secret_store_files.py",
           "app/security/linux_secret_store.py", "app/security/linux_secret_backup.py")
OPERATION = "backend-posix-secret-probe-v1"
RUNNER = r'''
import contextlib,hashlib,importlib,importlib.metadata,io,json,os,platform,subprocess,sys,tempfile
from pathlib import Path

def main():
    config=json.loads(Path('/verification/config.json').read_text())
    if sys.platform!='linux' or os.getuid()!=10001 or os.getgid()!=10001:
        raise RuntimeError('POSIX probe process identity mismatch.')
    sys.path.insert(0,'/opt/izo/backend')
    for relative,pin in config['modules'].items():
        source=Path('/opt/izo/backend')/relative
        if hashlib.sha256(source.read_bytes()).hexdigest()!=pin:
            raise RuntimeError('POSIX probe installed module mismatch.')
        module=importlib.import_module(relative[:-3].replace('/','.'))
        if Path(module.__file__).resolve()!=source:
            raise RuntimeError('POSIX probe import origin mismatch.')
    for name,pin in {**config['tests'],**config['cli']}.items():
        if hashlib.sha256((Path('/verification')/name).read_bytes()).hexdigest()!=pin:
            raise RuntimeError('POSIX probe test mismatch.')
    for name,version in config['dependencies'].items():
        if importlib.metadata.version(name)!=version:
            raise RuntimeError('POSIX probe dependency mismatch.')
    import pytest
    class Counts:
        def __init__(self):
            self.collected=0; self.passed=0; self.failed=0; self.skipped=0; self.errors=0; self.warnings=0
            self.failed_nodes=[]
        def pytest_collection_finish(self,session):
            self.collected=len(session.items)
        def pytest_collectreport(self,report):
            if report.failed:self.errors+=1
            if report.skipped:self.skipped+=1
        def pytest_runtest_logreport(self,report):
            if report.skipped:self.skipped+=1
            if report.failed:
                self.failed+=1; self.failed_nodes.append(report.nodeid)
            if report.when=='call' and report.passed:self.passed+=1
        def pytest_warning_recorded(self,warning_message,when,nodeid,location):
            self.warnings+=1
    counts=Counts()
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        code=pytest.main(['--noconftest','-c','/dev/null','--rootdir=/verification','-p','no:cacheprovider',
            '--basetemp=/tmp/posix-tests','-W','error','-q',*[str(Path('/verification')/n) for n in config['tests']]],
            plugins=[counts])
    result={**vars(counts),'exit_code':int(code),'python':platform.python_version(),
            'dependencies':config['dependencies'],'modules':config['modules'],'tests':config['tests'],'cli':config['cli']}
    result['status']='PASS' if code==0 and counts.collected>0 and counts.passed==counts.collected and not (
        counts.failed or counts.skipped or counts.errors or counts.warnings) else 'FAILED'
    for name in config['cli']:
        help_result=subprocess.run([sys.executable,'-I','-B','/verification/'+name,'--help'],
            capture_output=True,timeout=20,check=False)
        if help_result.returncode!=0:
            raise RuntimeError('Packaged secret CLI help failed.')
    from app.security.linux_secret_store import LinuxSecretStore
    from app.security.linux_secret_backup import _snapshot
    with tempfile.TemporaryDirectory(prefix='cli-restore-',dir='/tmp') as temporary:
        source=LinuxSecretStore(Path(temporary)/'source')
        source.set('fixture_name','synthetic-restore-proof')
        payload,_=_snapshot(source.root)
        target=Path(temporary)/'restored'
        restored=subprocess.run([sys.executable,'-I','-B','/verification/restore_secret_store.py',
            '--backend-root','/opt/izo/backend','--secret-dir',str(target)],
            input=payload,capture_output=True,timeout=30,check=False)
        if restored.returncode!=0 or json.loads(restored.stdout).get('status')!='LOCAL_SECRET_RESTORE_VERIFIED':
            raise RuntimeError('Packaged secret restore CLI failed.')
        if LinuxSecretStore(target).get('fixture_name')!='synthetic-restore-proof':
            raise RuntimeError('Packaged secret restore CLI readback failed.')
    result['cli_restore_verified']=True
    result['cli_help_verified']=True
    print(json.dumps(result,sort_keys=True))
    raise SystemExit(0 if result['status']=='PASS' else 1)

if __name__ == "__main__":
    main()
'''


def candidate_material(source: Path) -> tuple[dict, dict[str, bytes]]:
    source = plain_path(source)
    tests = {name: plain_path(source / "backend" / name).read_bytes() for name in TESTS}
    modules = {name: hashlib.sha256(plain_path(source / "backend" / name).read_bytes()).hexdigest()
               for name in MODULES}
    requirements = plain_path(source / "backend/requirements.txt").read_text(encoding="utf-8")
    dependencies = {}
    for name in ("cryptography", "pytest"):
        versions = re.findall(r"^" + name + r"==([0-9]+(?:\.[0-9]+){2})$", requirements, re.MULTILINE)
        require(len(versions) == 1, "POSIX_PROBE_PINNED_DEPENDENCIES_REQUIRED")
        dependencies[name] = versions[0]
    scripts = {name: plain_path(source / "tools" / name).read_bytes() for name in CLIS}
    return {"modules": modules, "tests": {name: hashlib.sha256(raw).hexdigest() for name, raw in tests.items()},
            "cli": {name: hashlib.sha256(raw).hexdigest() for name, raw in scripts.items()},
            "dependencies": dependencies}, {**tests, **scripts}


def probe_backend_posix(source: Path, sha: str, image: str, docker) -> dict:
    require(SHA.fullmatch(sha or "") is not None and IMAGE.fullmatch(image or "") is not None,
            "POSIX_PROBE_EXACT_SOURCE_REQUIRED")
    config, tests = candidate_material(source)
    nonce = uuid.uuid4().hex
    labels = {"org.izo.operation": OPERATION, "org.izo.operation-id": nonce}
    with tempfile.TemporaryDirectory(prefix="izo-backend-posix-") as temporary:
        root = Path(temporary)
        # Host temp defaults are 0700; the test container's unprivileged UID needs read/traverse.
        root.chmod(0o755)
        for name, raw in {**tests, "runner.py": RUNNER.encode(),
                          "config.json": json.dumps(config, sort_keys=True).encode()}.items():
            path = root / name
            path.write_bytes(raw)
            path.chmod(0o644)
        args = ["create", "--name", "izo-backend-posix-" + nonce, "--network", "none", "--read-only",
                "--restart", "no", "--user", "10001:10001", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--pids-limit", "128", "--memory", "512m",
                "--cpus", "2", "--env", "PYTHONDONTWRITEBYTECODE=1",
                "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                "--mount", "type=bind,source=" + str(root) + ",target=/verification,readonly",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=256m,uid=0,gid=0,mode=1777"]
        for key, value in labels.items():
            args += ["--label", key + "=" + value]
        args += ["--entrypoint", "python", image, "-I", "-B", "/verification/runner.py"]
        identity = docker.run(*args)
        try:
            require(re.fullmatch(r"[0-9a-f]{64}", identity or "") is not None, "POSIX_PROBE_ID_INVALID")
            docker.run("start", identity)
            exit_code = docker.run("wait", identity, timeout=180)
            result = json.loads(docker.run("logs", identity))
            result.update(source_sha=sha, image=image, runner_sha256=hashlib.sha256(RUNNER.encode()).hexdigest())
        finally:
            state = json.loads(docker.run("inspect", identity))[0]
            require(all((state.get("Config", {}).get("Labels") or {}).get(k) == v
                        for k, v in labels.items()), "POSIX_PROBE_OWNERSHIP_MISMATCH")
            docker.run("rm", "--force", identity)
        result["owned_container_removed"] = True
    require(exit_code == "0" and result.get("status") == "PASS"
            and result.get("collected", 0) > 0 and result.get("passed") == result["collected"]
            and all(result.get(key) == 0 for key in ("failed", "skipped", "errors", "warnings", "exit_code"))
            and result.get("modules") == config["modules"] and result.get("tests") == config["tests"]
            and result.get("cli") == config["cli"] and result.get("cli_restore_verified") is True
            and result.get("cli_help_verified") is True
            and result.get("dependencies") == config["dependencies"],
            "BACKEND_POSIX_PROBE_FAILED " + json.dumps(result, sort_keys=True))
    return result
