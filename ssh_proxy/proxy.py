import functools
import json
import logging
import pathlib
import signal
import shutil
import socket
import subprocess
import tempfile
import threading
import uuid

from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import docker
import msgpack


log = logging.getLogger(__name__)


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
    host, port = sock.getsockname()
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
            data = sock.recv(1024)
            return
        finally:
            sock.close()


class Proxy:
    def __init__(self,
                 runtime_dir: str,
                 image_name: str,
                 client_name: str,
                 host: str,
                 root_ca_path: str,
                 keep_alive=1200,
                 ):
        """Docstring will be here..."""
        self._iot_client = AWSIoTMQTTClient(client_name, useWebsocket=True)
        self._iot_client.configureEndpoint(host, 443)
        self._iot_client.configureCredentials(root_ca_path)
        self._keep_alive = keep_alive

        self._stop = threading.Event()
        self._hendlers = {
        }

        self._runtime_dir = pathlib.Path(runtime_dir)
        self._docker = docker.from_env()
        self._image_name = image_name
        self._lock = threading.Lock()
        self._containers = {}

    def _start_iot_client(self):
        self._iot_client.connect(self._keep_alive)
        self._iot_client.subscribe('sshproxy', 1, self._iot_callback)

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

    def signal_handler(self, signum, frame):
        self._stop.set()

    @in_thread
    def _iot_callback(self, client, userdata, message):
        log.debug('Got message: %s', message.payload)
        job = json.loads(message.payload)
        job_id = uuid.UUID(job.pop('_id'))
        command = job.pop('command', '')

        handler = self._handlers.get(command)
        if handler is None:
            self._iot_client.publish(
                'sshproxy/missing',
                f'No handler for command "{command}"',
                0
            )
        handler(job_id, task)

    def _container_list(self, job_id, task):
        # TODO
        with self._lock:
            response = {
                container_id: {
                    key: value in container_data['info'].items()
                    if key in {'',}
                } for container_id, container_data in self._containers.items()
            }
        payload = json_dumps({'_id': job_id, 'result': response})
        self._iot_client.publish('sshproxy/success', payload, 0)

    def _container_info(self, job_id, task):
        # TODO
        container_id = task.pop('container_id', None)
        with self._lock:
            if container_id in self._containers:
                topic = 'sshproxy/success'
                response = self._containers[container_id]
            else:
                topic = 'sshproxy/error'
                response = {'msg': f'No container with id "{container_id}"'}
        payload = json_dumps({'_id': job_id, 'result': response})
        self._iot_client.publish(topic, payload, 0)

    def _container_run(self, job_id, task):
        with self._lock:
            if job_id in self._containers:
                # TODO
                return

            _tmp_dir = tempfile.TemporaryDirectory(
                dir=self._runtime_dir
            )
            tmp_dir = pathlib.Path(_tmp_dir.name)

            private_key_file = tmp_dir / 'rsa_key'
            public_key_file = tmp_dir / 'rsa_key.pub'
            subprocess.chekc_call([
                'ssh-keygen', '-f', private_key_file, '-t', 'rsa', '-N', ''
            ])
            private_key = private_key_file.read_text()

            docker_root = tmp_dir / 'root'
            docker_ssh = docker_root / '.ssh'
            docker_ssh.mkdir(mode=0o700, parents=True)

            shutil.copy(public_key_file, docker_ssh / 'authorized_keys')

            docker_ssh_port = get_free_port()
            connector_ssh_port = get_free_port()

            container = self._docker.containers.run(
                self._image_name,
                auto_remove=True,
                detach=True,
                mounts=[docker.types.Mount('/root', str(docker_root), type='bind')],
                ports={'22', docker_ssh_port, '2222': connector_ssh_port}
            )
            self._containers[job_id] = {'container': container}

            wait_for_port_opens(docker_ssh_port)
            

    def _container_stop(self, job_id, task):
        # TODO
        pass
