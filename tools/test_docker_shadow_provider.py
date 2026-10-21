"""Real HTTP characterization of the controlled provider, never product bypass."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import socket
import struct
import threading
import time
import zlib
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from backend.app.integrations import comfyui_client as client
from backend.app.services import comfyui_results as results
from backend.app.services import comfyui_workflows as workflows
from tools import docker_shadow_provider as fixture


@pytest.fixture(autouse=True)
def local_http_only(monkeypatch):
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('NO_PROXY', '127.0.0.1')
    monkeypatch.setenv('no_proxy', '127.0.0.1')
    for method in ('connect', 'connect_ex'):
        original = getattr(socket.socket, method)
        def guarded(owned, address, original=original):
            assert address[0] == '127.0.0.1', 'OUTBOUND_TEST_NETWORK_FORBIDDEN'
            return original(owned, address)
        monkeypatch.setattr(socket.socket, method, guarded)


def free_ports():
    sockets = []
    try:
        for _ in range(2):
            owned = socket.socket()
            sockets.append(owned)
            owned.bind(('127.0.0.1', 0))
        ports = [owned.getsockname()[1] for owned in sockets]
        assert min(ports) >= 20000
        return ports
    finally:
        for owned in sockets:
            owned.close()


@pytest.fixture
def provider():
    ports = free_ports()
    with fixture.ControlledProvider(bind='127.0.0.1', port=ports[0], control_port=ports[1]) as owned:
        yield owned
    for port in ports:
        with socket.socket() as probe:
            probe.settimeout(.2)
            assert probe.connect_ex(('127.0.0.1', port)) != 0
        with socket.socket() as reusable:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                reusable.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            reusable.bind(('127.0.0.1', port))
    assert not owned._connections
    assert all(not thread.is_alive() for thread in owned._threads)
    assert all(not thread.is_alive() for thread in owned._pool._threads)


def control(provider, route, payload):
    with httpx.Client(trust_env=False) as http:
        response = http.post(provider.control_url + route, json=payload,
                             headers={'Authorization': 'Bearer ' + provider.control_token})
    response.raise_for_status()
    return response.json()


def submit(provider, job='private-job-canary', timeout=1):
    return asyncio.run(client.submit_comfyui_workflow(base_url=provider.base_url,
                       workflow={'1': {'inputs': {'text': 'private-prompt-canary'}}},
                       job_id=job, timeout_seconds=timeout))


def test_fixture_png_checksums_and_strict_decode():
    content = fixture.PNG
    assert content.startswith(b'\x89PNG\r\n\x1a\n')
    offset, chunks = 8, []
    while offset < len(content):
        size, = struct.unpack_from('>I', content, offset)
        end = offset + 8 + size
        assert end + 4 <= len(content)
        kind, body = content[offset + 4:offset + 8], content[offset + 8:end]
        expected_crc, = struct.unpack_from('>I', content, end)
        assert zlib.crc32(kind + body) & 0xffffffff == expected_crc
        chunks.append(kind)
        offset = end + 4
    assert offset == len(content) and chunks == [b'IHDR', b'IDAT', b'IEND']
    with Image.open(io.BytesIO(content)) as png:
        png.verify()  # load() alone tolerates a damaged IDAT checksum.
    with Image.open(io.BytesIO(content)) as png:
        png.load()
        assert png.size == (1, 1) and png.format == 'PNG'
        assert png.convert('RGBA').getpixel((0, 0)) == (255, 255, 255, 255)


def test_actual_client_discovery_workflow_hold_release_and_png(provider, tmp_path):
    async def exercise():
        base = {'base_url': provider.base_url}
        assert await client.comfyui_flux_klein_available(**base)
        assert await client.fetch_comfyui_node_names(**base) == {'FluxKleinOneNode'}
        models = await client.fetch_comfyui_models(**base)
        assert 'flux-2-klein-4b-fp8.safetensors' in models['diffusion_models']
        assert await client.fetch_flux_klein_config(**base) == {
            'autofill_prompts': {}, 'lora_triggers_custom': {}, 't2i_templates': [], 'discover_prompts': {}}
        graph = await client.fetch_comfyui_workflow(**base, endpoint='workflow_t2i')
        request = SimpleNamespace(prompt='private-prompt-canary', negativePrompt='', mode='text_to_image',
                                  width=512, height=512, seed=17, steps=4, cfg=1, strength=.8, loras=[])
        workflows.patch_shared_flux_nodes(graph, request, models['diffusion_models'][0], models['text_encoders'][0],
                                         models['vaes'][0], default_negative_prompt='',
                                         model_profiles={'flux_klein_4b': {'sampler': 'euler'}})
        assert graph['FK:166']['inputs']['text'] == request.prompt
        assert graph['FK:171']['inputs']['seed'] == 17
        control(provider, '/plan', {'mode': 'hold', 'hold_seconds': 5})
        payload = await client.submit_comfyui_workflow(**base, workflow=graph, job_id='private-job-canary')
        prompt_id = results.prompt_id_from_submission(payload)
        async with client.ComfyUIHistoryClient(**base) as polling:
            assert await polling.fetch(prompt_id) == {}
            assert provider.receipt()['jobs'][0]['state'] == 'held'
            control(provider, '/release', {'prompt_id': prompt_id})
            history = await polling.fetch(prompt_id)
        images = results.extract_images_from_history(history[prompt_id])
        content = await client.fetch_comfyui_image_bytes(**base, image=images[0])
        with Image.open(io.BytesIO(content)) as png:
            png.verify()
        with Image.open(io.BytesIO(content)) as png:
            png.load()
            assert png.size == (1, 1) and png.format == 'PNG'
        image_file = tmp_path / 'private-original-name.png'
        image_file.write_bytes(content)
        uploaded = await client.upload_comfyui_image(**base, path=image_file)
        assert uploaded.endswith('.png') and uploaded != image_file.name
        edit = await client.fetch_comfyui_workflow(**base, endpoint='workflow_edit')
        request.mode = 'edit'
        workflows.patch_mode_nodes(edit, request, {'input1': uploaded}, models['diffusion_models'][0],
                                   models['text_encoders'][0], models['vaes'][0], default_negative_prompt='',
                                   model_profiles={'flux_klein_4b': {'sampler': 'euler'}})
        assert edit['FK:91']['inputs']['image'] == uploaded
        await client.interrupt_comfyui(**base)
        assert await client.free_comfyui_memory(**base)
    asyncio.run(exercise())
    receipt = json.dumps(provider.receipt())
    for secret in ['private-prompt-canary', 'private-job-canary', 'private-original-name', provider.control_token]:
        assert secret not in receipt
    assert provider.receipt()['counts']['accepted'] == 1


def test_loss_after_acceptance_does_not_fake_idempotency(provider):
    control(provider, '/plan', {'mode': 'disconnect'})
    with pytest.raises(httpx.RemoteProtocolError):
        submit(provider)
    first = provider.receipt()['jobs'][0]['prompt_id']
    second = results.prompt_id_from_submission(submit(provider))
    assert first != second
    assert provider.receipt()['counts']['accepted'] == 2
    assert provider.receipt()['jobs'][0]['client_sha256'] == provider.receipt()['jobs'][1]['client_sha256']
    assert provider.receipt()['application_exactly_once'] == 'NOT_TESTED'


def test_silence_causes_real_client_read_timeout_after_acceptance(provider):
    control(provider, '/plan', {'mode': 'silence', 'silence_seconds': .3, 'hold_seconds': 3})
    with pytest.raises(httpx.ReadTimeout):
        submit(provider, timeout=.05)
    assert provider.receipt()['counts']['accepted'] == 1
    assert provider.receipt()['jobs'][0]['state'] == 'held'


def test_hold_deadline_expires_and_cannot_be_released(provider):
    control(provider, '/plan', {'mode': 'hold', 'hold_seconds': .02})
    prompt_id = results.prompt_id_from_submission(submit(provider))
    time.sleep(.03)
    assert provider.receipt()['jobs'][0]['state'] == 'expired'
    with pytest.raises(httpx.HTTPStatusError):
        control(provider, '/release', {'prompt_id': prompt_id})
    async def check():
        async with client.ComfyUIHistoryClient(base_url=provider.base_url) as polling:
            assert await polling.fetch(prompt_id) == {}
    asyncio.run(check())


def raw(provider, data):
    port = int(provider.base_url.rsplit(':', 1)[1])
    with socket.create_connection(('127.0.0.1', port), timeout=4) as owned:
        owned.sendall(data)
        return owned.recv(4096)


@pytest.mark.parametrize('wire,status', [
    (b'POST /prompt HTTP/1.1\r\nContent-Length: 1048577\r\n\r\n', b'413'),
    (b'GET / HTTP/1.1\r\nX: ' + b'a' * 16384, b'431'),
    (b'POST /prompt HTTP/1.1\r\nContent-Length: 1\r\nContent-Length: 1\r\n\r\nx', b'400'),
    (b'POST /prompt HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n', b'400'),
    (b'GET /view?filename=../../foreign&subfolder=&type=output HTTP/1.1\r\n\r\n', b'404'),
], ids=['body-too-large', 'headers-too-large', 'duplicate-length', 'chunked', 'foreign-path'])
def test_http_bounds_and_path_rejection(provider, wire, status):
    try:
        response = raw(provider, wire)
    except (ConnectionResetError, ConnectionAbortedError):
        # Windows can reset on close with unread over-limit header bytes.
        assert status == b'431'
    else:
        assert status in response.split(b'\r\n', 1)[0]
    assert provider.receipt()['counts'].get('accepted', 0) == 0


def test_control_auth_separation_and_plan_bounds(provider):
    with httpx.Client(trust_env=False) as http:
        assert http.post(provider.control_url + '/plan', json={'mode': 'hold'}).status_code == 403
        assert http.get(provider.base_url + '/receipt').status_code == 404
        assert http.post(provider.base_url + '/plan', json={'mode': 'complete'}).status_code == 404
        response = http.post(provider.control_url + '/plan', json={'mode': 'hold', 'hold_seconds': 61},
                             headers={'Authorization': 'Bearer ' + provider.control_token})
        assert response.status_code == 409
    control(provider, '/plan', {'mode': 'hold', 'hold_seconds': 2})
    with pytest.raises(httpx.HTTPStatusError):
        control(provider, '/plan', {'mode': 'complete'})


def test_absolute_header_and_body_deadlines(provider, monkeypatch):
    monkeypatch.setattr(fixture, 'READ_DEADLINE', .15)
    for incomplete in [b'GET /object_info HTTP/1.1\r\nX: ', b'POST /prompt HTTP/1.1\r\nContent-Length: 10\r\n\r\nx']:
        started = time.monotonic()
        raw(provider, incomplete)
        assert time.monotonic() - started < .7
    assert provider.receipt()['counts']['transport_closed'] == 2


def test_slow_drip_does_not_extend_absolute_deadline(provider, monkeypatch):
    monkeypatch.setattr(fixture, 'READ_DEADLINE', .15)
    port = int(provider.base_url.rsplit(':', 1)[1])
    with socket.create_connection(('127.0.0.1', port), timeout=1) as owned:
        owned.sendall(b'GET /object_info HTTP/1.1\r\nX: ')
        def drip():
            try:
                for _ in range(20):
                    time.sleep(.03)
                    owned.sendall(b'a')
            except OSError:
                pass
        thread = threading.Thread(target=drip)
        thread.start()
        started = time.monotonic()
        try:
            try:
                response = owned.recv(4096)
            except (ConnectionResetError, ConnectionAbortedError):
                # Windows can report the fixture's deadline close as a reset.
                pass
            else:
                assert response == b'' or b'408' in response.split(b'\r\n', 1)[0]
            assert time.monotonic() - started < .4
        finally:
            try:
                owned.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            thread.join(1)
        assert not thread.is_alive()
        counts = provider.receipt()['counts']
        assert counts.get('accepted', 0) == 0
        assert counts.get('rejected', 0) + counts.get('transport_closed', 0) == 1


def test_lifetime_automatically_closes_own_listeners_and_workers():
    ports = free_ports()
    with fixture.ControlledProvider(bind='127.0.0.1', port=ports[0], control_port=ports[1], lifetime_seconds=1) as owned:
        submit(owned)
        until = time.monotonic() + 2
        while not owned._closed and time.monotonic() < until:
            time.sleep(.01)
        assert owned._closed
        assert all(not thread.is_alive() for thread in owned._pool._threads)
        for port in ports:
            with socket.socket() as probe:
                probe.settimeout(.2)
                assert probe.connect_ex(('127.0.0.1', port)) != 0


def test_interrupt_changes_only_owned_held_state_and_upload_limit(provider, monkeypatch):
    control(provider, '/plan', {'mode': 'hold', 'hold_seconds': 2})
    submit(provider)
    asyncio.run(client.interrupt_comfyui(base_url=provider.base_url))
    assert provider.receipt()['jobs'][0]['state'] == 'interrupted'
    with httpx.Client(trust_env=False) as http:
        assert http.post(provider.base_url + '/upload/image', files={'image': ('secretname.txt', b'bad', 'text/plain')},
                         data={'overwrite': 'true', 'type': 'input'}).status_code == 415
        monkeypatch.setattr(fixture, 'MAX_JOBS', 1)
        for expected in [200, 429]:
            response = http.post(provider.base_url + '/upload/image', files={'image': ('private-upload.png', fixture.PNG, 'image/png')},
                                 data={'overwrite': 'true', 'type': 'input'})
            assert response.status_code == expected
    assert len(provider.receipt()['uploads']) == 1
    assert 'private-upload' not in json.dumps(provider.receipt())


def test_concurrency_and_retention_are_bounded(provider, monkeypatch):
    monkeypatch.setattr(fixture, 'MAX_JOBS', 3)
    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(lambda _: results.prompt_id_from_submission(submit(provider)), range(3)))
    assert len(set(ids)) == 3
    with pytest.raises(httpx.HTTPStatusError) as error:
        submit(provider)
    assert error.value.response.status_code == 429
    opened = []
    try:
        port = int(provider.base_url.rsplit(':', 1)[1])
        for _ in range(4):
            own = socket.create_connection(('127.0.0.1', port), timeout=1)
            opened.append(own)
            own.sendall(b'GET /object_info HTTP/1.1\r\nX: ')
        until = time.monotonic() + 1
        while len(provider._connections) != 4 and time.monotonic() < until:
            time.sleep(.005)
        assert len(provider._connections) == 4
        with socket.create_connection(('127.0.0.1', port), timeout=1) as excess:
            assert excess.recv(1) == b''
        assert provider.receipt()['counts']['concurrency_rejected'] == 1
    finally:
        for own in opened:
            own.close()


def test_foreign_port_not_replaced_and_partial_start_is_cleaned():
    port, control_port = free_ports()
    with socket.socket() as foreign:
        foreign.bind(('127.0.0.1', control_port))
        foreign.listen()
        with pytest.raises(OSError):
            with fixture.ControlledProvider(bind='127.0.0.1', port=port, control_port=control_port):
                pytest.fail('Must reject occupied control port')
        assert foreign.getsockname()[1] == control_port
        with socket.socket() as reusable:
            reusable.bind(('127.0.0.1', port))


def test_dispatch_failure_closes_unassigned_connection_and_releases_permit(provider, monkeypatch):
    def fail(*_):
        raise RuntimeError('CONTROLLED_DISPATCH_FAILURE')
    monkeypatch.setattr(provider._pool, 'submit', fail)
    try:
        assert raw(provider, b'GET /object_info HTTP/1.1\r\n\r\n') == b''
    except (ConnectionResetError, ConnectionAbortedError):
        pass
    until = time.monotonic() + 1
    while provider._connections and time.monotonic() < until:
        time.sleep(.005)
    assert not provider._connections
    assert provider._slots._value == 4
    assert provider.receipt()['counts']['dispatch_failed'] == 1


def test_partial_thread_start_failure_cleans_without_joining_unstarted_thread(monkeypatch):
    original = threading.Thread.start
    count = 0
    def start(thread):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError('CONTROLLED_THREAD_START_FAILURE')
        return original(thread)
    monkeypatch.setattr(threading.Thread, 'start', start)
    ports = free_ports()
    owned = fixture.ControlledProvider(bind='127.0.0.1', port=ports[0], control_port=ports[1])
    with pytest.raises(RuntimeError, match='CONTROLLED_THREAD_START_FAILURE'):
        owned.__enter__()
    assert owned._closed and not owned._connections
    assert all(not thread.is_alive() for thread in owned._threads)
    for port in ports:
        with socket.socket() as reusable:
            reusable.bind(('127.0.0.1', port))


@pytest.mark.parametrize('bind,port,control_port', [('0.0.0.0', 48131, 48132), ('localhost', 48131, 48132),
                                                  ('127.0.0.1', 0, 48132), ('127.0.0.1', 48131, 48131)])
def test_explicit_loopback_and_high_ports_required(bind, port, control_port):
    with pytest.raises(ValueError):
        fixture.ControlledProvider(bind=bind, port=port, control_port=control_port)
