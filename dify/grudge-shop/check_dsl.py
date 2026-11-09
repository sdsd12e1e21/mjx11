"""Verify references and execute the DSL's code with adversarial JSON strings."""
import json
from pathlib import Path

root = Path(__file__).parent
dsl = json.loads((root / 'grudge-shop.yml').read_text(encoding='utf-8'))
assert dsl['version'] == '0.4.0'
graph = dsl['workflow']['graph']
nodes = {n['id']: n['data'] for n in graph['nodes']}
assert nodes['llm']['prompt_template'][0]['text'].strip() == (root / 'prompt.txt').read_text(encoding='utf-8').strip()
for node_id in ('pack', 'history', 'savepack', 'verify'):
    assert nodes[node_id]['code'].strip() == (root / 'workflow_code' / (node_id + '.py')).read_text(encoding='utf-8').strip()
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
assert run('history',body='{"status":"empty","content":null}',status=200)['history'].startswith('暂无历史')
assert run('history',body='{"status":"ready","content":"真实召回"}',status=200)['history'] == '真实召回'
reply = '记下了！'
packed = run('savepack', player='alice', query=query, reply=reply)
assert json.loads(packed['payload'])['reply'] == reply
receipt = {'scope_id':'scp_test','records':[{'artifact':{'family':'atomic-memory','artifact_id':'art_test','revision':1}}]}
assert run('verify',body=json.dumps(receipt),status=200,reply=reply)['answer'] == reply
assert run('verify',body=json.dumps(dict(receipt,finale='win')),status=200,reply=reply)['answer'] == 'win'
failures = [('history',dict(body='{}',status=502)),('verify',dict(body='{}',status=200,reply=reply))]
failures += [('history',dict(body=json.dumps(body),status=200)) for body in ({}, [], {'status':'error'}, {'status':'ready','content':None}, {'status':'empty','content':'unexpected'})]
failures += [('verify',dict(body=json.dumps(body),status=200,reply=reply)) for body in ([], {'records':[{'id':'fake'}]}, dict(receipt,records=[{'artifact':{'family':'atomic-memory','artifact_id':'art_bad','revision':True}}]))]
for fn, args in failures:
    try:
        run(fn, **args)
        raise AssertionError('failure must stop the workflow')
    except ValueError:
        pass
print('PASS: DSL compatibility marker, synchronized code, graph references, JSON encoding, strict recall/write contracts')
