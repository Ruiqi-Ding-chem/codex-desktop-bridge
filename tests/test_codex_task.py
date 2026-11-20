"""Tests for codex_task.py. They use a temporary CODEX_HOME with made-up records and a fake codex,
so they need neither Codex nor a network connection, and never touch the real ~/.codex."""
import contextlib, importlib.util, io, json, os, shutil, sqlite3, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', 'skills', 'codex-bridge', 'scripts', 'codex_task.py')
FAKE = os.path.join(HERE, 'fake_codex.py')

spec = importlib.util.spec_from_file_location('codex_task', SCRIPT)
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)

SID = '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'


def write_jsonl(path, events, extra_lines=()):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
        for line in extra_lines:
            f.write(line + '\n')


def sample_events(cwd):
    return [
        {'type': 'session_meta', 'payload': {'id': SID, 'cwd': '\\\\?\\' + cwd, 'source': 'vscode'}},
        {'type': 'event_msg', 'payload': {'type': 'thread_settings_applied',
                                          'thread_settings': {'model': 'model-a', 'reasoning_effort': 'high'}}},
        {'type': 'event_msg', 'payload': {'type': 'task_started'}},
        {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {
            'type': 'UserMessage', 'content': [{'type': 'text', 'text': 'Summarise the notes in 3 bullets'}]}}},
        {'type': 'event_msg', 'payload': {'type': 'task_complete', 'last_agent_message': 'First answer'}},
        {'type': 'event_msg', 'payload': {'type': 'task_started'}},
        {'type': 'turn_context', 'payload': {'model': 'model-b', 'effort': 'low'}},
        {'type': 'event_msg', 'payload': {'type': 'task_complete', 'last_agent_message': '第二个回答'}},
    ]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='codex_bridge_test_')
        self.home = os.path.join(self.tmp, 'codex_home')
        self.work = os.path.join(self.tmp, 'Thesis')
        self.work2 = os.path.join(self.tmp, 'Thesis2')  # a sibling whose name starts the same
        for d in (self.home, self.work, self.work2):
            os.makedirs(d)
        self._saved = (ct.CODEX_HOME, ct.SESSIONS, os.environ.get('CODEX_HOME'), os.environ.get('CODEX_EXE'))
        ct.CODEX_HOME, ct.SESSIONS = self.home, os.path.join(self.home, 'sessions')
        os.environ['CODEX_HOME'] = self.home
        os.environ.pop('CODEX_EXE', None)
        self.rollout = os.path.join(self.home, 'sessions', '2026', '01', '01', 'rollout-2026-01-01T00-00-00-%s.jsonl' % SID)
        write_jsonl(self.rollout, sample_events(self.work), extra_lines=['not json', '[1, 2]'])
        con = sqlite3.connect(os.path.join(self.home, 'state_5.sqlite'))
        con.executescript('''
            create table projects (id integer primary key, name text, position integer);
            create table project_roots (project_id integer, position integer, path text);
        ''')
        con.execute('insert into projects values (1, ?, 0)', ('Thesis',))
        con.execute('insert into projects values (2, ?, 1)', ('Notes',))
        con.execute('insert into project_roots values (1, 0, ?)', (self.work,))
        con.execute('insert into project_roots values (1, 1, ?)', (os.path.join(self.tmp, 'Thesis-figures'),))
        con.execute('insert into project_roots values (2, 0, ?)', (os.path.join(self.tmp, 'Notes'),))
        con.commit(); con.close()
        self.opened = []
        self._open_link = ct.open_link
        ct.open_link = self.opened.append
        self._codex_cmd = ct.codex_cmd
        ct.codex_cmd = lambda: [sys.executable, FAKE]

    def tearDown(self):
        ct.CODEX_HOME, ct.SESSIONS = self._saved[0], self._saved[1]
        for key, val in (('CODEX_HOME', self._saved[2]), ('CODEX_EXE', self._saved[3])):
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        os.environ.pop('FAKE_CODEX_BUSY', None)
        ct.open_link, ct.codex_cmd = self._open_link, self._codex_cmd
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, *argv):
        """Run a command; return its JSON output (also for errors, which exit with code 1)."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                ct.main(list(argv))
            except SystemExit as e:
                if e.code not in (0, 1, None):
                    raise
        return json.loads(buf.getvalue())

    def last_call(self):
        with open(os.path.join(self.home, 'fake_call.json'), encoding='utf-8') as f:
            return json.load(f)

    def prompt_file(self, text):
        p = os.path.join(self.tmp, 'prompt.txt')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(text)
        return p


class TestRecords(Base):
    def test_parse_rollout(self):
        info = ct.parse_rollout(self.rollout)
        self.assertEqual(info['session_id'], SID)
        self.assertEqual(info['cwd'], self.work)  # \\?\ prefix removed
        self.assertEqual(info['source'], 'vscode')
        self.assertEqual((info['model'], info['effort']), ('model-b', 'low'))
        self.assertEqual(info['user_messages'], ['Summarise the notes in 3 bullets'])
        self.assertEqual(info['answers'], ['First answer', '第二个回答'])
        self.assertTrue(info['finished'])

    def test_unfinished_turn(self):
        with open(self.rollout, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_started'}}) + '\n')
        self.assertFalse(ct.parse_rollout(self.rollout)['finished'])

    def test_read(self):
        self.assertEqual(self.call('read', SID)['answer'], '第二个回答')
        self.assertEqual(self.call('read', SID, '--all')['answers'], ['First answer', '第二个回答'])

    def test_read_unknown_session(self):
        self.assertIn('no session record', self.call('read', '0190a1b2-0000-0000-0000-000000000000')['error'])

    def test_session_id_is_validated(self):
        self.assertIn('not a session id', self.call('read', '*')['error'])
        self.assertIn('not a session id', self.call('open', '..\\x')['error'])

    def test_open(self):
        self.assertEqual(self.call('open', SID)['opened'], 'codex://threads/' + SID)
        self.assertEqual(self.opened, ['codex://threads/' + SID])


class TestProjects(Base):
    def test_list_projects(self):
        self.assertEqual(ct.list_projects(), {
            'Thesis': [self.work, os.path.join(self.tmp, 'Thesis-figures')],
            'Notes': [os.path.join(self.tmp, 'Notes')]})

    def test_resolve_by_name_ignores_case(self):
        self.assertEqual(ct.resolve_project('thesis'), (self.work, 'Thesis'))

    def test_resolve_by_folder(self):
        sub = os.path.join(self.work, 'chapter1')
        os.makedirs(sub)
        self.assertEqual(ct.resolve_project(sub), (sub, 'Thesis'))

    def test_sibling_folder_is_not_inside(self):
        self.assertEqual(ct.resolve_project(self.work2), (self.work2, None))

    def test_unknown_project(self):
        err = self.call('run', '--project', 'Nope', '--prompt', 'x')['error']
        self.assertIn("unknown project 'Nope'", err)
        self.assertIn('Thesis', err)

    def test_newest_state_db_wins(self):
        open(os.path.join(self.home, 'state_7.sqlite'), 'w').close()
        self.assertTrue(ct.state_db_path().endswith('state_7.sqlite'))

    def test_no_database(self):
        os.remove(os.path.join(self.home, 'state_5.sqlite'))
        self.assertEqual(ct.list_projects(), {})
        self.assertEqual(ct.resolve_project(self.work), (self.work, None))

    def test_database_layout_changed(self):
        os.remove(os.path.join(self.home, 'state_5.sqlite'))
        con = sqlite3.connect(os.path.join(self.home, 'state_5.sqlite'))
        con.execute('create table something_else (x)'); con.commit(); con.close()
        self.assertEqual(ct.list_projects(), {})


class TestModels(Base):
    def test_models(self):
        with open(os.path.join(self.home, 'models_cache.json'), 'w', encoding='utf-8') as f:
            json.dump({'models': [
                {'slug': 'model-a', 'visibility': 'list', 'default_reasoning_level': 'medium',
                 'supported_reasoning_levels': [{'effort': 'low'}, {'effort': 'high'}], 'description': 'A'},
                {'slug': 'hidden', 'visibility': 'hide'}]}, f)
        with open(os.path.join(self.home, 'config.toml'), 'w', encoding='utf-8') as f:
            f.write('model = "model-a"\nmodel_reasoning_effort = "high"\nservice_tier = "priority"\n')
        res = self.call('models')
        self.assertEqual(list(res['models']), ['model-a'])
        self.assertEqual(res['models']['model-a']['efforts'], ['low', 'high'])
        self.assertEqual(res['app_default'], {'model': 'model-a', 'model_reasoning_effort': 'high',
                                              'service_tier': 'priority'})

    def test_models_without_cache(self):
        self.assertIn('models_error', self.call('models'))


class TestBackground(Base):
    def test_run(self):
        prompt = '只读。请用一句话总结 “notes.md”。'
        res = self.call('run', '--project', 'Thesis', '--prompt-file', self.prompt_file(prompt),
                        '--model', 'model-x', '--effort', 'high')
        self.assertEqual(res['exit_code'], 0)
        self.assertEqual((res['project'], res['folder']), ('Thesis', self.work))
        self.assertEqual((res['model'], res['effort']), ('model-x', 'high'))
        self.assertEqual(res['answer'], 'echo: ' + prompt)
        self.assertEqual(res['open_link'], 'codex://threads/' + res['session_id'])
        call = self.last_call()
        self.assertEqual(call['prompt'], prompt)  # arrived intact as UTF-8
        self.assertEqual(call['args'][:6], ['exec', '--skip-git-repo-check', '-s', 'read-only', '-C', self.work])
        self.assertIn('model_reasoning_effort="high"', call['args'])
        self.assertEqual(call['args'][-1], '-')
        self.assertEqual(self.opened, [])

    def test_run_open_and_write_sandbox(self):
        res = self.call('run', '--project', self.work, '--prompt', 'hi', '--sandbox', 'workspace-write', '--open')
        call = self.last_call()
        self.assertIn('workspace-write', call['args'])
        self.assertNotIn('-m', call['args'])  # no --model: the app default is used
        self.assertEqual(self.opened, [res['open_link']])

    def test_run_ephemeral(self):
        res = self.call('run', '--project', 'Thesis', '--prompt', '17 x 23?', '--model', 'model-y',
                        '--effort', 'low', '--ephemeral')
        self.assertEqual(res['answer'], 'echo: 17 x 23?')
        self.assertEqual((res['model'], res['effort']), ('model-y', 'low'))
        self.assertNotIn('open_link', res)
        self.assertNotIn('log_tail', res)

    def test_empty_prompt(self):
        self.assertIn('empty', self.call('run', '--project', 'Thesis', '--prompt-file', self.prompt_file('  \n'))['error'])

    def test_continue(self):
        res = self.call('continue', SID, '--prompt', 'Now shorter', '--effort', 'low')
        self.assertEqual(res['answer'], 'echo: Now shorter')
        self.assertEqual(res['turns'], 3)
        self.assertEqual(res['folder'], self.work)
        call = self.last_call()
        self.assertEqual(call['args'][:2], ['exec', 'resume'])
        self.assertEqual(call['args'][-2:], [SID, '-'])

    def test_continue_blocked_by_open_app_thread(self):
        os.environ['FAKE_CODEX_BUSY'] = '1'
        res = self.call('continue', SID, '--prompt', 'Now shorter')
        self.assertIn('blocked', res)
        self.assertIsNone(res['answer'])
        self.assertEqual(ct.parse_rollout(self.rollout)['answers'], ['First answer', '第二个回答'])  # unchanged


class TestVisible(Base):
    def test_new_thread_link(self):
        res = self.call('visible', '--project', 'Thesis', '--prompt', 'Draft an abstract & title', '--no-wait')
        self.assertEqual(res['mode'], 'visible')
        url = self.opened[0]
        self.assertTrue(url.startswith('codex://threads/new?path='))
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(url).query)
        self.assertEqual(q['path'], [self.work])
        self.assertEqual(q['prompt'], ['Draft an abstract & title'])

    def test_followup_link(self):
        self.call('visible', '--session', SID, '--prompt', '再改短一点', '--no-wait')
        self.assertTrue(self.opened[0].startswith('codex://threads/%s?prompt=' % SID))

    def test_prompt_too_long_for_link(self):
        res = self.call('visible', '--project', 'Thesis', '--prompt', '长' * 3000, '--no-wait')
        self.assertIn('too long', res['error'])
        self.assertEqual(self.opened, [])

    def test_needs_project_or_session(self):
        self.assertIn('--project', self.call('visible', '--prompt', 'x', '--no-wait')['error'])

    def test_find_new_thread_prefers_matching_prompt(self):
        import time
        t0 = time.time()
        other = os.path.join(self.home, 'sessions', '2026', '01', '02', 'rollout-x-0190a1b2-0000-0000-0000-00000000000a.jsonl')
        mine = os.path.join(self.home, 'sessions', '2026', '01', '02', 'rollout-x-0190a1b2-0000-0000-0000-00000000000b.jsonl')
        for path, sid, text in ((mine, 'b', 'Draft an abstract'), (other, 'a', 'Something else')):
            write_jsonl(path, [
                {'type': 'session_meta', 'payload': {'id': sid, 'cwd': self.work, 'source': 'vscode'}},
                {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {
                    'type': 'UserMessage', 'content': [{'type': 'text', 'text': text}]}}}])
        matched, info = ct.find_new_thread(self.work, 'Draft an abstract', t0)
        self.assertTrue(matched)
        self.assertEqual(info['session_id'], 'b')


class TestSetup(Base):
    def test_codex_exe_from_environment(self):
        exe = os.path.join(self.tmp, 'codex.exe')
        open(exe, 'w').close()
        os.environ['CODEX_EXE'] = exe
        self.assertEqual(ct.find_codex_exe(), exe)
        os.environ['CODEX_EXE'] = os.path.join(self.tmp, 'missing.exe')
        self.assertIsNone(ct.find_codex_exe())

    def test_under(self):
        self.assertTrue(ct.under(r'C:\Work\Thesis\ch1', r'c:\work\thesis'))
        self.assertTrue(ct.under(r'\\?\C:\Work\Thesis', 'C:/Work/Thesis/'))
        self.assertFalse(ct.under(r'C:\Work\Thesis2', r'C:\Work\Thesis'))
        self.assertFalse(ct.under(r'C:\Work', ''))


if __name__ == '__main__':
    unittest.main()
