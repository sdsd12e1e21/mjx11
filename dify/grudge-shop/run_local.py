"""Start the delivered PowerContext + gateway from a fresh, persistent directory."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
OPENER = build_opener(ProxyHandler({}))


def private_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def stop_child(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name != 'nt':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def wait_ready(process, url, timeout, log_path):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Service exited with code {process.returncode}. See {log_path}')
        try:
            with OPENER.open(url, timeout=min(2, max(.1, deadline - time.monotonic()))) as response:
                data = json.load(response)
                if response.status == 200 and data.get('status') in ('ok', 'ready'):
                    return
        except (OSError, ValueError, AttributeError):
            pass
        time.sleep(.25)
    raise RuntimeError(f'Service readiness timed out after {timeout}s. See {log_path}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=ROOT / '.runtime')
    parser.add_argument('--pc-port', type=int, default=8000)
    parser.add_argument('--gateway-port', type=int, default=8765)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--check', action='store_true',
                        help='Verify real memory, or restore the previous smoke test, then stop both services.')
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.pc_port == args.gateway_port:
        parser.error('Use a positive timeout and two different ports.')
    if not all(1 <= p <= 65535 for p in (args.pc_port, args.gateway_port)):
        parser.error('Ports must be between 1 and 65535.')
    try:
        version = importlib.metadata.version('powercontext')
    except importlib.metadata.PackageNotFoundError:
        parser.error('Install dependencies first: python -m pip install -r requirements.txt')
    if version != '1.5.0':
        parser.error(f'Expected PowerContext 1.5.0, found {version}; install requirements.txt in a new venv.')
    # Reserve both ports until checks finish; do not reuse or stop unrelated services.
    reservations = []
    try:
        for port in (args.pc_port, args.gateway_port):
            sock = socket.socket()
            reservations.append(sock)
            sock.bind(('127.0.0.1', port))
    except OSError:
        parser.error('A selected port is occupied. Choose --pc-port and --gateway-port; existing services are untouched.')
    finally:
        for sock in reservations:
            sock.close()
    state_dir = args.state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / 'connection.json'
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding='utf-8'))
        if (not isinstance(config, dict) or not isinstance(config.get('gateway_token'), str)
                or len(config['gateway_token']) < 24
                or not isinstance(config.get('game_namespace'), str) or not config['game_namespace']):
            parser.error('Invalid private connection.json; restore its original token or select a new state directory.')
    else:
        config = {'gateway_token': secrets.token_urlsafe(32),
                  'game_namespace': 'grudge-shop-' + secrets.token_hex(8)}
    config.update(powercontext_version=version,
                  powercontext_url=f'http://127.0.0.1:{args.pc_port}',
                  gateway_url=f'http://127.0.0.1:{args.gateway_port}')
    private_json(config_path, config)
    env = dict(os.environ, PYTHONUTF8='1', POWERCONTEXT_HOME=str(state_dir / 'pc-data'),
               POWERCONTEXT_URL=config['powercontext_url'], POWERCONTEXT_TOKEN='',
               GATEWAY_HOST='127.0.0.1', GATEWAY_PORT=str(args.gateway_port),
               GATEWAY_TOKEN=config['gateway_token'], GAME_NAMESPACE=config['game_namespace'])
    children = []
    logs = []
    try:
        services = [
            ('powercontext', [sys.executable, '-c', 'from powercontext.cli.app import main; main()',
                              'server', 'run', '--host', '127.0.0.1', '--port', str(args.pc_port), '--no-env-file'],
             config['powercontext_url'] + '/health/live'),
            ('gateway', [sys.executable, str(ROOT / 'gateway.py')], config['gateway_url'] + '/health'),
        ]
        for name, command, health in services:
            path = state_dir / (name + '.log')
            log = path.open('ab')
            logs.append(log)
            kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
            child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log, **kwargs)
            children.append(child)
            wait_ready(child, health, args.timeout, path)
            print(f'{name}: ready', flush=True)
        if args.check:
            import verify
            output = state_dir / 'smoke.json'
            command = ['--connection', str(config_path), '--output', str(output)]
            if output.exists():
                command += ['--resume', str(output)]
            verify.main(command)
            return 0
        print(f'Gateway: {config["gateway_url"]}\nPrivate connection file: {config_path}', flush=True)
        print('Keep this terminal running. Ctrl+C stops only these two child process trees.', flush=True)
        while True:
            if any(child.poll() is not None for child in children):
                raise RuntimeError(f'A service stopped. Inspect logs in {state_dir}')
            time.sleep(.5)
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(children):
            stop_child(child)
        for log in logs:
            log.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Startup failed: {error}', file=sys.stderr)
        raise SystemExit(1)
