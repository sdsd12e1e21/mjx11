"""Local-first game gateway. PowerContext is the only history storage."""
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PC_URL = os.environ.get('POWERCONTEXT_URL', 'http://127.0.0.1:8000').rstrip('/')
PC_TOKEN = os.environ.get('POWERCONTEXT_TOKEN', '')
TOKEN = os.environ.get('GATEWAY_TOKEN', '')
NAMESPACE = os.environ.get('GAME_NAMESPACE', 'grudge-shop-v1')

def pc_post(path, payload):
    headers = {'Content-Type': 'application/json'}
    if PC_TOKEN:
        headers['Authorization'] = 'Bearer ' + PC_TOKEN
    req = Request(PC_URL + path, json.dumps(payload, ensure_ascii=False).encode(), headers, method='POST')
    with urlopen(req, timeout=25) as response:
        return json.load(response)

def scope_for(player):
    # Only authenticated application callers may supply player IDs.
    # Dify DSL binds this to sys.user_id, never to LLM output or user text.
    key = hashlib.sha256((NAMESPACE + '\0' + player).encode()).hexdigest()
    return pc_post('/v1/scopes', {'title': '记仇杂货铺玩家', 'summary': '虚构游戏互动',
                                 'idempotency_key': 'grudge-shop-' + key})['scope_id']

def recall(player):
    scope = scope_for(player)
    data = pc_post('/v1/context/prepare', {'scope_id': scope, 'query': '杂货铺', 'max_bytes': 6000})
    return {'scope_id': scope, 'status': data['status'], 'content': data.get('content'), 'prepared': data}

def remember(player, query, reply):
    scope = scope_for(player)
    text = '杂货铺 游戏记录\n玩家实际行动：' + query + '\n店主虚构回复：' + reply
    if len(text.encode()) > 8000:
        raise ValueError('本轮记忆超过8000字节，请缩短输入或模型输出')
    saved = pc_post('/v1/memory/remember', {'scope_id': scope, 'kind': 'game_event',
                                         'text': text, 'reason': '玩家参与已说明会保存互动的虚构游戏'})
    if not saved.get('records'):
        raise RuntimeError('PowerContext did not return write evidence')
    return {'scope_id': scope, 'records': saved['records']}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not put game content, headers or credentials in access logs.

    def respond(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != '/health':
            return self.respond(404, {'error': 'not_found'})
        self.respond(200, {'service': 'grudge-shop-gateway', 'storage': 'PowerContext', 'status': 'live'})

    def do_POST(self):
        auth = self.headers.get('Authorization', '')
        if not TOKEN or not hmac.compare_digest(auth, 'Bearer ' + TOKEN):
            return self.respond(401, {'error': 'unauthorized'})
        if self.path not in ('/recall', '/remember'):
            return self.respond(404, {'error': 'not_found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 20000:
                return self.respond(413, {'error': 'invalid_body_size'})
            data = json.loads(self.rfile.read(length))
            player = data.get('player_id')
            if not isinstance(player, str) or not 1 <= len(player) <= 256:
                raise ValueError('player_id must contain 1-256 characters')
            query = data.get('query', '')
            if not isinstance(query, str) or not query.strip() or len(query) > 1200:
                raise ValueError('query must contain 1-1200 characters')
            if self.path == '/recall':
                result = recall(player)
            else:
                reply = data.get('reply')
                if not isinstance(reply, str) or not reply.strip():
                    raise ValueError('reply is required')
                result = remember(player, query, reply)
            self.respond(200, result)
        except (ValueError, TypeError, UnicodeError):
            self.respond(400, {'error': 'invalid_input'})
        except (HTTPError, URLError, TimeoutError, OSError):
            self.respond(502, {'error': 'powercontext_unavailable'})
        except (KeyError, RuntimeError):
            self.respond(502, {'error': 'powercontext_contract_error'})

if __name__ == '__main__':
    if not TOKEN or TOKEN == 'REPLACE_WITH_GATEWAY_TOKEN':
        raise SystemExit('Set GATEWAY_TOKEN to a non-placeholder secret before starting.')
    address = os.environ.get('GATEWAY_HOST', '127.0.0.1')
    port = int(os.environ.get('GATEWAY_PORT', '8765'))
    print(f'Game gateway listening on {address}:{port}', flush=True)
    ThreadingHTTPServer((address, port), Handler).serve_forever()
