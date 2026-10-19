"""Measured two-container worker claims, lease fencing and isolated-role recovery."""
from __future__ import annotations

import json
import math
import re
import time
import uuid

from tools.docker_clean_recovery import ACTIVE, REFUNDS, accounting, require, same_accounts, wait_for
from tools.docker_clean_features import public_fields
from tools import docker_shadow_roles as roles

WORKER_READ = r'''
import json
from pathlib import Path
p=Path('/tmp/izo-generation-worker.json')
assert not p.is_symlink()
with p.open() as source:
 text=source.read(8193)
assert len(text)<=8192
data=json.loads(text)
keys=('version','role','workerId','pid','state','currentJobId','lastContactAt','lastSuccessAt',
 'lastFailureAt','httpRequests','httpResponses','httpFailures','completedJobs')
print(json.dumps({key:data[key] for key in keys}))
'''
CLAIM_READ = r'''
import json,sqlite3,sys,time
job,users=json.loads(sys.argv[1])
db=sqlite3.connect('file:/home/izo/data/app.sqlite3?mode=ro',uri=True,timeout=5)
db.execute('PRAGMA query_only=ON')
row=db.execute('SELECT settings_json FROM jobs WHERE id=? AND user_id IN ('+
 ','.join('?' for _ in users)+')',[job,*users]).fetchone()
db.close()
assert row is not None and len(row[0] or '{}')<=65536
claim=json.loads(row[0] or '{}').get('_workerClaim') or {}
keys=('version','workerId','issuedAt','renewedAt','leaseUntil','providerCommands','lastCommandAt','lossReason')
print(json.dumps({'jobId':job,'sampledAt':time.time(),'claim':{key:claim[key] for key in keys if key in claim}}))
'''
PROCESS_READ = r'''
import json
from pathlib import Path
status=Path('/proc/1/status').read_text()
cmd=Path('/proc/1/cmdline').read_bytes().split(b'\0')
print(json.dumps({'pid':1,'state':next(row for row in status.splitlines() if row.startswith('State:')).split()[1],
 'workerCommand':cmd[:3]==[b'python',b'-m',b'app.generation_worker']}))
'''


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def worker_status(value):
    expected = {'version', 'role', 'workerId', 'pid', 'state', 'currentJobId', 'lastContactAt',
                'lastSuccessAt', 'lastFailureAt', 'httpRequests', 'httpResponses', 'httpFailures', 'completedJobs'}
    require(isinstance(value, dict) and set(value) == expected and value['version'] == 1
            and value['role'] == 'worker' and re.fullmatch(r'[0-9a-f]{32}', str(value['workerId']))
            and type(value['pid']) is int and value['pid'] > 0
            and value['state'] in {'starting', 'idle', 'working', 'reconnecting', 'stopped'}
            and (value['currentJobId'] is None or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(value['currentJobId'])))
            and all(value[key] is None or finite(value[key]) for key in ('lastContactAt', 'lastSuccessAt', 'lastFailureAt'))
            and all(type(value[key]) is int and 0 <= value[key] <= 5000
                    for key in ('httpRequests', 'httpResponses', 'httpFailures', 'completedJobs')),
            'RECOVERY_WORKER_RECEIPT_INVALID')
    return value


