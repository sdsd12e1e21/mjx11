"""Exercise REAL gateway + PowerContext, then save a portable evidence file."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4

URL = os.environ.get('GATEWAY_URL', 'http://127.0.0.1:8765').rstrip('/')
TOKEN = os.environ['GATEWAY_TOKEN']

def post(path, payload, token=TOKEN):
    req = Request(URL + path, json.dumps(payload, ensure_ascii=False).encode(),
                  {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}, method='POST')
    with urlopen(req, timeout=40) as response:
        return json.load(response)

def main():
    player = 'validation-' + uuid4().hex
    other = player + '-other'
    first = post('/recall', {'player_id': player, 'query': '杂货铺'})
    assert first['status'] == 'empty', first
    action = '我把借口罐头偷偷换成了空气，标签写着量子罐头。'
    # Fixture only, deliberately not claiming this line came from a model.
    reply = '乌老板敲了敲空罐：好一个量子罐头！你的恶作剧我记下了。'
    saved = post('/remember', {'player_id': player, 'query': action, 'reply': reply})
    assert saved['records'], saved
    recovered = post('/recall', {'player_id': player, 'query': '我又来杂货铺了，你认识我吗？'})
    assert recovered['scope_id'] == first['scope_id']
    assert recovered['status'] == 'ready', recovered
    assert '量子罐头' in recovered['content'], recovered
    isolated = post('/recall', {'player_id': other, 'query': '杂货铺'})
    assert isolated['status'] == 'empty', isolated
    assert isolated['scope_id'] != first['scope_id']
    try:
        post('/recall', {'player_id': player, 'query': '杂货铺'}, 'wrong-token')
        raise AssertionError('unauthorized request unexpectedly accepted')
    except HTTPError as error:
        assert error.code == 401
    result = {'tested': 'real PowerContext HTTP memory roundtrip + player isolation + gateway auth',
              'model_reply_origin': 'fixed test fixture; no Dify/model end-to-end claim',
              'initial': first, 'write': saved, 'new_request_recall': recovered, 'other_player': isolated,
              'checks': {'empty_initial':True,'write_evidence':True,'recall_previous_action':True,
                         'player_isolation':True,'reject_bad_token':True}}
    output = Path(__file__).parent / 'evidence' / 'powercontext-roundtrip.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: real persistence, recall, player isolation, authentication; evidence/' + output.name)

if __name__ == '__main__':
    main()
