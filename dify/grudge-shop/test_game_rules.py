import json
import unittest
from gateway import historical_actions, resolve_finale

class GameRulesTest(unittest.TestCase):
    def test_reward_requires_prior_apology_and_current_help(self):
        self.assertEqual(resolve_finale([], '我补回罐头'), '')
        self.assertEqual(resolve_finale(['我认真道歉'], '请给我徽章'), '')
        self.assertIn('友好结局', resolve_finale(['我认真道歉'], '我补回罐头'))

    def test_npc_dialogue_does_not_count_as_player_apology(self):
        item = {'content': '杂货铺 游戏记录\n玩家实际行动：我想看罐头\n店主虚构回复：请向我道歉并补偿'}
        content = 'BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n' + json.dumps({'items': [item]}) + '\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1'
        actions = historical_actions(content)
        self.assertEqual(actions, ['我想看罐头'])
        self.assertEqual(resolve_finale(actions, '我补回罐头'), '')

    def test_blacklist_needs_repeated_pranks(self):
        self.assertEqual(resolve_finale(['我恶作剧'], '继续恶作剧'), '')
        self.assertIn('黑名单结局', resolve_finale(['我恶作剧', '我偷偷换罐头'], '继续恶作剧'))

    def test_unavailable_or_truncated_history_does_not_invent_progress(self):
        self.assertEqual(historical_actions(''), [])
        self.assertEqual(historical_actions('BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n{broken\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1'), [])

if __name__ == '__main__':
    unittest.main()
