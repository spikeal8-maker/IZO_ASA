"""Fail-closed role, image, IPC and offline-reader boundaries; no Docker claims."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from tools import docker_shadow_roles as roles
from tools.docker_shadow import OWNER, Shadow, ShadowError
from tools.docker_shadow_fixture import FixtureControls

PROJECT, SHA = 'izo-asa-shadow-role-contract', 'a' * 40
IMAGE = 'sha256:' + 'b' * 64


def acceptance_config():
    app = {'network_mode': 'service:guard', 'labels': {'io.izo.owner': OWNER}, 'user': '10001:10001',
           'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
           'depends_on': {'guard': {'condition': 'service_healthy'}}}
    backend = {**deepcopy(app), 'image': 'owned-backend', 'command': ['python', '/opt/izo/fixtures/docker_shadow_fixture.py'],
        'environment': {'IZO_SHADOW_FIXTURE': 'controlled-comfyui-v1', 'COMFYUI_BASE_URL': 'http://127.0.0.1:48991',
            'COMFYUI_MOCK_FALLBACK': 'false', 'IZO_PROCESS_ROLE': 'server', 'IZO_WORKER_SOCKET': roles.SOCKET},
        'volumes': [{'type': 'volume', 'source': suffix, 'target': target} for target, suffix in
                    {**roles.DATA_TARGETS, roles.IPC_TARGET: roles.IPC_VOLUME}.items()]}
    worker = {**deepcopy(app), 'image': 'owned-backend', 'command': list(roles.COMMAND), 'restart': 'no',
        'read_only': True, 'environment': dict(roles.ENVIRONMENT),
        'depends_on': {**app['depends_on'], 'backend': {'condition': 'service_started'}},
        'volumes': [{'type': 'volume', 'source': roles.IPC_VOLUME, 'target': roles.IPC_TARGET}],
        'healthcheck': {'test': ['CMD', *roles.COMMAND, '--health']}}
    guard = {'networks': {'shadow': {}}, 'dns': ['127.0.0.1'], 'labels': {'io.izo.owner': OWNER},
             'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
             'healthcheck': {'test': ['CMD', 'python', '/network_guard.py', '--check']}, 'image': 'owned-guard'}
    return {'services': {'backend': backend, 'worker': deepcopy(worker), 'worker_peer': deepcopy(worker),
                         'web': {**app, 'image': 'owned-web'}, 'guard': guard},
            'networks': {'shadow': {}}, 'volumes': {name: {'labels': {'io.izo.owner': OWNER}}
                for name in (*roles.DATA_TARGETS.values(), roles.IPC_VOLUME)}}


def worker_container():
    return {'Id': 'c' * 64, 'Image': IMAGE, 'Config': {'Cmd': list(roles.COMMAND), 'Entrypoint': None,
        'User': '10001:10001', 'Env': [key + '=' + value for key, value in roles.ENVIRONMENT.items()],
        'Healthcheck': {'Test': ['CMD', *roles.COMMAND, '--health']}},
        'Mounts': [{'Type': 'volume', 'Name': PROJECT + '_worker_ipc', 'Destination': roles.IPC_TARGET, 'RW': True}],
        'HostConfig': {'ReadonlyRootfs': True, 'RestartPolicy': {'Name': 'no'}}}


class RoleConfigTests(unittest.TestCase):
    def setUp(self):
        self.shadow = Shadow(PROJECT, SHA, fixture=True)

    def test_split_profile_is_explicit_and_combined_shadow_keeps_original_resources(self):
        self.shadow.compose = Mock(return_value=json.dumps(acceptance_config()))
        self.assertEqual(self.shadow.config(), acceptance_config())
        combined = Shadow(PROJECT, SHA)
        self.assertEqual(roles.services(combined), {'backend', 'web', 'guard'})
        self.assertEqual(roles.backend_targets(combined), roles.DATA_TARGETS)
        self.assertEqual(len(roles.services(self.shadow)), 5)
        self.assertEqual(roles.backend_targets(self.shadow)[roles.IPC_TARGET], 'worker_ipc')

    def test_missing_peer_or_wrong_server_role_cannot_use_legacy_three_process_receipt(self):
        for mutate in (lambda c: c['services'].pop('worker_peer'),
                       lambda c: c['services']['backend']['environment'].update(IZO_PROCESS_ROLE='combined')):
            config = acceptance_config()
            mutate(config)
            self.shadow.compose = Mock(return_value=json.dumps(config))
            with self.assertRaises(ShadowError):
                self.shadow.config()

    def test_worker_cannot_inherit_database_media_credentials_network_or_api_command(self):
        mutations = [lambda w: w['environment'].update(DATABASE_URL='/home/izo/data/app.sqlite3'),
            lambda w: w['environment'].update(ADMIN_ONE_TIME_CODE='PRIVATE_CANARY'),
            lambda w: w['volumes'].append({'type': 'volume', 'source': 'media-data', 'target': '/home/izo/media'}),
            lambda w: w.update(command=['python', '-m', 'uvicorn', 'main:app']),
            lambda w: w.update(network_mode='host'), lambda w: w.update(pid='host'),
            lambda w: w.update(user='0:0'), lambda w: w.update(read_only=False),
            lambda w: w.update(image='different-image'), lambda w: w.update(restart='always'),
            lambda w: w['depends_on']['backend'].update(condition='service_healthy'),
            lambda w: w['healthcheck'].update(test=['CMD', 'true'])]
        for mutate in mutations:
            config = acceptance_config()
            mutate(config['services']['worker_peer'])
            self.shadow.compose = Mock(return_value=json.dumps(config))
            with self.subTest(mutate=mutate), self.assertRaises(ShadowError):
                self.shadow.config()

    def test_extra_or_foreign_ipc_volume_is_rejected_before_creation(self):
        for mutate in (lambda c: c['volumes'].update(extra={}),
                       lambda c: c['volumes']['worker_ipc'].update(external=True),
                       lambda c: c['volumes']['worker_ipc']['labels'].update({'io.izo.owner': 'foreign'}),
                       lambda c: c['services']['backend']['volumes'][-1].update(read_only=True)):
            config = acceptance_config()
            mutate(config)
            with self.assertRaises(ShadowError):
                roles.config_guard(self.shadow, config)

    def test_same_source_labels_do_not_allow_a_different_worker_image(self):
        config = acceptance_config()
        config['services']['worker_peer']['image'] = 'different-same-revision'
        def inspect(_image, _inspect, reference):
            return json.dumps([{'Id': 'sha256:' + ('f' if reference.startswith('different') else 'b') * 64,
                'Config': {'Labels': {'org.opencontainers.image.revision': SHA,
                                     'org.opencontainers.image.source': 'spikeal8-maker/IZO_ASA'}}}])
        self.shadow.docker = Mock(side_effect=inspect)
        with self.assertRaisesRegex(ShadowError, 'WORKER_IMAGE_CHANGED'):
            self.shadow.image_guard(config)

    def test_unlabelled_ipc_name_collision_is_checked(self):
        self.shadow.containers = Mock(return_value=[])
        def docker(*args):
            if args[:3] == ('volume', 'ls', '--format'):
                return PROJECT + '_worker_ipc'
            if args[:2] == ('volume', 'inspect'):
                return json.dumps([{'Labels': None}])
            return ''
        self.shadow.docker = Mock(side_effect=docker)
        with self.assertRaisesRegex(ShadowError, 'RESOURCE_NAME_COLLISION'):
            self.shadow.ownership_guard()


class RuntimeRoleTests(unittest.TestCase):
    def test_worker_runtime_rejects_wrong_mount_identity_main_and_writable_root(self):
        shadow = SimpleNamespace(fixture=True, project=PROJECT)
        roles.runtime_guard(shadow, worker_container(), 'worker')
        for mutate in (lambda c: c['Mounts'][0].update(Name='foreign_worker_ipc'),
                       lambda c: c['Mounts'][0].update(RW=False),
                       lambda c: c['Config']['Env'].append('DATABASE_URL=PRIVATE_CANARY'),
                       lambda c: c['Config'].update(Cmd=['python', '-m', 'uvicorn', 'main:app']),
                       lambda c: c['HostConfig'].update(ReadonlyRootfs=False),
                       lambda c: c['HostConfig'].update(PidMode='host')):
            row = worker_container()
            mutate(row)
            with self.assertRaises(ShadowError):
                roles.runtime_guard(shadow, row, 'worker')

    def test_ipc_requires_exact_owned_uid_directory0700_and_socket0600(self):
        safe = {'directory': {'uid': 10001, 'gid': 10001, 'mode': 0o700, 'isDirectory': True},
                'socket': {'uid': 10001, 'gid': 10001, 'mode': 0o600, 'isSocket': True}}
        shadow = Mock()
        shadow.docker.return_value = json.dumps(safe)
        self.assertEqual(roles.ipc_guard(shadow, 'owned'), safe)
        for part, key, value in [('socket', 'mode', 0o666), ('directory', 'mode', 0o755),
                                 ('socket', 'isSocket', False), ('directory', 'uid', 0)]:
            wrong = deepcopy(safe)
            wrong[part][key] = value
            shadow.docker.return_value = json.dumps(wrong)
            with self.assertRaisesRegex(ShadowError, 'IPC_PERMISSIONS_INVALID'):
                roles.ipc_guard(shadow, 'owned')

    def test_offline_reader_override_cannot_merge_in_live_worker_ipc(self):
        backend = {'network_mode': 'none', 'volumes': [{'type': 'volume', 'source': suffix,
                    'target': target, 'read_only': True} for target, suffix in roles.DATA_TARGETS.items()]}
        encoded = roles.volume_override(backend)
        self.assertEqual(encoded.count('"volumes": !override ['), 1)
        decoded = json.loads(encoded.replace('"volumes": !override [', '"volumes": [', 1))
        self.assertEqual(decoded['services']['backend'], backend)
        self.assertNotIn('worker_ipc', encoded)

    def test_fixture_reads_existing_dispatcher_snapshot_without_private_metadata(self):
        controls = FixtureControls(None)
        controls.application = SimpleNamespace(generation_dispatcher=SimpleNamespace(snapshot=lambda: {
            'role': 'server', 'localConsumer': False, 'ready': True, 'connectedWorkers': 0, 'onlineWorkers': 2,
            'token': 'PRIVATE_CANARY', 'database': '/private/file', 'claimedJobs': 1}))
        receipt = controls.receipt()
        self.assertEqual(receipt['generationDispatcher']['onlineWorkers'], 2)
        self.assertNotIn('PRIVATE_CANARY', json.dumps(receipt))
        self.assertNotIn('/private/file', json.dumps(receipt))


if __name__ == '__main__':
    unittest.main()
