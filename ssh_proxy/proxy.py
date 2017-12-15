import enum
import functools
import json
import logging
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zlib

from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import docker
import msgpack


log = logging.getLogger(__name__)


class Status(enum.Enum):
    Starting = enum.auto()
    Running = enum.auto()
    Stopping = enum.auto()


class Container:
    def __init__(self, tmp_dir, docker_client, image):
        self._real_tmp_dir = tempfile.TemporaryDirectory(dir=tmp_dir)
        self._tmp_dir = pathlib.Path(self._real_tmp_dir.name)

        self._pk_file = self._tmp_dir / 'rsa_key'
        subprocess.check_call([
            'ssh-keygen', '-f', self._pk_file, '-t', 'rsa', '-N', ''
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        self._bind_root = self._tmp_dir / 'root'
        auth_keys_file = self._bind_root / '.ssh' / 'authorized_keys'
        auth_keys_file.parent.mkdir(mode=0o700, parents=True)
        shutil.copy(self._pk_file.with_suffix('.pub'), auth_keys_file)

        self._docker = docker_client
        self._image = image

        self.docker_port = None
        self.server_port = None
        self.container = None

        self.lock = threading.Condition()
        self.status = Status.Starting

    def read_private_key(self):
        return self._pk_file.read_bytes()

    def start(self):
        self.docker_port = get_free_port()
        self.server_port = get_free_port()

        mount = docker.types.Mount('/root', str(self._bind_root), type='bind')

        self.container = self._docker.containers.run(
            self._image,
            auto_remove=True,
            detach=True,
            mounts=[mount],
            ports={'22': self.docker_port, '2222': self.server_port}
        )

    def wait_for_start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        while True:
            try:
                sock.connect(('127.0.0.1', self.docker_port))
            except ConnectionError:
                with self.lock:
                    if self.status == Status.want_stop:
                        return
                time.sleep(1)
            else:
                sock.recv(1024)
                return
            finally:
                sock.close()

    def want_stop(self):
        return self.status == Status.Stopping

    def destroy(self):
        self.container.stop()
        self._real_tmp_dir.cleanup()

    def info(self):
        return {
            'container_id': self.id,
            'docker_port': self.docker_port,
            'server_port': self.server_port,
        }

    @property
    def id(self):
        if self.container is None:
            return None
        return self.container.id


def in_thread(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        threading.Thread(target=func, args=args, kwargs=kwargs).start()
    return wrapper


def json_dumps(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def get_free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('', 0))
    _, port = sock.getsockname()
    sock.close()
    return port


def wait_for_port_opens(port):
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect(('127.0.0.1', port))
        except ConnectionError:
            time.sleep(1)
        else:
            sock.recv(1024)
            return
        finally:
            sock.close()


class Proxy:
    def __init__(self,
                 name: str,
                 host: str,
                 runtime_dir: str,
                 image: str,
                 iot_host: str,
                 root_ca_path: str,
                 cert_path: str,
                 key_path: str,
                 keep_alive=1200):
        """Docstring will be here..."""
        self._host = host

        self.name = name
        self._iot_client = AWSIoTMQTTClient(name)
        self._iot_client.configureEndpoint(iot_host, 8883)
        self._iot_client.configureCredentials(root_ca_path, key_path, cert_path)
        self._keep_alive = keep_alive

        self._stop = threading.Event()
        self._handlers = {
            'run': self._container_run,
            'stop': self._container_stop,
            'info': self._container_info,
            'list': self._container_list,
            'connect': self._send_connect,
        }

        self._runtime_dir = pathlib.Path(runtime_dir)
        self._docker = docker.from_env()

        try:
            image = self._docker.images.get(image)
        except docker.errors.ImageNotFound:
            print('Specified image not found')
            sys.exit(1)
        self._image = image
        self._lock = threading.Lock()
        self._containers = {}

    def _start_iot_client(self):
        self._iot_client.connect(self._keep_alive)
        self._iot_client.subscribe(
            f'ssh/proxy/{self.name}', 1, self._iot_callback
        )

    def _stop_iot_client(self):
        self._iot_client.disconnect()

    def run_forever(self):
        if not self._runtime_dir.is_dir():
            raise RuntimeError(
                f'Runtime dir "{self._runtime_dir}" does not exists'
            )
        self._start_iot_client()
        try:
            self._stop.wait()
        except:
            print('Got exception')
        else:
            print('No exception')
        self._stop_iot_client()

    def catch_signals(self):
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, _signum, _frame):
        self._stop.set()

    @in_thread
    def _iot_callback(self, _client, _userdata, message):
        log.info('Got message: %s', message.payload)
        try:
            job = json.loads(message.payload)
            job_id = uuid.UUID(job.pop('_id'))
            command = job.pop('command', '')
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            self._iot_client.publish(
                f'ssh/proxy/{self.name}/error',
                'Unable to parse message', 0
            )
            return

        handler = self._handlers.get(command)
        if handler is None:
            self._iot_client.publish(
                f'ssh/proxy/{self.name}/{job_id.hex}/error',
                f'No handler for command "{command}"', 1
            )
            return
        try:
            handler(job_id, job)
        except:
            self._iot_client.publish(
                f'ssh/proxy/{self.name}/{job_id.hex}/error',
                'An error occurred', 1
            )
            raise

    def _container_run(self, job_id, job):
        server = job.pop('server', None)
        container = Container(self._runtime_dir, self._docker, self._image)
        container.start()
        log.info('Container %s started', container.container.short_id)

        with self._lock:
            self._containers[container.id] = container

        container.wait_for_start()
        send_connect = server is not None
        with container.lock:
            if container.status == Status.Stopping:
                send_connect = False
            else:
                container.status = Status.Running

        self._iot_client.publish(
            f'ssh/proxy/{self.name}/{job_id.hex}/success',
            json_dumps({'type': 'started', 'data': container.info()}), 1
        )

        if send_connect:
            private_key = container.read_private_key()
            message = [
                job_id.bytes,
                1, # Client connect message
                [
                    private_key,
                    'root',
                    self._host,
                    container.docker_port,
                    2222
                ]
            ]
            payload = bytearray(zlib.compress(msgpack.dumps(message)))
            self._iot_client.publish(f'ssh/server/{server}', payload, 1)

        with container.lock:
            container.lock.wait_for(container.want_stop)

        log.info('Container %s stopping', container.container.short_id)
        id_ = container.id
        with self._lock:
            del self._containers[id_]
        container.destroy()

        self._iot_client.publish(
            f'ssh/proxy/{self.name}/{job_id.hex}/success',
            json_dumps({'type': 'stopped', 'data': {'container_id': id_}}), 1
        )

    def _container_stop(self, job_id, job):
        container_id = job.pop('container_id')
        with self._lock:
            container = self._containers.get(container_id)

        if container is None:
            self._iot_client.publish(
                f'ssh/proxy/{self.name}/{job_id.hex}/error',
                'Container does not exists', 1
            )
        else:
            with container.lock:
                container.status = Status.Stopping
                container.lock.notify()
            self._iot_client.publish(
                f'ssh/proxy/{self.name}/{job_id.hex}/success',
                'Ok', 1
            )

    def _container_info(self, job_id, job):
        container_id = job.pop('container_id')
        with self._lock:
            container = self._containers.get(container_id)

        if container is None:
            self._iot_client.publish(
                f'ssh/proxy/{self.name}/{job_id.hex}/error',
                'Container does not exists', 1
            )
        else:
            self._iot_client.publish(
                f'ssh/proxy/{self.name}/{job_id.hex}/success',
                json_dumps({'type': 'info', 'data': container.info()}), 1
            )

    def _container_list(self, job_id, job):
        with self._lock:
            data = {
                key: container.info()
                for key, container in self._containers.items()
            }

        self._iot_client.publish(
            f'ssh/proxy/{self.name}/{job_id.hex}/success',
            json_dumps({'type': 'list', 'data': data}), 1
        )

    def _send_connect(self, job_id, job):
        container_id = job.pop('container_id')
        server = job.pop('server')

        with self._lock:
            container = self._containers.get(container_id)

        if container is None:
            self._iot_client.publish(
                f'ssh/proxy/{self.name}/{job_id.hex}/error',
                'Container does not exits', 1
            )
        else:
            private_key = container.read_private_key()
            message = [
                job_id.bytes,
                1, # Client connect message
                [
                    private_key,
                    'root',
                    self._host,
                    container.docker_port,
                    2222
                ]
            ]
            payload = bytearray(zlib.compress(msgpack.dumps(message)))
            self._iot_client.publish(f'ssh/server/{server}', payload, 1)

            self._iot_client.publish(
                f'ssh/proxy/{self.name}/{job_id.hex}/success',
                'Connect sent', 1
            )
