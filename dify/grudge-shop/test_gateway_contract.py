"""Failure-contract regressions; real-service tests are run by verify.py."""
import io
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import gateway
from configure_dsl import render
from run_local import private_json, wait_ready


class ContractTest(unittest.TestCase):
    def test_failed_config_write_preserves_previous_valid_connection(self):
        scratch = Path(__file__).resolve().parent / '.runtime' / 'tests'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            path = Path(directory) / 'connection.json'
            previous = {'gateway_token': 'test-only-token-of-at-least-24-characters'}
            private_json(path, previous)
            with self.assertRaises(TypeError):
                private_json(path, {'unserializable': object()})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), previous)

    def test_unavailable_memory_is_not_presented_as_first_visit(self):
        for value in (None, [], {}, {'status': 'error'}, {'status': 'ready', 'content': None},
                      {'status': 'empty', 'content': 'unexpected'}):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                gateway.validate_context(value)

    def test_real_context_states_are_preserved(self):
        self.assertEqual(gateway.validate_context({'status': 'empty', 'content': None})['status'], 'empty')
        self.assertEqual(gateway.validate_context({'status': 'ready', 'content': 'history'})['content'], 'history')

    def test_invalid_write_evidence_is_rejected(self):
        for result in ({}, [], {'records': 'fake'}, {'records': [{'id': 'fake'}]},
                       {'records': [{'artifact': {'family': 'atomic-memory', 'artifact_id': 'x', 'revision': True}}]}):
            with self.subTest(result=result), self.assertRaises(RuntimeError):
                gateway.validate_records(result)

    def test_valid_artifact_ref_is_not_replaced(self):
        records = [{'artifact': {'family': 'atomic-memory', 'artifact_id': 'art_real', 'revision': 2}}]
        self.assertIs(gateway.validate_records({'records': records}), records)

    def test_bad_upstream_json_is_contract_failure(self):
        with patch.object(gateway.PC_OPENER, 'open', return_value=io.BytesIO(b'not json')):
            with self.assertRaises(RuntimeError):
                gateway.pc_post('/v1/context/prepare', {})

    def test_malformed_history_does_not_crash_game_rules(self):
        for payload in ([], {'items': None}, {'items': [None, 'bad', {'content': None}]}):
            wrapped = 'BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n' + json.dumps(payload) + '\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1'
            self.assertEqual(gateway.historical_actions(wrapped), [])

    def test_export_binds_connection_without_mutating_template(self):
        template = {'workflow': {'environment_variables': [{'name': 'GATEWAY_URL', 'value': 'placeholder'},
                                                          {'name': 'GATEWAY_TOKEN', 'value': 'placeholder'}]}}
        result = render(template, {'gateway_token': 'test-only-token-of-at-least-24-characters'}, 'https://game.example.com/')
        self.assertEqual(result['workflow']['environment_variables'][0]['value'], 'https://game.example.com')
        self.assertEqual(template['workflow']['environment_variables'][0]['value'], 'placeholder')
        for url in ('file:///tmp/file', 'https://user:password@example.com', 'https://example.com/?token=x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                render(template, {'gateway_token': 'test-only-token-of-at-least-24-characters'}, url)

    def test_startup_child_failure_is_reported_without_waiting(self):
        class Exited:
            returncode = 7
            def poll(self):
                return self.returncode
        with self.assertRaisesRegex(RuntimeError, 'code 7'):
            wait_ready(Exited(), 'http://127.0.0.1:1/health', 120, 'server.log')


if __name__ == '__main__':
    unittest.main()
