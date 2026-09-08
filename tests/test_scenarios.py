"""Adversarial acceptance scenarios; all state and commands stay in temp directories."""
import copy
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
import seedbag_core as core


class ContinuityScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / '.seedbag').mkdir()
        self.ledger = self.root / '.seedbag' / 'ledger.json'
        self.ledger.write_text(json.dumps(dict(schema=1, seed_version='0.3.0',
                                              name='Adversarial trial', repository='', events=[])), encoding='utf-8')
        (self.root / 'input.txt').write_text('original input', encoding='utf-8')

    def apply(self, *operations):
        before = core.load(self.root)
        return core.apply(self.root, list(operations), before['revision'], before['digest'])

    def refuse_without_write(self, *operations):
        before = self.ledger.read_bytes()
        with self.assertRaises(core.Error):
            self.apply(*operations)
        self.assertEqual(before, self.ledger.read_bytes())

    def capture(self, ident='user1', origin='user'):
        self.apply(dict(op='capture.add', id=ident, text='Keep offline use.',
                        origin=origin, locator='fixture:turn1'))

    def check_and_work(self):
        self.apply(dict(op='check.add', id='verify', argv=[sys.executable, '-c', 'print("checked")'],
                        inputs=['input.txt'], timeout=10),
                   dict(op='work.add', id='build', title='Build guide', requires=[],
                        owners=[], checks=['verify']))

    def test_assistant_proposal_cannot_be_accepted_without_user_provenance(self):
        self.capture('proposal', 'assistant')
        self.refuse_without_write(dict(op='item.add', id='offline', kind='decision',
                                       text='Offline guide', status='accepted', sources=['proposal']))
        self.apply(dict(op='item.add', id='offline', kind='decision', text='Offline guide',
                        status='proposed', sources=['proposal']))
        self.refuse_without_write(dict(op='item.status', id='offline', status='accepted',
                                       source='proposal', reason='Assistant thinks it best'))

    def test_pending_capture_blocks_closeout_even_after_passing_check(self):
        self.capture()
        self.check_and_work()
        core.run_check(self.root, 'verify')
        self.assertTrue(core.readiness(core.load(self.root), root=self.root))
        self.refuse_without_write(dict(op='work.status', id='build', status='done', note='Finished'))
        self.apply(dict(op='capture.resolve', id='user1', items=[], reason='No durable content in fixture'))
        self.apply(dict(op='work.status', id='build', status='done', note='Verified'))

    def test_stale_revision_and_digest_reject_before_any_write(self):
        stale = core.load(self.root)
        self.apply(dict(op='project.set', purpose='Current purpose'))
        current = core.load(self.root)
        for revision, digest in [(stale['revision'], stale['digest']),
                                 (current['revision'], stale['digest']),
                                 (stale['revision'], current['digest'])]:
            before = self.ledger.read_bytes()
            with self.assertRaises(core.Error):
                core.apply(self.root, [dict(op='project.set', purpose='Lost update')], revision, digest)
            self.assertEqual(before, self.ledger.read_bytes())

    def test_requirements_cannot_be_deleted_or_rewritten(self):
        self.capture()
        self.apply(dict(op='item.add', id='offline', kind='requirement', text='Must work offline',
                        status='accepted', sources=['user1']),
                   dict(op='capture.resolve', id='user1', items=['offline'], reason='Recorded'))
        for op in [dict(op='item.remove', id='offline'),
                   dict(op='item.update', id='offline', text='Network required'),
                   dict(op='item.add', id='offline', kind='requirement', text='Changed',
                        status='accepted', sources=['user1'])]:
            self.refuse_without_write(op)
        self.assertEqual(core.load(self.root)['state']['items']['offline']['text'], 'Must work offline')

    def test_rehashed_history_rewrite_and_dropped_history_rejected_against_parent(self):
        self.apply(dict(op='project.set', purpose='First purpose'))
        parent = copy.deepcopy(core.load(self.root)['ledger'])
        changed = copy.deepcopy(parent)
        changed['events'][0]['operations'][0]['purpose'] = 'Rewritten history'
        event = changed['events'][0]
        event['digest'] = core.digest({key: value for key, value in event.items() if key != 'digest'})
        self.ledger.write_text(json.dumps(changed), encoding='utf-8')
        with self.assertRaises(core.Error):
            core.validate_parent(self.root, parent)
        dropped = copy.deepcopy(parent)
        dropped['events'] = []
        self.ledger.write_text(json.dumps(dropped), encoding='utf-8')
        with self.assertRaises(core.Error):
            core.validate_parent(self.root, parent)

    def test_changed_inputs_invalidate_pass_and_completed_work_readiness(self):
        self.check_and_work()
        core.run_check(self.root, 'verify')
        (self.root / 'input.txt').write_text('changed after test', encoding='utf-8')
        self.refuse_without_write(dict(op='work.status', id='build', status='done', note='Old test passed'))
        core.run_check(self.root, 'verify')
        self.apply(dict(op='work.status', id='build', status='done', note='Fresh test passed'))
        self.assertEqual([], core.readiness(core.load(self.root), root=self.root))
        (self.root / 'input.txt').write_text('changed after completion', encoding='utf-8')
        self.assertTrue(core.readiness(core.load(self.root), root=self.root))

    def test_fabricated_check_result_rejected(self):
        self.check_and_work()
        self.refuse_without_write(dict(op='check.run', id='verify', code=0,
                                       input_digest=core.input_digest(self.root, ['input.txt']), output='Forged'))
        self.refuse_without_write(dict(op='work.status', id='build', status='done', note='Assumed success'))

    def test_single_current_account_and_no_completed_next_work(self):
        self.apply(dict(op='current.set', summary='First checkpoint', next_work=None))
        self.apply(dict(op='current.set', summary='Second checkpoint', next_work=None))
        self.assertEqual(core.load(self.root)['state']['current'],
                         dict(summary='Second checkpoint', next_work=None))
        self.check_and_work()
        core.run_check(self.root, 'verify')
        self.apply(dict(op='work.status', id='build', status='done', note='Done'))
        self.refuse_without_write(dict(op='current.set', summary='Contradictory next step', next_work='build'))

    def test_running_effect_survives_reload_and_cannot_blindly_repeat(self):
        self.apply(dict(op='effect.add', id='publish', argv=[sys.executable, '-c', 'pass'],
                        inputs=['input.txt'], description='Simulated external command; never executed'))
        binding = core.input_digest(self.root, ['input.txt'])
        # Abruptly terminate a separate local process after its durable begin.
        program = '''import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import seedbag_core as core
root = Path(sys.argv[2])
s = core.load(root)
core.apply(root, [dict(op='effect.begin', id='publish', binding=core.input_digest(root, ['input.txt']))], s['revision'], s['digest'])
os._exit(23)
'''
        child = subprocess.run([sys.executable, '-B', '-c', program,
                                str(Path(core.__file__).parent), str(self.root)],
                               cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(child.returncode, 23, child.stdout + child.stderr)
        recovered = core.load(self.root)
        self.assertEqual(recovered['state']['effects']['publish']['status'], 'running')
        self.assertTrue(core.readiness(recovered, root=self.root))
        self.refuse_without_write(dict(op='effect.begin', id='publish', binding=binding))
        (self.root / 'receipt.txt').write_text('Fixture observation: command did not run.', encoding='utf-8')
        self.apply(dict(op='effect.resolve', id='publish', outcome='not_performed', receipt='receipt.txt'))
        self.refuse_without_write(dict(op='effect.begin', id='publish', binding=binding))

    def test_zero_exit_is_not_verified_external_effect(self):
        self.apply(dict(op='effect.add', id='publish', argv=[sys.executable, '-c', 'pass'],
                        inputs=['input.txt'], description='Fixture'))
        self.apply(dict(op='effect.begin', id='publish', binding=core.input_digest(self.root, ['input.txt'])))
        self.apply(dict(op='effect.return', id='publish', code=0, output='Success claimed'))
        self.assertTrue(core.readiness(core.load(self.root), root=self.root))

    @unittest.skipUnless(shutil.which('git'), 'Git executable is unavailable')
    def test_local_save_and_local_commit_do_not_claim_shared_checkpoint(self):
        import seedbag_git
        empty_template = self.root / 'empty-template'
        empty_template.mkdir()

        def git(*args):
            result = subprocess.run(['git', '-c', 'user.name=Seedbag Test',
                                     '-c', 'user.email=seedbag@example.invalid',
                                     '-c', 'commit.gpgsign=false',
                                     '-c', 'core.hooksPath=' + str(empty_template), *args],
                                    cwd=self.root, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        git('init', '--template=' + str(empty_template), '.')
        local = seedbag_git.status(self.root)
        self.assertEqual(local['commit_state'], 'unborn')
        self.assertEqual(local['shared_state'], 'no_shared_reference')
        self.assertEqual(local['reference_freshness'], 'cached_not_rechecked')
        git('add', '--', '.seedbag/ledger.json', 'input.txt')
        git('commit', '-m', 'Fixture local checkpoint')
        committed = seedbag_git.status(self.root)
        self.assertEqual(committed['commit_state'], 'committed')
        self.assertEqual(committed['shared_state'], 'no_shared_reference')
        self.assertEqual(committed['reference_freshness'], 'cached_not_rechecked')
        self.assertIsNone(committed['upstream'])

    def cli(self, *arguments):
        return subprocess.run([sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'seedbag.py'),
                               '--root', str(self.root), *arguments],
                              cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=20)

    def test_cli_malformed_effect_resolution_is_json_refusal_and_preserves_ledger(self):
        snapshot = core.load(self.root)
        request = dict(expected_revision=snapshot['revision'], expected_digest=snapshot['digest'],
                       operations=[dict(op='effect.resolve', id='missing', outcome='confirmed')])
        request_file = self.root / 'request.json'
        request_file.write_text(json.dumps(request), encoding='utf-8')
        before = self.ledger.read_bytes()
        result = self.cli('apply', '--file', str(request_file))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.ledger.read_bytes())
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail('CLI refusal was not JSON: ' + result.stderr)
        self.assertFalse(payload['ok'])

    def test_cli_capture_preserves_verbatim_line_endings(self):
        original = 'First exact line.\r\nSecond exact line.\r\n'
        source = self.root / 'message.txt'
        source.write_bytes(original.encode('utf-8'))
        result = self.cli('capture', '--file', str(source), '--id', 'verbatim',
                          '--origin', 'user', '--locator', 'fixture:exact-user-message')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(core.load(self.root)['state']['captures']['verbatim']['text'], original)

    def test_effect_runner_refuses_inputs_changed_since_preparation(self):
        self.apply(dict(op='effect.add', id='prepared',
                        argv=[sys.executable, '-c',
                              'from pathlib import Path; Path("effect-marker").write_text("executed")'],
                        inputs=['input.txt'], description='Prepared operation tied to original input'))
        (self.root / 'input.txt').write_text('Different scope after preparation', encoding='utf-8')
        with self.assertRaises(core.Error):
            core.run_effect(self.root, 'prepared')
        self.assertFalse((self.root / 'effect-marker').exists())

    def test_check_that_changes_own_declared_input_cannot_record_success(self):
        self.apply(dict(op='check.add', id='selfchanging',
                        argv=[sys.executable, '-c',
                              'from pathlib import Path; Path("input.txt").write_text("changed by check")'],
                        inputs=['input.txt'], timeout=10))
        with self.assertRaises(core.Error):
            core.run_check(self.root, 'selfchanging')
        self.assertNotIn('selfchanging', core.load(self.root)['state']['runs'])

    def test_cli_init_does_not_overwrite_existing_project(self):
        before = {path.relative_to(self.root): path.read_bytes()
                  for path in self.root.rglob('*') if path.is_file()}
        result = self.cli('init', str(self.root), '--name', 'Replacement', '--no-git')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)['ok'])
        after = {path.relative_to(self.root): path.read_bytes()
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_abruptly_terminated_lock_holder_does_not_leave_permanent_lock(self):
        program = '''import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import seedbag_core as core
with core.project_lock(Path(sys.argv[2])):
    os._exit(23)
'''
        child = subprocess.run([sys.executable, '-B', '-c', program,
                                str(Path(core.__file__).parent), str(self.root)],
                               cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(child.returncode, 23, child.stdout + child.stderr)
        snapshot = self.apply(dict(op='project.set', purpose='Recovered after abrupt lock-holder exit'))
        self.assertEqual(snapshot['revision'], 1)

    def test_changed_requirements_invalidate_pass_even_with_identical_files(self):
        self.capture()
        self.apply(dict(op='item.add', id='offline', kind='requirement', text='Must work offline',
                        status='accepted', sources=['user1']),
                   dict(op='capture.resolve', id='user1', items=['offline'], reason='Recorded'))
        self.check_and_work()
        core.run_check(self.root, 'verify')
        self.apply(dict(op='work.status', id='build', status='done', note='Verified original scope'))
        original_files_digest = core.input_digest(self.root, ['input.txt'])
        self.capture('user2')
        self.apply(dict(op='item.add', id='keyboard', kind='requirement', text='All controls must support keyboard',
                        status='accepted', sources=['user2']),
                   dict(op='capture.resolve', id='user2', items=['keyboard'], reason='New requirement recorded'))
        self.assertEqual(core.input_digest(self.root, ['input.txt']), original_files_digest)
        self.assertTrue(any('requirements' in problem.lower()
                            for problem in core.readiness(core.load(self.root), root=self.root)))
        self.refuse_without_write(dict(op='work.status', id='build', status='done', note='Old pass is insufficient'))
        core.run_check(self.root, 'verify')
        self.assertEqual(core.readiness(core.load(self.root), root=self.root), [])

    def test_legitimate_growth_preserves_item_and_moves_owner_route(self):
        original = self.root / 'layout.md'
        original.write_text('Domain layout requirements', encoding='utf-8')
        self.capture()
        self.apply(dict(op='owner.add', id='layout', path='layout.md', summary='Layout domain', tags=[], requires=[]),
                   dict(op='item.add', id='readable', kind='requirement', text='Use readable spacing',
                        status='accepted', sources=['user1']),
                   dict(op='capture.resolve', id='user1', items=['readable'], reason='Captured'))
        self.check_and_work()
        parent = core.load(self.root)['ledger']
        folder = self.root / 'docs'
        folder.mkdir()
        destination = folder / 'layout.md'
        destination.write_bytes(original.read_bytes())
        self.apply(dict(op='item.route', id='readable', **{'global': False}, owner='layout',
                        reason='Scoped layout requirement now has an explicit domain owner'),
                   dict(op='owner.move', id='layout', path='docs/layout.md', reason='Organize domain documents'),
                   dict(op='work.revise', id='build', requires=['readable'], owners=['layout'], checks=['verify'],
                        reason='Explicitly include layout requirements'))
        original.unlink()
        snapshot = core.validate_parent(self.root, parent)
        item = snapshot['state']['items']['readable']
        self.assertEqual(item['text'], 'Use readable spacing')
        self.assertEqual(item['status'], 'accepted')
        self.assertEqual(item['sources'], ['user1'])
        self.assertEqual(item['owner'], 'layout')
        self.assertFalse(item['global'])
        self.assertEqual(snapshot['state']['owners']['layout']['path'], 'docs/layout.md')
        self.assertEqual(snapshot['state']['work']['build']['requires'], ['readable'])
        core.run_check(self.root, 'verify')
        self.apply(dict(op='work.status', id='build', status='done', note='Verified expanded scope'))

    def test_new_id_alias_refused_while_equivalent_effect_is_unresolved(self):
        definition = dict(argv=[sys.executable, '-c', 'pass'], inputs=['input.txt'], description='Fixture command')
        self.apply(dict(op='effect.add', id='original', **definition))
        self.apply(dict(op='effect.begin', id='original', binding=core.input_digest(self.root, ['input.txt'])))
        self.refuse_without_write(dict(op='effect.add', id='alias', **definition))
        self.apply(dict(op='effect.return', id='original', code=0, output='Needs reconciliation'))
        self.refuse_without_write(dict(op='effect.add', id='another_alias', **definition))

    def test_prepared_alias_cannot_begin_while_equivalent_attempt_is_unresolved(self):
        (self.root / 'second.txt').write_text('Second input', encoding='utf-8')
        command = [sys.executable, '-c', 'pass']
        self.apply(dict(op='effect.add', id='first', argv=command,
                        inputs=['input.txt', 'second.txt'], description='First prepared attempt'),
                   dict(op='effect.add', id='earlier_alias', argv=command,
                        inputs=['second.txt', 'input.txt'], description='Previously prepared alias'))
        binding = core.input_digest(self.root, ['input.txt', 'second.txt'])
        self.apply(dict(op='effect.begin', id='first', binding=binding))
        self.refuse_without_write(dict(op='effect.begin', id='earlier_alias', binding=binding))
        self.apply(dict(op='effect.return', id='first', code=0, output='Outcome still needs inspection'))
        self.refuse_without_write(dict(op='effect.begin', id='earlier_alias', binding=binding))

    def test_portable_python_check_works_without_path_and_keeps_stored_command(self):
        script = self.root / 'verify.py'
        script.write_text('from pathlib import Path\n'
                          'assert Path("input.txt").read_text() == "original input"\n'
                          'print("portable check passed")\n', encoding='utf-8')
        command = ['@python', 'verify.py']
        self.apply(dict(op='check.add', id='portable', argv=command,
                        inputs=['verify.py', 'input.txt'], timeout=10))
        before = core.load(self.root)['ledger']['events'][0]
        with patch.dict(os.environ, {'PATH': ''}):
            result = core.run_check(self.root, 'portable')
        self.assertEqual(result['code'], 0, result['output'])
        self.assertIn('portable check passed', result['output'])
        after = core.load(self.root)
        self.assertEqual(after['state']['checks']['portable']['argv'], command)
        self.assertEqual(after['ledger']['events'][0], before)

    def test_context_exposes_stale_completed_work_without_losing_usable_packet(self):
        import seedbag_context
        self.check_and_work()
        core.run_check(self.root, 'verify')
        self.apply(dict(op='work.status', id='build', status='done', note='Declared check passed'),
                   dict(op='current.set', summary='Build completed and verified.', next_work=None))
        seedbag_context.render(self.root)
        self.assertTrue(seedbag_context.context(self.root)['checkpoint_ready'])
        (self.root / 'input.txt').write_text('Changed after completion', encoding='utf-8')
        packet = seedbag_context.context(self.root, budget=24000)
        self.assertFalse(packet['checkpoint_ready'])
        self.assertTrue(any('stale check inputs' in problem.lower()
                            for problem in packet['readiness_problems']))
        self.assertFalse(packet['overflow'])
        self.assertTrue(packet['brief'])
        self.assertEqual(packet['revision'], core.load(self.root)['revision'])
        self.assertEqual(packet['bytes'], len(seedbag_context.context_json(packet)))
        self.assertLessEqual(packet['bytes'], 24000)


if __name__ == '__main__':
    unittest.main()