class WorkerRun:
    def __init__(self, run):
        self.run, self.shadow = run, run.shadow

    def rows(self, *, source_guard=False):
        rows = self.run.guard() if source_guard else self.shadow.ownership_guard()
        require(len(rows) == 5 and {row['Config']['Labels'].get('com.docker.compose.service') for row in rows}
                == roles.services(self.shadow), 'RECOVERY_SPLIT_CONTAINERS_INVALID')
        result = {row['Config']['Labels']['com.docker.compose.service']: row for row in rows}
        require(len({row['Id'] for row in rows}) == 5
                and all(result[name]['Image'] == self.run.images[name] for name in result), 'RECOVERY_WORKER_IMAGE_CHANGED')
        for name in ('backend', *roles.WORKERS):
            row, labels = result[name], result[name]['Config']['Labels']
            require(re.fullmatch(r'[0-9a-f]{64}', row['Id']) and labels.get('io.izo.owner') == 'SHADOW-TOPOLOGY-01'
                    and labels.get('com.docker.compose.project') == self.shadow.project
                    and labels.get('com.docker.compose.oneoff', '').lower() == 'false', 'RECOVERY_WORKER_NOT_OWNED')
            host = row['HostConfig']
            require(host.get('NetworkMode') == 'container:' + result['guard']['Id'] and not host.get('PortBindings')
                    and not row['NetworkSettings'].get('Networks') and not host.get('Privileged')
                    and not host.get('CapAdd') and host.get('CapDrop') == ['ALL']
                    and 'no-new-privileges:true' in host.get('SecurityOpt', []), 'RECOVERY_WORKER_BOUNDARY_CHANGED')
            roles.runtime_guard(self.shadow, row, name)
        pids = [result[name]['State']['Pid'] for name in ('backend', *roles.WORKERS) if result[name]['State']['Running']]
        require(len(pids) == len(set(pids)) and all(type(pid) is int and pid > 0 for pid in pids),
                'RECOVERY_WORKER_PROCESSES_NOT_DISTINCT')
        return result

    def workers(self, *, running=True):
        result = {}
        for name, row in self.rows().items():
            if name not in roles.WORKERS:
                continue
            require(row['State']['Running'] is running, 'RECOVERY_WORKER_RUNNING_MISMATCH')
            value = {'containerId': row['Id'], 'imageId': row['Image'], 'hostPid': row['State']['Pid'],
                     'startedAt': row['State']['StartedAt']}
            if running:
                raw = self.shadow.docker('exec', row['Id'], 'python', '-c', WORKER_READ, timeout=15)
                require(isinstance(raw, str) and len(raw) <= 8192, 'RECOVERY_WORKER_RECEIPT_LIMIT')
                value['process'] = worker_status(json.loads(raw))
            result[name] = value
        if running:
            require(len({row['hostPid'] for row in result.values()}) == 2
                    and all(type(row['hostPid']) is int and row['hostPid'] > 0 for row in result.values())
                    and len({row['process']['workerId'] for row in result.values()}) == 2,
                    'RECOVERY_WORKER_PROCESSES_NOT_DISTINCT')
        return result

    def dispatcher(self):
        value = self.run.provider().get('generationDispatcher', {})
        require(value.get('role') == 'server' and value.get('localConsumer') is False
                and type(value.get('ready')) is bool
                and type(value.get('connectedWorkers')) is int and 0 <= value['connectedWorkers'] <= 1
                and type(value.get('onlineWorkers')) is int and 0 <= value['onlineWorkers'] <= 64
                and all(type(value.get(key)) is int and 0 <= value[key] <= 5000
                        for key in ('claimedJobs', 'completedJobs', 'expiredLeases')),
                'RECOVERY_SERVER_ROLE_NOT_PROVEN')
        return value

    def ready(self, count=2):
        def probe():
            value = self.dispatcher()
            return value if value['onlineWorkers'] == count and value['ready'] is (count > 0) else None
        return wait_for(probe, seconds=35, code='RECOVERY_WORKER_CONNECTION_TIMEOUT')

    def claim(self, job_id):
        value = self.run.inside(CLAIM_READ, json.dumps([job_id, self.run.user_ids]))
        claim = value.get('claim', {})
        require(value.get('jobId') == job_id and finite(value.get('sampledAt')) and claim.get('version') == 2
                and re.fullmatch(r'[0-9a-f]{32}', str(claim.get('workerId')))
                and all(finite(claim.get(key)) for key in ('issuedAt', 'renewedAt', 'leaseUntil'))
                and type(claim.get('providerCommands')) is int and claim['providerCommands'] > 0,
                'RECOVERY_DURABLE_WORKER_CLAIM_MISSING')
        return value

    def public(self, job_id, status):
        flow, path = self.run.flow, '/api/phone/v1/jobs'
        api = flow.owner.request('GET', '/api/jobs/' + job_id)
        detail = flow.owner.request('GET', path + '/' + job_id)
        listed = flow.owner.request('GET', path + '?active=false&limit=60')
        active = flow.owner.request('GET', path + '?active=true&limit=60')
        require(public_fields([api, detail, listed, active]) and detail.get('ok') is True
                and listed.get('ok') is True and active.get('ok') is True, 'RECOVERY_PHONE_PRIVATE_OR_INVALID')
        matching = [item for item in listed.get('items', []) if item.get('id') == job_id]
        expected = {'running', 'processing'} if status == 'active' else {status}
        require(len(matching) == 1 and detail['job'].get('id') == job_id
                and all(value.get('status') in expected for value in (detail['job'], matching[0]))
                and api.get('status') in (ACTIVE - {'queued'} if status == 'active' else expected)
                and (job_id in {item['id'] for item in active.get('items', [])}) is (status in {'active', 'queued'}),
                'RECOVERY_PHONE_DURABLE_STATE_MISMATCH')
        for client, code in ((flow.other, 404), (flow.guest, 401)):
            client.request('GET', path + '/' + job_id, expected=(code,))
        return {'apiStatus': api['status'], 'phoneListStatus': matching[0]['status'],
                'phoneDetailStatus': detail['job']['status'], 'otherUser': 404, 'guest': 401}

    def action(self, name, action, signal=None):
        require(name in {'backend', *roles.WORKERS} and action in {'start', 'stop', 'kill'}, 'RECOVERY_WORKER_ACTION_INVALID')
        require(signal in {'SIGKILL', 'SIGSTOP', 'SIGCONT'} if action == 'kill' else signal is None,
                'RECOVERY_WORKER_SIGNAL_INVALID')
        before = self.rows(source_guard=True)[name]
        args = ('kill', '--signal', signal, name) if signal else (action, name)
        self.shadow.compose(*args, timeout=45)
        after = self.rows()[name]
        require(after['Id'] == before['Id'] and after['Image'] == before['Image'], 'RECOVERY_WORKER_CONTAINER_REPLACED')
        return after

    def stable(self, job_id, before, client, *, seconds=4, active=False):
        deadline = time.monotonic() + seconds
        while True:
            current, provider = self.run.snapshot(), self.run.provider()
            unchanged = current == before if not active else (
                same_accounts(current, before) and current['ledger'] == before['ledger']
                and current['images'] == before['images'] and current['activeJobs'] == 1
                and next(item for item in current['jobs'] if item['id'] == job_id)['status'] in ACTIVE - {'queued'})
            require(unchanged, 'RECOVERY_LATE_WORKER_MUTATED_STATE')
            require(sum(item['client_sha256'] == client for item in provider['provider']['jobs']) == 1,
                    'RECOVERY_DUPLICATE_PROVIDER_OPERATION')
            if time.monotonic() >= deadline:
                return {'database': current, 'provider': provider, 'observedSeconds': seconds}
            time.sleep(.5)

    def loss(self, case, signal):
        baseline, initial = self.run.snapshot(), self.ready()
        before = self.workers()
        job_id = self.run.held_job(case)
        claim = self.claim(job_id)
        active = [(name, row) for name, row in self.workers().items() if row['process']['currentJobId'] == job_id]
        require(len(active) == 1 and active[0][1]['process']['workerId'] == claim['claim']['workerId'],
                'RECOVERY_EXECUTING_WORKER_AMBIGUOUS')
        name, executing = active[0]
        case.update(beforeWorkers=before, dispatcherBefore=initial, claimBefore=claim,
                    executingService=name, publicActive=self.public(job_id, 'active'))
        client = case['acceptedBeforeAction']['provider']['provider']['jobs'][-1]['client_sha256']
        self.stable(job_id, self.run.snapshot(), client, active=True)
        renewed = self.claim(job_id)
        case['dispatcherDuring'] = self.dispatcher()
        require(case['dispatcherDuring']['claimedJobs'] == initial['claimedJobs'] + 1
                and renewed['claim']['workerId'] == claim['claim']['workerId'], 'RECOVERY_JOB_CLAIMED_MORE_THAN_ONCE')
        require(29.9 <= renewed['claim']['leaseUntil'] - renewed['claim']['renewedAt'] <= 30.1
                and renewed['claim']['renewedAt'] > claim['claim']['renewedAt'], 'RECOVERY_WORKER_HEARTBEAT_NOT_OBSERVED')
        case['renewedClaim'] = renewed
        resumed, started = signal != 'SIGSTOP', time.monotonic()
        try:
            row = self.action(name, 'kill', signal)
            require(row['State']['Running'] is (signal == 'SIGSTOP') and (signal != 'SIGKILL'
                    or row['State']['ExitCode'] == 137), 'RECOVERY_WORKER_LOSS_NOT_OBSERVED')
            case['loss'] = {'signal': signal, 'containerId': row['Id'], 'hostPidBefore': executing['hostPid'],
                            'runningAfterSignal': row['State']['Running'], 'exitCode': row['State'].get('ExitCode')}
            if signal == 'SIGSTOP':
                raw = self.shadow.docker('exec', row['Id'], 'python', '-c', PROCESS_READ, timeout=15)
                require(len(raw) <= 1024, 'RECOVERY_WORKER_PROCESS_RECEIPT_LIMIT')
                case['stoppedProcess'] = json.loads(raw)
                require(case['stoppedProcess'] == {'pid': 1, 'state': 'T', 'workerCommand': True},
                        'RECOVERY_WORKER_NOT_OS_STOPPED')
            case['providerReleasedAfterSignal'] = self.run.signal('release')
            self.run.checkpoint()
            after = wait_for(lambda: (value if next(item for item in value['jobs'] if item['id'] == job_id)['status'] == 'failed'
                else None) if (value := self.run.snapshot()) else None, seconds=40, code='RECOVERY_LEASE_LOSS_NOT_TERMINAL')
            accounting(after, [job_id], refunded=True)
            reason = 'worker_connection_lost' if signal == 'SIGKILL' else 'worker_heartbeat_expired'
            final_claim = self.claim(job_id)
            job = next(item for item in after['jobs'] if item['id'] == job_id)
            require(final_claim['claim'].get('lossReason') == reason and same_accounts(baseline, after)
                    and job['completed_at'] and job['result_image_id'] is None
                    and not any(image['job_id'] == job_id for image in after['images'])
                    and any(item['jobId'] == job_id and item['reason'] in REFUNDS and item['cause'] == 'worker_lease_expired'
                            for item in after['ledger']), 'RECOVERY_WORKER_REFUND_OR_FENCE_INVALID')
            if signal == 'SIGSTOP':
                require(time.monotonic() - started >= 25, 'RECOVERY_HEARTBEAT_LEASE_EXPIRED_EARLY')
            case.update(claimAfter=final_claim, afterLoss=after, elapsedSeconds=round(time.monotonic() - started, 3),
                        publicFailed=self.public(job_id, 'failed'))
            self.action(name, 'start' if signal == 'SIGKILL' else 'kill', None if signal == 'SIGKILL' else 'SIGCONT')
            resumed = True
            self.ready()
            case['lateResultFence'] = self.stable(job_id, after, client)
            case['dispatcherAfter'] = self.dispatcher()
            case['claimAfterFence'] = self.claim(job_id)
            require(case['claimAfterFence']['claim'] == final_claim['claim'], 'RECOVERY_EXPIRED_CLAIM_CHANGED')
            case['afterWorkers'] = after_workers = self.workers()
            recovered = after_workers[name]
            require(recovered['containerId'] == executing['containerId'] and
                    ((recovered['process']['workerId'] != executing['process']['workerId']
                      and recovered['hostPid'] != executing['hostPid']) if signal == 'SIGKILL' else
                     (recovered['process']['workerId'] == executing['process']['workerId']
                      and recovered['hostPid'] == executing['hostPid'])), 'RECOVERY_WORKER_RESTART_IDENTITY_INVALID')
            case.update(status='PASS', providerSubmissionsForSameJob=1)
        finally:
            if not resumed:
                self.action(name, 'kill', 'SIGCONT')
                case['stoppedWorkerResumed'] = True

    def server_only(self, case):
        before = self.workers()
        wire = self.run.signal('hold')
        try:
            for name in roles.WORKERS:
                self.action(name, 'stop')
            case['stoppedWorkers'] = self.workers(running=False)
            case['dispatcherWithoutWorkers'] = self.ready(0)
            job_id = self.run.submit(uuid.uuid4().hex)['id']
            charged = self.run.snapshot()
            accounting(charged, [job_id], refunded=False)
            case['queued'] = self.public(job_id, 'queued')
            deadline = time.monotonic() + 4
            while True:
                observed = self.run.provider()
                require(self.run.snapshot() == charged and observed['instanceId'] == wire['instanceId']
                        and observed['provider']['counts'].get('accepted', 0) == wire['provider']['counts'].get('accepted', 0),
                        'RECOVERY_SERVER_EXECUTED_WITHOUT_WORKER')
                if time.monotonic() >= deadline:
                    break
                time.sleep(.5)
            require(self.run.flow.guest.request('GET', '/api/live').get('ok') is True,
                    'RECOVERY_SERVER_LIVENESS_FAILED')
            require(self.run.flow.guest.request('GET', '/api/health', expected=(503,)).get('httpStatus') == 503,
                    'RECOVERY_NO_WORKER_READINESS_INVALID')
            case['durableQueued'] = charged
        finally:
            for name in roles.WORKERS:
                self.action(name, 'start')
        self.ready()
        wait_for(lambda: any(item['state'] == 'held' for item in self.run.provider()['provider']['jobs']), seconds=25)
        case['claimedAfterStart'] = self.claim(job_id)
        self.run.signal('release')
        after = wait_for(lambda: (value if next(item for item in value['jobs'] if item['id'] == job_id)['status'] == 'completed'
            else None) if (value := self.run.snapshot()) else None, seconds=30, code='RECOVERY_QUEUED_JOB_NOT_RECOVERED')
        accounting(after, [job_id], refunded=False)
        require(sum(item['job_id'] == job_id for item in after['images']) == 1, 'RECOVERY_RESULT_IMAGE_COUNT_INVALID')
        case.update(beforeWorkers=before, afterWorkers=self.workers(), afterRecovery=after,
                    publicCompleted=self.public(job_id, 'completed'), status='PASS')

    def workers_only(self, case):
        before, database, provider = self.workers(), self.run.snapshot(), self.run.provider()
        try:
            stopped = self.action('backend', 'stop')
            require(stopped['State']['Running'] is False, 'RECOVERY_API_STOP_NOT_OBSERVED')
            disconnected = wait_for(lambda: (rows if all(row['process']['state'] == 'reconnecting' for row in rows.values())
                else None) if (rows := self.workers()) else None, seconds=25, code='RECOVERY_WORKER_DID_NOT_DISCONNECT')
            response = self.run.flow.guest.request('GET', '/api/live', expected=(502, 503, 504))
            require(response.get('httpStatus') in {502, 503, 504}, 'RECOVERY_WORKER_SERVED_API')
            require(all(before[name]['hostPid'] == disconnected[name]['hostPid'] and before[name]['process']['workerId']
                == disconnected[name]['process']['workerId'] for name in roles.WORKERS), 'RECOVERY_WORKER_EXITED_WITH_API')
            case.update(disconnectedWorkers=disconnected, unavailableApiStatus=response['httpStatus'])
        finally:
            self.action('backend', 'start')
        wait_for(lambda: self.run.provider()['instanceId'] != provider['instanceId'], seconds=30)
        self.ready()
        after = self.run.snapshot()
        require(after == database and self.run.provider()['provider']['counts'].get('accepted', 0) == 0,
                'RECOVERY_ROLE_RESTART_REPLAYED_JOB')
        case.update(reconnectedWorkers=self.workers(), afterRestart=after, status='PASS')


