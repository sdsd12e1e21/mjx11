"""Create a local, credential-bearing DSL from the sanitized submitted template."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from run_local import private_json

ROOT = Path(__file__).resolve().parent


def render(template, connection, gateway_url):
    parsed = urlparse(gateway_url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Use a plain HTTP(S) gateway root URL, without credentials, query or fragment.')
    token = connection.get('gateway_token')
    if not isinstance(token, str) or len(token) < 24:
        raise ValueError('Missing or invalid gateway_token in private connection file.')
    dsl = json.loads(json.dumps(template))
    values = {'GATEWAY_URL': gateway_url.rstrip('/'), 'GATEWAY_TOKEN': token}
    for variable in dsl['workflow']['environment_variables']:
        if variable['name'] in values:
            variable['value'] = values[variable['name']]
    return dsl


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection', type=Path, default=ROOT / '.runtime/connection.json')
    parser.add_argument('--gateway-url', required=True,
                        help='HTTPS root reachable by Dify Cloud, or a reachable host address for self-hosted Dify.')
    args = parser.parse_args(argv)
    template = json.loads((ROOT / 'grudge-shop.yml').read_text(encoding='utf-8'))
    connection = json.loads(args.connection.read_text(encoding='utf-8'))
    result = render(template, connection, args.gateway_url)
    output = args.connection.resolve().parent / 'grudge-shop-configured.yml'
    private_json(output, result)
    print(f'Configured DSL: {output}')
    print('Contains a local gateway secret. Import into your Dify workspace; do not commit or share this file.')
    if urlparse(args.gateway_url).scheme != 'https' or urlparse(args.gateway_url).hostname in ('localhost', '127.0.0.1', '::1'):
        print('For Dify Cloud, replace this URL with a public HTTPS gateway; localhost is only for an appropriate self-hosted deployment.')


if __name__ == '__main__':
    main()
