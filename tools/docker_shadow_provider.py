"""Bounded loopback Comfy wire fixture; no model execution or application bypass.

Construct with two explicit unused high ports and use as a context manager.
The control capability exists only in memory. Receipts contain generated IDs,
counts and digests, never request text, supplied filenames or credentials.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from email.parser import BytesParser
from email.policy import default
import hashlib
import json
import math
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=')
MAX_BODY, MAX_HEADERS, MAX_JOBS = 1024 * 1024, 16384, 64
READ_DEADLINE, MAX_HOLD, MAX_SILENCE = 3.0, 60.0, 2.0
MODELS = {'diffusion_models': ['flux-2-klein-4b-fp8.safetensors', 'flux-2-klein-9b-fp8.safetensors'],
          'text_encoders': ['qwen_3_4b.safetensors', 'qwen_3_8b.safetensors'],
          'vaes': ['flux2-vae.safetensors'], 'loras': []}


def workflow():
    """Only the t2i/edit node IDs patched by comfyui_workflows are supported."""
    classes = {'165': 'UNETLoader', '155': 'CLIPLoader', '153': 'VAELoader',
               '166': 'CLIPTextEncode', '156': 'CLIPTextEncode', '170': 'EmptyLatentImage',
               '171': 'KSampler', '86': 'SaveImage', '169': 'ModelSamplingFlux'}
    return {f'FK:{key}': {'class_type': value, 'inputs': {}} for key, value in classes.items()}


class RequestError(Exception):
    def __init__(self, status=400):
        self.status = status


class ControlledProvider:
    """Owned HTTP listeners with at most four concurrent bounded requests."""

    def __init__(self, *, bind: str, port: int, control_port: int, lifetime_seconds=300):
        if bind != '127.0.0.1' or type(port) is not int or type(control_port) is not int:
            raise ValueError('EXPLICIT_IPV4_LOOPBACK_REQUIRED')
        if port == control_port or any(not 20000 <= p <= 65535 for p in (port, control_port)):
            raise ValueError('DISTINCT_HIGH_PORTS_REQUIRED')
        if not 1 <= lifetime_seconds <= 300 or not math.isfinite(lifetime_seconds):
            raise ValueError('BOUNDED_LIFETIME_REQUIRED')
        self.base_url, self.control_url = f'http://{bind}:{port}', f'http://{bind}:{control_port}'
        self.control_token = secrets.token_urlsafe(32)
        self._bind, self._ports, self._lifetime = bind, (port, control_port), lifetime_seconds
        self._lock, self._stop = threading.Lock(), threading.Event()
        self._slots = threading.BoundedSemaphore(4)
        self._listeners, self._threads, self._connections = [], [], set()
        self._jobs, self._uploads, self._counts = {}, {}, {}
        self._next = None
        self._pool = None
        self._started = False
        self._close_lock, self._closed, self._timer = threading.Lock(), False, None

    def __enter__(self):
        if self._started:
            raise RuntimeError('FIXTURE_ALREADY_USED')
        self._started = True
        try:
            for port in self._ports:
                listener = socket.socket()
                self._listeners.append(listener)
                # No SO_REUSEADDR: an existing listener must never be displaced.
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind((self._bind, port))
                listener.listen(4)
                listener.settimeout(.1)
            self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='shadow-provider')
            self._until = time.monotonic() + self._lifetime
            for index, listener in enumerate(self._listeners):
                thread = threading.Thread(target=self._accept, args=(listener, bool(index)), daemon=True)
                thread.start()
                self._threads.append(thread)
            self._timer = threading.Timer(self._lifetime, self.close)
            self._timer.daemon = True
            self._timer.start()
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_):
        self.close()

    def close(self):
        with self._close_lock:
            if not self._closed:
                self._stop.set()
                if self._timer:
                    self._timer.cancel()
                for listener in self._listeners:
                    listener.close()
                with self._lock:
                    for connection in self._connections:
                        try:
                            connection.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                for thread in self._threads:
                    thread.join(1)
                if self._pool:
                    self._pool.shutdown(wait=True, cancel_futures=False)
                self._closed = True
        if self._timer and self._timer.ident is not None and self._timer is not threading.current_thread():
            self._timer.join(1)

    def _count(self, name):
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + 1

    def _accept(self, listener, control):
        while not self._stop.is_set() and time.monotonic() < self._until:
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self._slots.acquire(blocking=False):
                connection.close()
                self._count('concurrency_rejected')
                continue
            with self._lock:
                self._connections.add(connection)
            try:
                self._pool.submit(self._serve, connection, control)
            except BaseException:
                with self._lock:
                    self._connections.discard(connection)
                connection.close()
                self._slots.release()
                self._count('dispatch_failed')
                self._stop.set()
                break
        listener.close()

    @staticmethod
    def _read(connection):
        deadline, data = time.monotonic() + READ_DEADLINE, bytearray()

        def receive(limit):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestError(408)
            connection.settimeout(remaining)
            block = connection.recv(min(4096, limit))
            if not block:
                raise RequestError()
            return block

        while b'\r\n\r\n' not in data:
            if len(data) >= MAX_HEADERS:
                raise RequestError(431)
            data.extend(receive(MAX_HEADERS - len(data)))
        raw_headers, body = bytes(data).split(b'\r\n\r\n', 1)
        rows = raw_headers.split(b'\r\n')
        if len(rows[0]) > 1024 or len(rows) > 65:
            raise RequestError(431)
        method, target, version = rows[0].decode('ascii').split(' ')
        if method not in ('GET', 'POST') or version != 'HTTP/1.1' or not target.startswith('/'):
            raise RequestError()
        headers = {}
        for row in rows[1:]:
            name, value = row.decode('ascii').split(':', 1)
            name = name.lower()
            if name in headers or not name or any(c.isspace() for c in name):
                raise RequestError()
            headers[name] = value.strip()
        if 'transfer-encoding' in headers or 'expect' in headers:
            raise RequestError()
        length = headers.get('content-length', '0')
        if not length.isascii() or not length.isdecimal() or len(length) > 8:
            raise RequestError()
        length = int(length)
        if length > MAX_BODY:
            raise RequestError(413)
        if len(body) > length:
            raise RequestError()
        while len(body) < length:
            body += receive(length - len(body))
        return method, target, headers, body

    def _serve(self, connection, control):
        try:
            method, target, headers, body = self._read(connection)
            status, payload, mime = self._control(method, target, headers, body) if control else self._provider(method, target, headers, body)
            if status is None:  # Acceptance was recorded before deliberately losing the response.
                return
            self._reply(connection, status, payload, mime)
            self._count('responses')
        except (RequestError, ValueError, TypeError, UnicodeError, RecursionError) as error:
            self._count('rejected')
            try:
                self._reply(connection, getattr(error, 'status', 400), {'error': 'FIXTURE_REQUEST_REJECTED'})
            except OSError:
                pass
        except (OSError, TimeoutError):
            self._count('transport_closed')
        finally:
            with self._lock:
                self._connections.discard(connection)
            connection.close()
            self._slots.release()

    @staticmethod
    def _reply(connection, status, payload, mime='application/json'):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode()
        connection.settimeout(.5)
        connection.sendall(f'HTTP/1.1 {status} Fixture\r\nContent-Type: {mime}\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n'.encode() + data)

    @staticmethod
    def _json(headers, body):
        if headers.get('content-type', '').split(';')[0] != 'application/json':
            raise RequestError(415)
        payload = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(RequestError()))
        if not isinstance(payload, dict):
            raise RequestError()
        return payload

    def _refresh(self):
        for job in self._jobs.values():
            if job['state'] == 'held' and time.monotonic() >= job['deadline']:
                job['state'] = 'expired'

    def receipt(self):
        with self._lock:
            self._refresh()
            return {'counts': dict(self._counts), 'jobs': [
                {k: v for k, v in job.items() if k != 'deadline'} for job in self._jobs.values()],
                'uploads': list(self._uploads.values()), 'model_execution': False,
                'application_exactly_once': 'NOT_TESTED'}

    def _control(self, method, target, headers, body):
        if not secrets.compare_digest(headers.get('authorization', ''), 'Bearer ' + self.control_token):
            raise RequestError(403)
        if method == 'GET' and target == '/receipt':
            return 200, self.receipt(), 'application/json'
        if method != 'POST' or target not in ('/plan', '/release'):
            raise RequestError(404)
        payload = self._json(headers, body)
        with self._lock:
            self._refresh()
            if target == '/plan':
                mode = payload.get('mode')
                hold, silence = payload.get('hold_seconds', 0), payload.get('silence_seconds', .5)
                if (mode not in ('complete', 'hold', 'disconnect', 'silence')
                        or type(hold) not in (int, float) or not math.isfinite(hold) or not 0 <= hold <= MAX_HOLD
                        or type(silence) not in (int, float) or not math.isfinite(silence) or not 0 < silence <= MAX_SILENCE
                        or mode == 'hold' and hold == 0 or self._next is not None):
                    raise RequestError(409)
                self._next = (mode, hold, silence)
                return 200, {'planned': mode}, 'application/json'
            job = self._jobs.get(payload.get('prompt_id'))
            if job is None or job['state'] != 'held':
                raise RequestError(409)
            job['state'] = 'completed'
            return 200, {'prompt_id': job['prompt_id'], 'state': job['state']}, 'application/json'

    def _submit(self, headers, body):
        payload = self._json(headers, body)
        if (set(payload) != {'prompt', 'client_id', 'extra_data'} or not isinstance(payload['prompt'], dict)
                or not 1 <= len(payload['prompt']) <= 128 or not isinstance(payload['client_id'], str)
                or not payload['client_id'].startswith('onenode-backend-') or len(payload['client_id']) > 200
                or payload['extra_data'] != {'enable_previews': True}):
            raise RequestError()
        with self._lock:
            if len(self._jobs) >= MAX_JOBS:
                raise RequestError(429)
            mode, hold, silence = self._next or ('complete', 0, .5)
            self._next = None
            prompt_id = str(uuid.uuid4())
            self._jobs[prompt_id] = {'prompt_id': prompt_id, 'state': 'held' if hold else 'completed',
                'mode': mode, 'body_sha256': hashlib.sha256(body).hexdigest(),
                'client_sha256': hashlib.sha256(payload['client_id'].encode()).hexdigest(),
                'deadline': time.monotonic() + hold}
            self._counts['accepted'] = self._counts.get('accepted', 0) + 1
        if mode == 'silence':
            self._stop.wait(silence)
        if mode in ('silence', 'disconnect'):
            self._count('response_lost')
            return None, b'', 'application/json'
        return 200, {'prompt_id': prompt_id, 'number': len(self._jobs), 'node_errors': {}}, 'application/json'

    def _upload(self, headers, body):
        content_type = headers.get('content-type', '')
        if not content_type.startswith('multipart/form-data;'):
            raise RequestError(415)
        message = BytesParser(policy=default).parsebytes(('Content-Type: ' + content_type + '\r\n\r\n').encode())
        boundary = message.get_boundary()
        if not boundary or not boundary.isascii() or not 1 <= len(boundary) <= 70:
            raise RequestError()
        parts = body.split(b'--' + boundary.encode())
        if len(parts) != 5 or parts[0] != b'' or parts[-1] != b'--\r\n':
            raise RequestError()
        values = {}
        for raw in parts[1:-1]:
            if not raw.startswith(b'\r\n') or not raw.endswith(b'\r\n'):
                raise RequestError()
            part_headers, value = raw[2:-2].split(b'\r\n\r\n', 1)
            if len(part_headers) > 2048:
                raise RequestError(431)
            part = BytesParser(policy=default).parsebytes(part_headers + b'\r\n\r\n')
            name = part.get_param('name', header='content-disposition')
            if (name in values or name not in ('image', 'overwrite', 'type')
                    or part.get_content_maintype() == 'multipart' or part.get('Content-Transfer-Encoding')):
                raise RequestError()
            values[name] = value
            if name == 'image' and part.get_content_type() != 'image/png':
                raise RequestError(415)
        if values.get('overwrite') != b'true' or values.get('type') != b'input' or not values.get('image', b'').startswith(b'\x89PNG\r\n\x1a\n'):
            raise RequestError()
        with self._lock:
            if len(self._uploads) >= MAX_JOBS:
                raise RequestError(429)
            name = str(uuid.uuid4()) + '.png'
            self._uploads[name] = {'name': name, 'sha256': hashlib.sha256(values['image']).hexdigest(), 'bytes': len(values['image'])}
        return 200, {'name': name, 'subfolder': '', 'type': 'input'}, 'application/json'

    def _provider(self, method, target, headers, body):
        parsed = urlsplit(target)
        if method == 'POST':
            if target == '/prompt':
                return self._submit(headers, body)
            if target == '/upload/image':
                return self._upload(headers, body)
            if target in ('/interrupt', '/free'):
                with self._lock:
                    self._refresh()
                    if target == '/interrupt':
                        for job in self._jobs.values():
                            if job['state'] == 'held':
                                job['state'] = 'interrupted'
                    self._counts[target[1:]] = self._counts.get(target[1:], 0) + 1
                return 200, {}, 'application/json'
        if method == 'GET' and not parsed.query:
            if target == '/object_info':
                return 200, {'FluxKleinOneNode': {}}, 'application/json'
            if target == '/flux_klein/models':
                return 200, MODELS, 'application/json'
            if target == '/flux_klein/config':
                return 200, {}, 'application/json'
            if target in ('/flux_klein/workflow_t2i', '/flux_klein/workflow_edit'):
                return 200, workflow(), 'application/json'
            if target.startswith('/history/'):
                prompt_id = target.removeprefix('/history/')
                with self._lock:
                    self._refresh()
                    job = self._jobs.get(prompt_id)
                    if job and job['state'] == 'completed':
                        return 200, {prompt_id: {'outputs': {'FK:86': {'images': [
                            {'filename': prompt_id + '.png', 'subfolder': '', 'type': 'output'}]}}}}, 'application/json'
                return 200, {}, 'application/json'
        if method == 'GET' and parsed.path == '/view':
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=3)
            if set(query) != {'filename', 'subfolder', 'type'} or any(len(v) != 1 for v in query.values()):
                raise RequestError()
            with self._lock:
                self._refresh()
                job = self._jobs.get(query['filename'][0].removesuffix('.png'))
                if (job and job['state'] == 'completed' and query['filename'] == [job['prompt_id'] + '.png']
                        and query['subfolder'] == [''] and query['type'] == ['output']):
                    return 200, PNG, 'image/png'
        raise RequestError(404)
