"""Linux Docker build + real HTTP/mTLS lifecycle smoke test (not a pytest mock).

Run: python tests/container_smoke.py
Uses an isolated build context, synthetic secret canaries and short-lived PKI.
Never edits deployment files in the checkout or requires a real model/database.
"""
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

REPO = Path(__file__).resolve().parents[1]
CANARY = 'BUILD_SECRET_CANARY_MUST_NOT_SHIP'
BASE_PATH = '/rest/v1/registry-center'
CARD = dict(name='SmokeAgent', provider={'organization': 'SmokeOrg', 'url': 'https://example.org'},
            description='Container smoke test', version='1.0.0', capabilities={'streaming': False},
            defaultInputModes=['text/plain'], defaultOutputModes=['text/plain'],
            skills=[{'id': 'smoke', 'name': 'Smoke', 'description': 'Test', 'tags': []}])


def command(*args, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=600)
    if check and result.returncode:
        raise RuntimeError(f'{args[0]} command failed:\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}')
    return result


def build_context(root):
    context = root / 'context'
    context.mkdir()
    # Copy only tracked source, never the dirty local config/key material.
    sensitive = {'etc/conf/server.conf', 'etc/conf/persistence.conf',
                 'etc/conf/integration_credentials.conf', 'etc/config/models.yaml',
                 'common/config/models.yaml', 'common/config/llm_config.json'}
    paths = command('git', '-C', str(REPO), 'ls-files', '-z').stdout.split('\0')
    for name in filter(None, paths):
        path = Path(name)
        if (name in sensitive or name.startswith(('etc/ssl/', 'etc/sign_cert/', 'etc/sign_verify/'))
                or path.name.startswith('.env') or path.suffix in ('.pem', '.key', '.cer', '.p12', '.pfx')):
            continue
        destination = context / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / path, destination)
    canaries = sensitive | {'etc/ssl/server_key.pem', 'etc/sign_cert/private.pem',
                            'etc/sign_verify/jwks/canary.json', 'etc/conf/cipher.key', '.env',
                            'common/util/auth.local.json', 'common/config/.env',
                            'registry-center-web/node_modules/canary.txt', 'reviews/canary.txt'}
    for name in canaries:
        path = context / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CANARY, encoding='utf-8')
    # Force a Windows working-copy entrypoint, proving the Dockerfile repairs it.
    script = context / 'bin/entrypoint.sh'
    script.write_bytes(script.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    return context


def make_pki(root):
    pki = root / 'pki'
    pki.mkdir(mode=0o700)
    command('openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-sha256', '-days', '1',
            '-subj', '/CN=SmokeCA', '-addext', 'basicConstraints=critical,CA:TRUE',
            '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
            '-keyout', str(pki / 'ca.key'), '-out', str(pki / 'trust.cer'))
    for name, server in [('server', True), ('vendor-a', False), ('vendor-b', False)]:
        key, csr, cert = pki / (name + '_key.pem'), pki / (name + '.csr'), pki / (name + '.cer')
        args = ['openssl', 'req', '-new', '-newkey', 'rsa:3072', '-sha256', '-subj', '/CN=' + name,
                '-keyout', str(key), '-out', str(csr)]
        args += ['-passout', 'pass:Smoke#2026'] if server else ['-nodes']
        command(*args)
        ext = pki / (name + '.ext')
        ext.write_text('basicConstraints=critical,CA:FALSE\nextendedKeyUsage=' +
                       ('serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n' if server else 'clientAuth\n'))
        command('openssl', 'x509', '-req', '-in', str(csr), '-CA', str(pki / 'trust.cer'),
                '-CAkey', str(pki / 'ca.key'), '-CAcreateserial', '-days', '1', '-sha256',
                '-extfile', str(ext), '-out', str(cert))
    (pki / 'cert_pwd').write_text('Smoke#2026', encoding='utf-8')
    for file in pki.iterdir():
        file.chmod(0o600)
    return pki


def http(base, method='GET', path='/agent-cards', body=None, context=None, headers=None):
    handlers = [ProxyHandler({})]
    if context:
        handlers.append(HTTPSHandler(context=context))
    data = json.dumps(body).encode() if body is not None else None
    request = Request(base + BASE_PATH + path, data=data, method=method,
                      headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with build_opener(*handlers).open(request, timeout=5) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def assert_status(expected, *args, **kwargs):
    status, body = http(*args, **kwargs)
    assert status == expected, (expected, status, body[:400])


def client_context(pki, name=None):
    context = ssl.create_default_context(cafile=str(pki / 'trust.cer'))
    if name:
        context.load_cert_chain(str(pki / (name + '.cer')), str(pki / (name + '_key.pem')))
    return context


def wait_ready(container, base, context=None):
    deadline = time.monotonic() + 60
    last_probe = None
    while time.monotonic() < deadline:
        if command('docker', 'inspect', '-f', '{{.State.Running}}', container).stdout.strip() != 'true':
            raise RuntimeError(command('docker', 'logs', container).stdout)
        try:
            status = http(base, context=context)[0]
            if status == 200:
                return
            last_probe = 'HTTP ' + str(status)
        except (URLError, OSError) as error:
            last_probe = repr(error)
        time.sleep(0.25)
    logs = command('docker', 'logs', container).stdout[-2000:]
    raise RuntimeError('Container service readiness timeout; last probe: '
                       + str(last_probe) + '\n' + logs)


def run():
    if os.name == 'nt' or not shutil.which('docker'):
        raise SystemExit('This smoke test requires a Linux Docker daemon (CI runs it on Ubuntu).')
    image = f'registry-center-smoke:{os.getpid()}'
    containers = []
    # Storage/models/signature services are independent of the packaging test.
    common = ['-e', 'PERSISTENCE_MODE=file', '-e', 'REGISTRY_AGENT_APPROVAL_ENABLED=false',
              '-e', 'REGISTRY_REGISTRY_SIGN_ENABLED=false', '-e', 'REGISTRY_SIGNATURE_VALIDATION_ENABLED=false']
    development = common + ['-e', 'REGISTRY_ENABLE_HTTPS=false', '-e', 'REGISTRY_OWNER_ISOLATION_ENABLED=false']
    with tempfile.TemporaryDirectory(prefix='registry-container-smoke-') as temp:
        root = Path(temp)
        try:
            context = build_context(root)
            command('docker', 'build', '--tag', image, str(context))
            inspect = '''from pathlib import Path
root = Path('/opt/registry-center')
assert not (root/'registry-center-web').exists()
assert not any((root/'etc/ssl').iterdir())
assert not (root/'etc/conf/cipher.key').exists()
for file in root.rglob('*'):
    if file.is_file():
        assert b'BUILD_SECRET_CANARY_MUST_NOT_SHIP' not in file.read_bytes(), str(file)
assert b'\\r' not in (root/'bin/entrypoint.sh').read_bytes()
'''
            command('docker', 'run', '--rm', '--entrypoint', 'python', image, '-c', inspect)
            command('docker', 'run', '--rm', *development, image, 'init')
            bad = command('docker', 'run', '--rm', image, 'serve', '--port', '9090', check=False)
            assert bad.returncode == 2 and 'accepts no arguments' in bad.stderr
            bad = command('docker', 'run', '--rm', '-e', 'REGISTRY_ENABLE_HTTPS=false', image, check=False)
            assert bad.returncode != 0 and 'enable_https=false' in (bad.stdout + bad.stderr)

            def start(extra, secure=False, pki=None):
                container = command('docker', 'run', '-d', '-p', '127.0.0.1::9090',
                                    '-e', 'PORT=9090', '-e', 'REGISTRY_PORT=8080', *extra, image).stdout.strip()
                containers.append(container)
                mapping = command('docker', 'port', container, '9090/tcp').stdout.strip()
                base = ('https' if secure else 'http') + '://' + mapping
                wait_ready(container, base, client_context(pki, 'vendor-a') if secure else None)
                command('docker', 'exec', container, 'python', '-m', 'agent_registry.healthcheck')
                return container, base

            container, base = start(development)
            assert_status(201, base, 'POST', body={'agentCards': [CARD]})
            assert_status(200, base, 'GET', '/agent-cards/SmokeOrg/SmokeAgent')
            assert json.loads(http(base, path='/agent-cards/SmokeOrg/SmokeAgent')[1])['agentCards'][0]['name'] == 'SmokeAgent'
            assert_status(200, base, 'PUT', '/agent-cards/SmokeOrg/SmokeAgent', body={'agentCards': [dict(CARD, description='Updated')]})
            assert json.loads(http(base, path='/agent-cards/SmokeOrg/SmokeAgent')[1])['agentCards'][0]['description'] == 'Updated'
            assert_status(200, base, 'DELETE', '/agent-cards/SmokeOrg/SmokeAgent')
            status, body = http(base, path='/agent-cards/SmokeOrg/SmokeAgent')
            assert status == 200 and json.loads(body)['agentCards'] == []

            pki = make_pki(root)
            mounted_pki = root / 'mounted-pki'
            shutil.copytree(pki, mounted_pki)
            # Read-only mount is owned/readable by the fixed application UID.
            command('docker', 'run', '--rm', '--user', '0', '--entrypoint', 'chown',
                    '-v', f'{mounted_pki}:/fixtures', image, '-R', '10001:10001', '/fixtures')
            secure = common + ['-v', f'{mounted_pki}:/opt/registry-center/etc/ssl:ro',
                               '-e', 'REGISTRY_OWNER__VALIDATION__MODE=strict',
                               '-e', 'REGISTRY_HEALTHCHECK_CLIENT_CERT=etc/ssl/vendor-a.cer',
                               '-e', 'REGISTRY_HEALTHCHECK_CLIENT_KEY=etc/ssl/vendor-a_key.pem']
            command('docker', 'run', '--rm', *secure, image, 'init')
            container, base = start(secure, True, pki)
            owner, other = client_context(pki, 'vendor-a'), client_context(pki, 'vendor-b')
            try:
                http(base, context=client_context(pki))
            except (URLError, OSError):
                pass
            else:
                raise AssertionError('mTLS accepted a client without a certificate')
            assert_status(201, base, 'POST', body={'agentCards': [CARD]}, context=owner)
            assert_status(403, base, 'PUT', '/agent-cards/SmokeOrg/SmokeAgent', body={'agentCards': [CARD]},
                          context=other, headers={'X-SSL-Client-DN': 'CN=vendor-a'})
            assert_status(200, base, 'PUT', '/agent-cards/SmokeOrg/SmokeAgent', body={'agentCards': [CARD]}, context=owner)
            assert_status(200, base, 'DELETE', '/agent-cards/SmokeOrg/SmokeAgent', context=owner)
            print('PASS: secret-free image, CRLF repair, init/argv, PORT, HTTP CRUD, read-only TLS, mTLS owner isolation, health probes')
        finally:
            for container in containers:
                logs = command('docker', 'logs', container, check=False)
                print(logs.stdout[-3000:], logs.stderr[-3000:])
                command('docker', 'rm', '-f', container, check=False)
            # Restore only the temporary mount's host ownership before cleanup.
            if (root / 'mounted-pki').exists():
                command('docker', 'run', '--rm', '--user', '0', '--entrypoint', 'chown',
                        '-v', f'{root / "mounted-pki"}:/fixtures', image,
                        '-R', f'{os.getuid()}:{os.getgid()}', '/fixtures', check=False)
            command('docker', 'image', 'rm', image, check=False)


if __name__ == '__main__':
    run()
