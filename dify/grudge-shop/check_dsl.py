"""Verify references and execute the DSL's code with adversarial JSON strings."""
import json
from pathlib import Path

root = Path(__file__).parent
dsl = json.loads((root / 'grudge-shop.yml').read_text(encoding='utf-8'))
graph = dsl['workflow']['graph']
nodes = {n['id']: n['data'] for n in graph['nodes']}
for edge in graph['edges']:
    assert edge['source'] in nodes and edge['target'] in nodes
for data in nodes.values():
    for var in data.get('variables', []):
        assert var['value_selector'][0] in nodes or var['value_selector'][0] == 'sys'

def run(id, **kw):
    ns = {}
    exec(nodes[id]['code'], ns)
    return ns['main'](**kw)

query = '把标签改成"量子罐头"\n\\再贴个🐦'
packed = run('pack', player='alice', query=query)
assert json.loads(packed['payload'])['query'] == query
assert run('history',body='{"content":null}',status=200)['history'].startswith('暂无历史')
reply = '记下了！'
packed = run('savepack', player='alice', query=query, reply=reply)
assert json.loads(packed['payload'])['reply'] == reply
assert run('verify',body='{"records":[{"id":"test"}]}',status=200,reply=reply)['answer'] == reply
assert run('verify',body='{"records":[{"id":"test"}],"finale":"win"}',status=200,reply=reply)['answer'] == 'win'
for fn, args in [('history',dict(body='{}',status=502)),('verify',dict(body='{}',status=200,reply=reply))]:
    try:
        run(fn, **args)
        raise AssertionError('failure must stop the workflow')
    except ValueError:
        pass
print('PASS: graph references, quote/newline/emoji encoding, recall parsing, fail-closed writes')