def prove_workers(run, case):
    run.guard()
    probe = WorkerRun(run)
    case.update(probeScope='TWO_OS_CONTAINER_WORKERS', workerIpc=roles.ipc_guard(run.shadow, run.backend()['Id']))
    probe.ready()
    previous = None
    for name, action in (('connectionLoss', lambda row: probe.loss(row, 'SIGKILL')),
                         ('heartbeatExpiry', lambda row: probe.loss(row, 'SIGSTOP')),
                         ('serverOnly', probe.server_only), ('workersOnly', probe.workers_only)):
        row = case[name] = {'status': 'FAIL'}
        try:
            if name != 'connectionLoss':
                before = run.snapshot()
                row['freshFixture'] = run.recreate()
                require(run.snapshot() == before, 'RECOVERY_ROLE_RECYCLE_CHANGED_STATE')
                if previous and 'claimAfterFence' in previous:
                    claim = previous['claimAfterFence']
                    preserved = probe.claim(claim['jobId'])
                    require(preserved['claim'] == claim['claim'], 'RECOVERY_ROLE_RECYCLE_CHANGED_CLAIM')
                    row['preservedPreviousClaim'] = preserved
            action(row)
        finally:
            run.checkpoint()
        require(row['status'] == 'PASS', 'RECOVERY_WORKER_CASE_FAILED')
        previous = row
    case['status'] = 'PASS'
