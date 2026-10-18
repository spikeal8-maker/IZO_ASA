"""Adversarial receipt and compensation tests; real Docker proof is a separate gate."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import docker_clean_workers as workers
from tools.docker_clean_recovery import RecoveryError
from tools.test_docker_clean_recovery import provider, snapshot
from tools.test_docker_shadow_roles import IMAGE, PROJECT, worker_container


def status(number=1, *, job=None):
    return {'version': 1, 'role': 'worker', 'workerId': str(number) * 32, 'pid': 1,
        'state': 'working' if job else 'idle', 'currentJobId': job, 'lastContactAt': 100.,
        'lastSuccessAt': None, 'lastFailureAt': None, 'httpRequests': 2, 'httpResponses': 1,
        'httpFailures': 0, 'completedJobs': 0}


def processes(*, active=False, restarted=False):
    return {name: {'containerId': str(index) * 64, 'hostPid': 100 + index + 100 * int(restarted and index == 1),
        'imageId': IMAGE, 'startedAt': 'fixture-start',
        'process': status(3 if restarted and index == 1 else index, job='job-a' if active and index == 1 else None)}
        for index, name in enumerate(workers.roles.WORKERS, 1)}


def rows():
    result = []
    for number, service in enumerate(('backend', 'worker', 'worker_peer', 'guard', 'web'), 1):
        row = worker_container()
        row.update(Id=str(number) * 64, State={'Running': True, 'Pid': 100 + number, 'StartedAt': 'fixture-start'},
                   NetworkSettings={'Networks': {}})
        row['Config']['Labels'] = {'io.izo.owner': 'SHADOW-TOPOLOGY-01', 'com.docker.compose.project': PROJECT,
                                  'com.docker.compose.service': service, 'com.docker.compose.oneoff': 'False'}
        row['HostConfig'].update(NetworkMode='container:' + '4' * 64, CapDrop=['ALL'],
                                  SecurityOpt=['no-new-privileges:true'], Privileged=False)
        if service == 'backend':
            row['Config']['Env'] = ['IZO_PROCESS_ROLE=server', 'IZO_WORKER_SOCKET=' + workers.roles.SOCKET]
            row['Mounts'] = [{'Type': 'volume', 'Destination': key, 'Name': PROJECT + '_' + value, 'RW': True}
                for key, value in workers.roles.backend_targets(SimpleNamespace(fixture=True)).items()]
        result.append(row)
    return result


def run_object():
    shadow = Mock(fixture=True, project=PROJECT)
    shadow.containers.return_value = rows()
    shadow.docker.side_effect = lambda _exec, cid, *_args, **_kwargs: json.dumps(status(1 if cid == '2' * 64 else 2))
    return SimpleNamespace(shadow=shadow, images={name: IMAGE for name in workers.roles.services(shadow)},
        user_ids=['owner', 'other'], guard=Mock(), checkpoint=Mock(), inside=Mock(), flow=Mock(),
        provider=Mock(return_value=provider(accepted=1)), snapshot=Mock(), held_job=Mock(), signal=Mock(), recreate=Mock())


class PrivateEvidenceTests(unittest.TestCase):
    def test_scoped_claim_reader_uses_read_only_sqlite_and_never_exports_token_or_prompt(self):
        connect = sqlite3.connect
        with tempfile.TemporaryDirectory(prefix='izo-worker-claim-') as directory:
            path = Path(directory) / 'jobs.sqlite3'
            with connect(path) as database:
                database.execute('CREATE TABLE jobs(id TEXT,user_id TEXT,settings_json TEXT)')
                database.executemany('INSERT INTO jobs VALUES(?,?,?)', [('job-a', 'owner', json.dumps({
                    'prompt': 'PRIVATE_CANARY', '_workerClaim': {'version': 2, 'workerId': 'a' * 32,
                    'token': 'PRIVATE_CAPABILITY', 'issuedAt': 10, 'renewedAt': 12, 'leaseUntil': 42,
                    'providerCommands': 1, 'lossReason': 'worker_connection_lost'}})),
                    ('foreign-job', 'foreign-user', json.dumps({'_workerClaim': {'workerId': 'FOREIGN_CANARY'}}))])
            database.close()
            before = path.read_bytes()
            def opened(database_uri, **kwargs):
                self.assertEqual(database_uri, 'file:/home/izo/data/app.sqlite3?mode=ro')
                self.assertEqual(kwargs, {'uri': True, 'timeout': 5})
                return connect(path.as_uri() + '?mode=ro', **kwargs)
            output = io.StringIO()
            with patch.object(sqlite3, 'connect', side_effect=opened), patch.object(sys, 'argv',
                    ['probe', json.dumps(['job-a', ['owner']])]), redirect_stdout(output):
                exec(compile(workers.CLAIM_READ, '<bounded-claim-reader>', 'exec'), {})
            value = json.loads(output.getvalue())
            self.assertEqual(value['claim']['workerId'], 'a' * 32)
            self.assertEqual(value['claim']['lossReason'], 'worker_connection_lost')
            self.assertNotIn('CANARY', output.getvalue())
            self.assertNotIn('PRIVATE_CAPABILITY', output.getvalue())
            self.assertEqual(before, path.read_bytes())
            with patch.object(sqlite3, 'connect', side_effect=opened), patch.object(sys, 'argv',
                    ['probe', json.dumps(['foreign-job', ['owner']])]), self.assertRaises(AssertionError):
                exec(compile(workers.CLAIM_READ, '<bounded-claim-reader>', 'exec'), {})

    def test_worker_receipt_rejects_unknown_private_fields_invalid_uuid_and_nonfinite_times(self):
        self.assertEqual(workers.worker_status(status()), status())
        for key, value in [('token', 'PRIVATE_CANARY'), ('workerId', 'invalid'), ('pid', False),
                           ('lastContactAt', float('nan')), ('httpRequests', -1), ('state', 'serving-api')]:
            with self.subTest(key=key), self.assertRaises(RecoveryError):
                workers.worker_status({**status(), key: value})

    def test_two_independent_worker_processes_are_required(self):
        run = run_object()
        proof = workers.WorkerRun(run)
        observed = proof.workers()
        self.assertEqual(len({row['hostPid'] for row in observed.values()}), 2)
        for change in ('duplicate-pid', 'duplicate-worker-id', 'missing-peer', 'foreign-owner', 'host-network'):
            run = run_object()
            state = rows()
            if change == 'duplicate-pid':
                state[2]['State']['Pid'] = state[1]['State']['Pid']
            elif change == 'duplicate-worker-id':
                run.shadow.docker.side_effect = None
                run.shadow.docker.return_value = json.dumps(status())
            elif change == 'missing-peer':
                state.pop(2)
            elif change == 'foreign-owner':
                state[2]['Config']['Labels']['io.izo.owner'] = 'foreign'
            else:
                state[2]['HostConfig']['NetworkMode'] = 'host'
            run.shadow.containers.return_value = state
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                workers.WorkerRun(run).workers()

    def test_server_receipt_cannot_disguise_a_local_consumer_as_separate_workers(self):
        run = run_object()
        base = {'role': 'server', 'localConsumer': False, 'ready': True, 'connectedWorkers': 0, 'onlineWorkers': 2,
                'claimedJobs': 1, 'completedJobs': 0, 'expiredLeases': 0}
        run.provider.return_value['generationDispatcher'] = base
        self.assertEqual(workers.WorkerRun(run).dispatcher(), base)
        for key, value in [('localConsumer', True), ('role', 'combined'), ('connectedWorkers', 2), ('onlineWorkers', 65), ('claimedJobs', '1')]:
            run.provider.return_value['generationDispatcher'] = {**base, key: value}
            with self.assertRaisesRegex(RecoveryError, 'SERVER_ROLE_NOT_PROVEN'):
                workers.WorkerRun(run).dispatcher()

    def test_mutation_cannot_escape_owned_service_identity_or_source_admission(self):
        run = run_object()
        probe = workers.WorkerRun(run)
        for name, action, signal in [('foreign', 'stop', None), ('worker', 'kill', 'SIGUSR1'), ('worker', 'rm', None)]:
            with self.assertRaises(RecoveryError):
                probe.action(name, action, signal)
        run.shadow.compose.assert_not_called()
        run.guard.side_effect = RuntimeError('SOURCE_CHANGED')
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_CHANGED'):
            probe.action('worker', 'kill', 'SIGKILL')
        run.shadow.compose.assert_not_called()
        run.guard.side_effect = None
        changed = rows()
        changed[1]['Id'] = 'f' * 64
        run.shadow.containers.side_effect = [rows(), changed]
        with self.assertRaisesRegex(RecoveryError, 'CONTAINER_REPLACED'):
            probe.action('worker', 'kill', 'SIGKILL')


class LeaseFailureTests(unittest.TestCase):
    def configured_loss(self, signal='SIGKILL', *, refund_cause='worker_lease_expired', duplicate_refund=False):
        run = run_object()
        restored = snapshot(['job-a'], refunded=True, status='failed')
        restored['ledger'][-1]['cause'] = refund_cause
        if duplicate_refund:
            restored['ledger'].append(deepcopy(restored['ledger'][-1]))
        run.snapshot.side_effect = [snapshot(), snapshot(['job-a']), restored]
        def held(case):
            case['acceptedBeforeAction'] = {'provider': provider(accepted=1)}
            return 'job-a'
        run.held_job.side_effect = held
        probe = workers.WorkerRun(run)
        probe.ready = Mock(return_value={'claimedJobs': 0})
        probe.workers = Mock(side_effect=[processes(), processes(active=True), processes(restarted=signal == 'SIGKILL')])
        claim = {'jobId': 'job-a', 'sampledAt': 110, 'claim': {'workerId': '1' * 32,
                  'issuedAt': 100, 'renewedAt': 102, 'leaseUntil': 132, 'providerCommands': 1}}
        renewed = deepcopy(claim)
        renewed['claim'].update(renewedAt=106, leaseUntil=136)
        final = deepcopy(renewed)
        final['claim'].update(leaseUntil=0, lossReason='worker_connection_lost' if signal == 'SIGKILL' else 'worker_heartbeat_expired')
        probe.claim = Mock(side_effect=[claim, renewed, final, deepcopy(final)])
        probe.public = Mock(return_value={'public': 'observed'})
        probe.dispatcher = Mock(return_value={'claimedJobs': 1})
        probe.stable = Mock(return_value={'database': restored})
        probe.action = Mock(return_value={'Id': '1' * 64, 'State': {'Running': signal == 'SIGSTOP', 'ExitCode': 137}})
        if signal == 'SIGSTOP':
            run.shadow.docker.side_effect = None
            run.shadow.docker.return_value = json.dumps({'pid': 1, 'state': 'T', 'workerCommand': True})
        return run, probe

    def test_executing_container_death_requires_canonical_refund_and_new_process_identity(self):
        run, probe = self.configured_loss()
        case = {}
        probe.loss(case, 'SIGKILL')
        self.assertEqual(case['status'], 'PASS')
        self.assertEqual(case['loss']['signal'], 'SIGKILL')
        self.assertEqual(probe.action.call_args_list[0].args, ('worker', 'kill', 'SIGKILL'))
        self.assertEqual(probe.action.call_args_list[-1].args, ('worker', 'start', None))
        run.signal.assert_called_once_with('release')
        self.assertEqual(case['providerSubmissionsForSameJob'], 1)

    def test_cancel_refund_or_duplicate_refund_cannot_satisfy_worker_lease_failure(self):
        for cause, duplicate in [('user_cancelled', False), ('worker_lease_expired', True)]:
            run, probe = self.configured_loss(refund_cause=cause, duplicate_refund=duplicate)
            case = {}
            with self.assertRaises(RecoveryError):
                probe.loss(case, 'SIGKILL')
            self.assertNotEqual(case.get('status'), 'PASS')
            run.signal.assert_called_once_with('release')

    def test_heartbeat_expiry_waits_for_real_lease_window_and_resumes_same_process(self):
        run, probe = self.configured_loss('SIGSTOP')
        case = {}
        with patch.object(workers.time, 'monotonic', side_effect=[0, 30, 31, 32]):
            probe.loss(case, 'SIGSTOP')
        self.assertEqual(case['status'], 'PASS')
        self.assertEqual(case['afterWorkers']['worker']['hostPid'], case['beforeWorkers']['worker']['hostPid'])
        self.assertEqual(probe.action.call_args_list[-1].args, ('worker', 'kill', 'SIGCONT'))

    def test_failed_heartbeat_proof_still_resumes_only_original_owned_service(self):
        run, probe = self.configured_loss('SIGSTOP', refund_cause='user_cancelled')
        case = {}
        with self.assertRaises(RecoveryError):
            probe.loss(case, 'SIGSTOP')
        self.assertTrue(case['stoppedWorkerResumed'])
        self.assertEqual(probe.action.call_args_list[-1].args, ('worker', 'kill', 'SIGCONT'))
        run.signal.assert_called_once_with('release')

    def test_late_result_or_second_provider_submission_never_passes_fencing(self):
        baseline = snapshot(['job-a'], refunded=True, status='failed')
        for change in ('ledger', 'image', 'provider'):
            run = run_object()
            after = deepcopy(baseline)
            if change == 'ledger':
                after['ledger'].append({'jobId': 'job-a', 'reason': 'daily_generation'})
            elif change == 'image':
                after['images'].append({'job_id': 'job-a', 'id': 'late-image'})
            else:
                run.provider.return_value = provider(accepted=2)
            run.snapshot.return_value = after
            with self.assertRaises(RecoveryError):
                workers.WorkerRun(run).stable('job-a', baseline, 'b' * 64, seconds=0)

    def test_active_progress_can_change_without_masking_a_duplicate_charge(self):
        run = run_object()
        before = snapshot(['job-a'])
        after = deepcopy(before)
        after['jobs'][0]['progress'] = 63
        run.snapshot.return_value = after
        workers.WorkerRun(run).stable('job-a', before, 'b' * 64, seconds=0, active=True)
        after['ledger'].append(deepcopy(after['ledger'][0]))
        with self.assertRaises(RecoveryError):
            workers.WorkerRun(run).stable('job-a', before, 'b' * 64, seconds=0, active=True)


class PublicAndAggregateTests(unittest.TestCase):
    def test_public_list_detail_and_legacy_api_must_agree_with_durable_terminal_state(self):
        for wrong in (None, 'list', 'detail', 'api', 'private'):
            run = run_object()
            def request(method, path, *args, **kwargs):
                if path.startswith('/api/jobs/'):
                    return {'id': 'job-a', 'status': 'running' if wrong == 'api' else 'failed',
                            **({'_workerClaim': {'token': 'PRIVATE_CANARY'}} if wrong == 'private' else {})}
                if path.endswith('/job-a'):
                    return {'ok': True, 'job': {'id': 'job-a', 'status': 'created' if wrong == 'detail' else 'failed'}}
                return {'ok': True, 'items': [] if 'active=true' in path else [{'id': 'job-a',
                    'status': 'created' if wrong == 'list' else 'failed'}]}
            run.flow.owner.request.side_effect = request
            if wrong is None:
                self.assertEqual(workers.WorkerRun(run).public('job-a', 'failed')['phoneListStatus'], 'failed')
                run.flow.other.request.assert_called_once_with('GET', '/api/phone/v1/jobs/job-a', expected=(404,))
                run.flow.guest.request.assert_called_once_with('GET', '/api/phone/v1/jobs/job-a', expected=(401,))
            else:
                with self.assertRaises(RecoveryError):
                    workers.WorkerRun(run).public('job-a', 'failed')

    def test_aggregate_requires_all_four_real_role_phases_and_checkpoints_failures(self):
        run = run_object()
        run.backend = Mock(return_value={'Id': 'a' * 64})
        with patch.object(workers.roles, 'ipc_guard', return_value={'permissions': 'measured'}), \
             patch.object(workers, 'WorkerRun') as factory:
            probe = factory.return_value
            probe.loss.side_effect = lambda row, signal: row.update(status='PASS')
            probe.server_only.side_effect = lambda row: row.update(status='PASS')
            probe.workers_only.side_effect = lambda row: row.update(status='FAIL')
            case = {}
            with self.assertRaisesRegex(RecoveryError, 'WORKER_CASE_FAILED'):
                workers.prove_workers(run, case)
            self.assertNotEqual(case.get('status'), 'PASS')
            self.assertEqual(case['workersOnly']['status'], 'FAIL')
            self.assertEqual(run.checkpoint.call_count, 4)


if __name__ == '__main__':
    unittest.main()
