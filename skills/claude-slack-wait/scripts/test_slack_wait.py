import argparse
import unittest
from unittest import mock

import slack_wait as sw

ME = 'U_ME'
ROOT = '1730000000.123456'


def msg(ts, user, **extra):
    return {'ts': ts, 'author': {'user_id': user}, **extra}


class FindNew(unittest.TestCase):
    def test_others_after_baseline_only(self):
        messages = [msg('1729999900.000000', 'U_A'), msg(ROOT, ME), msg('1730000100.000000', ME), msg('1730000200.000000', 'U_A')]
        replies, _ = sw.find_new(messages, ME, ROOT, ROOT, [])
        self.assertEqual([m['ts'] for m in replies], ['1730000200.000000'])

    def test_bot_without_user_id_counts(self):
        replies, _ = sw.find_new([{'ts': '1730000200.000000', 'author': None}], ME, ROOT, ROOT, [])
        self.assertEqual(len(replies), 1)

    def test_reactions_on_linked_message_except_mine_and_seen(self):
        root = msg(ROOT, ME, reactions=[{'name': 'eyes', 'users': ['U_A', ME]}, {'name': '+1', 'users': ['U_A']}])
        other = msg('1730000100.000000', ME, reactions=[{'name': 'tada', 'users': ['U_A']}])
        _, reactions = sw.find_new([root, other], ME, ROOT, ROOT, ['eyes:U_A'])
        self.assertEqual(reactions, ['+1:U_A'])


class Wait(unittest.TestCase):
    def run_wait(self, results, hours=24, run_hours=None):
        clock = [0.0]
        calls = iter(results)

        def poll():
            item = next(calls)
            if isinstance(item, Exception):
                raise item
            return item

        return sw.wait(poll, 60, hours, run_hours, sleep=lambda s: clock.__setitem__(0, clock[0] + s), now=lambda: clock[0])

    def test_collects_until_quiet(self):
        one, two = (['a'], []), (['a', 'b'], [])
        self.assertEqual(self.run_wait([([], []), one, two, two]), (0, two))

    def test_busy_thread_is_capped(self):
        self.assertEqual(self.run_wait([(['a'] * n, []) for n in range(1, 9)])[1], (['a'] * sw.MAX_SETTLE_POLLS, []))

    def test_transient_failures_then_reply(self):
        self.assertEqual(self.run_wait([sw.SlackError('fetch failed')] * 9 + [(['a'], [])] * 2)[0], 0)

    def test_gives_up_after_repeated_failures(self):
        self.assertEqual(self.run_wait([sw.SlackError('fetch failed')] * 10), (2, 'fetch failed'))

    def test_auth_failure_is_immediate(self):
        self.assertEqual(self.run_wait([sw.SlackError('invalid_auth')]), (2, 'invalid_auth'))

    def test_timeout(self):
        self.assertEqual(self.run_wait([([], [])] * 10, hours=0.05), (3, None))

    def test_run_ends_before_background_limit(self):
        self.assertEqual(self.run_wait([([], [])] * 10, run_hours=0.05), (4, None))

    def test_answer_found_at_run_end_is_kept(self):
        self.assertEqual(self.run_wait([([], []), (['a'], []), (['a', 'b'], [])], run_hours=0.02), (0, (['a', 'b'], [])))


class Links(unittest.TestCase):
    def test_thread_reply_link(self):
        m = sw.LINK.match('https://acme.slack.com/archives/C0123456789/p1730000000123456?thread_ts=1729990000.000100&cid=C0123456789')
        self.assertEqual((m['workspace'], m['channel'], f"{m['sec']}.{m['usec']}"), ('https://acme.slack.com', 'C0123456789', ROOT))

    def test_rejects_other_hosts(self):
        self.assertIsNone(sw.LINK.match('https://evil.example/archives/C0123456789/p1730000000123456'))

    def test_rearm_keeps_state(self):
        args = argparse.Namespace(link='https://x.slack.com/archives/D1/p1730000000123456?a=1&b=2', conversation=True, seen=['eyes:U_A'])
        with mock.patch('sys.argv', ['slack_wait.py']):
            command = sw.rearm_command(args, [msg('1730000200.000000', 'U_A')], ['-1:U_B'], ROOT)
        self.assertIn("'https://x.slack.com/archives/D1/p1730000000123456?a=1&b=2'", command)
        self.assertIn('--after 1730000200.000000 --conversation --seen=eyes:U_A,-1:U_B', command)
        self.assertTrue(sw.rearm_command(args, [], [], ROOT, 21.5).endswith(f'--after {ROOT} --conversation --hours 21.50 --seen=eyes:U_A'))


class Fetch(unittest.TestCase):
    def test_conversation_merges_thread_and_history(self):
        pages = [{'messages': [msg(ROOT, ME)]}, {'messages': [msg('1730000200.000000', 'U_A'), msg(ROOT, ME)]}]
        with mock.patch.object(sw, 'slack', side_effect=pages) as call:
            messages, _ = sw.fetch('https://x.slack.com/archives/D1/p1730000000123456', True, ROOT)
        self.assertEqual([m['ts'] for m in messages], [ROOT, '1730000200.000000'])
        self.assertEqual(call.call_count, 2)


if __name__ == '__main__':
    unittest.main()
