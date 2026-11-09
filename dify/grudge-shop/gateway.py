"""Local-first game gateway. PowerContext is the only history storage."""
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen
from urllib.parse import urlparse

PC_URL = os.environ.get('POWERCONTEXT_URL', 'http://127.0.0.1:8000').rstrip('/')
PC_TOKEN = os.environ.get('POWERCONTEXT_TOKEN', '')
TOKEN = os.environ.get('GATEWAY_TOKEN', '')
NAMESPACE = os.environ.get('GAME_NAMESPACE', 'grudge-shop-v1')
PC_TIMEOUT = 15
# Loopback traffic must not accidentally go through a machine's HTTP proxy.
PC_OPENER = (build_opener(ProxyHandler({})) if urlparse(PC_URL).hostname in
             ('127.0.0.1', 'localhost', '::1') else build_opener())

def validate_context(data):
    if not isinstance(data, dict) or data.get('status') not in ('empty', 'ready'):
        raise RuntimeError('PowerContext returned an invalid context status')
    content = data.get('content')
    if data['status'] == 'ready' and (not isinstance(content, str) or not content.strip()):
        raise RuntimeError('PowerContext returned ready without content')
    if data['status'] == 'empty' and content not in (None, ''):
        raise RuntimeError('PowerContext returned inconsistent empty content')
    return data

def validate_records(saved):
    records = saved.get('records') if isinstance(saved, dict) else None
    if not isinstance(records, list) or not records:
        raise RuntimeError('PowerContext did not return write evidence')
    for record in records:
        ref = record.get('artifact') if isinstance(record, dict) else None
        if (not isinstance(ref, dict) or ref.get('family') != 'atomic-memory'
                or not isinstance(ref.get('artifact_id'), str) or not ref['artifact_id']
                or type(ref.get('revision')) is not int or ref['revision'] < 1):
            raise RuntimeError('PowerContext returned an invalid ArtifactRef')
    return records

def pc_post(path, payload):
    headers = {'Content-Type': 'application/json'}
    if PC_TOKEN:
        headers['Authorization'] = 'Bearer ' + PC_TOKEN
    req = Request(PC_URL + path, json.dumps(payload, ensure_ascii=False).encode(), headers, method='POST')
    with PC_OPENER.open(req, timeout=PC_TIMEOUT) as response:
        try:
            data = json.load(response)
        except (ValueError, UnicodeError) as error:
            raise RuntimeError('PowerContext returned invalid JSON') from error
    if not isinstance(data, dict):
        raise RuntimeError('PowerContext returned a non-object response')
    return data

def scope_for(player):
    # Only authenticated application callers may supply player IDs.
    # Dify DSL binds this to sys.user_id, never to LLM output or user text.
    key = hashlib.sha256((NAMESPACE + '\0' + player).encode()).hexdigest()
    data = pc_post('/v1/scopes', {'title': '记仇杂货铺玩家', 'summary': '虚构游戏互动',
                                'idempotency_key': 'grudge-shop-' + key})
    if not isinstance(data.get('scope_id'), str) or not data['scope_id']:
        raise RuntimeError('PowerContext did not return a scope ID')
    return data['scope_id']

def recall(player):
    scope = scope_for(player)
    data = validate_context(pc_post('/v1/context/prepare', {'scope_id': scope, 'query': '杂货铺', 'max_bytes': 6000}))
    return {'scope_id': scope, 'status': data['status'], 'content': data.get('content'), 'prepared': data}

def remember(player, query, reply):
    scope = scope_for(player)
    previous = validate_context(pc_post('/v1/context/prepare', {'scope_id': scope, 'query': '杂货铺', 'max_bytes': 6000}))
    actions = historical_actions(previous.get('content') or '')
    finale = resolve_finale(actions, query)
    if finale:
        reply = finale
    text = '杂货铺 游戏记录\n玩家实际行动：' + query + '\n店主虚构回复：' + reply
    if len(text.encode()) > 8000:
        raise ValueError('本轮记忆超过8000字节，请缩短输入或模型输出')
    saved = pc_post('/v1/memory/remember', {'scope_id': scope, 'kind': 'game_event',
                                         'text': text, 'reason': '玩家参与已说明会保存互动的虚构游戏'})
    return {'scope_id': scope, 'records': validate_records(saved), 'finale': finale}

def historical_actions(content):
    """Inspect only player actions, not fictional NPC dialogue, for game rules."""
    begin = 'BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1'
    end = 'END_POWERCONTEXT_PREPARED_CONTEXT_V1'
    if begin not in content or end not in content:
        return []
    try:
        payload = json.loads(content.split(begin, 1)[1].split(end, 1)[0].strip())
        if not isinstance(payload, dict) or not isinstance(payload.get('items', []), list):
            return []
        actions = []
        for item in payload.get('items', []):
            if not isinstance(item, dict):
                continue
            text = item.get('content', '')
            if isinstance(text, str) and '玩家实际行动：' in text and '\n店主虚构回复：' in text:
                actions.append(text.split('玩家实际行动：', 1)[1].split('\n店主虚构回复：', 1)[0])
        return actions
    except (ValueError, TypeError, KeyError):
        return []

def resolve_finale(actions, query):
    # Small, explicit game rules bound the ending independently of model sampling.
    apologized = any(any(word in action for word in ('道歉', '对不起', '补偿')) for action in actions)
    helping = any(word in query for word in ('我补回', '我归还', '整理好货架', '诚实宣传'))
    if apologized and helping:
        return ('乌老板看着补回的罐头和整齐的货架，终于从小本本里取出一枚徽章，别在你的衣领上。\n'
                '“空气罐头那笔账我还记得，不过你后来的诚意，我也记下了。”\n'
                '【店主态度：熟客】\n【友好结局·本店最不放心的熟客】\n'
                '你获得了熟客徽章！\n1. 试用后悔怀表。\n2. 给诚实雨伞设计广告。\n3. 下次再来探店。')
    pranks = sum(any(word in action for word in ('恶作剧', '换成空气', '偷偷换')) for action in actions)
    if pranks >= 2 and any(word in query for word in ('继续恶作剧', '再次恶作剧', '又偷偷换')):
        return ('乌老板翻开密密麻麻的小本本，把你的名字写进“熟悉的麻烦”一栏。\n'
                '“你每次来，我都得先检查罐头！”\n【店主态度：记仇】\n'
                '【黑名单结局·本店最熟悉的麻烦】\n1. 认真道歉。\n2. 补回罐头。\n3. 下次再来。')
    return ''

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
        try:
            headers = {'Authorization': 'Bearer ' + PC_TOKEN} if PC_TOKEN else {}
            with PC_OPENER.open(Request(PC_URL + '/health/live', headers=headers), timeout=3) as response:
                healthy = response.status == 200 and json.load(response).get('status') == 'ok'
            if not healthy:
                raise RuntimeError('PowerContext is not ready')
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, AttributeError, RuntimeError):
            return self.respond(503, {'service': 'grudge-shop-gateway', 'status': 'not_ready',
                                      'powercontext': 'unavailable'})
        self.respond(200, {'service': 'grudge-shop-gateway', 'storage': 'PowerContext', 'status': 'ready'})

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
            if not isinstance(data, dict):
                raise ValueError('request body must be an object')
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
