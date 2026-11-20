"""Hand a task to the OpenAI Codex that ships with the Codex desktop app on Windows, and bring the answer back.

Run with:  python -I codex_task.py <command> ...

  doctor                           check that codex.exe, the login and the app's records are where expected
  projects                         list Codex app projects and their folders
  models                           list model slugs, effort levels and the app's defaults
  run      --project P [opts]      BACKGROUND mode: codex exec, waits, prints the answer as JSON
  visible  --project P [opts]      VISIBLE mode: open a prefilled new thread in the app, wait for the
                                   user to press Send, then print the answer as JSON
  visible  --session ID [opts]     VISIBLE follow-up: prefill the next message in an existing thread
  continue SESSION_ID [opts]       BACKGROUND follow-up in an existing thread (codex exec resume)
  read     SESSION_ID [--all]      print the answer(s) recorded for a past session
  open     SESSION_ID              show that session in the Codex app

Prompt input (run / visible / continue): --prompt-file FILE (UTF-8; best for long or non-ASCII text) or
--prompt "short text". Avoid piping non-ASCII text through Windows PowerShell 5.1, which re-encodes it.

--project accepts a Codex app project name or a folder path. A thread is shown under the project that
owns its working folder.

Environment: CODEX_HOME (default ~/.codex) and CODEX_EXE (path to codex.exe, if it is not found by itself).

This script writes nothing itself. Codex writes its own session record under CODEX_HOME/sessions, and
writes files only if you pass --sandbox workspace-write. No copies of answers are saved.
"""
import argparse, glob, json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.parse

__version__ = '0.1.0'

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

CODEX_HOME = os.environ.get('CODEX_HOME') or os.path.join(os.path.expanduser('~'), '.codex')
SESSIONS = os.path.join(CODEX_HOME, 'sessions')
APP_PROCESS_NAMES = ('ChatGPT', 'Codex')   # the desktop app's main process, depending on the app version
URL_LIMIT = 8000                           # longer codex:// links are not passed on reliably


# ---------- helpers ----------
def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def die(msg, code=1):
    out({'error': msg})
    sys.exit(code)


def _app_version(path):
    m = re.search(r'OpenAI\.Codex_([\d.]+)_', path)
    return tuple(int(x) for x in m.group(1).split('.')) if m else ()


def find_codex_exe():
    """Return the path of codex.exe, or None.

    Order: CODEX_EXE; the codex.exe next to the desktop app that is running now; the newest installed
    desktop app; a codex on PATH (the npm CLI, which works for background mode only).
    """
    env = os.environ.get('CODEX_EXE')
    if env:
        return env if os.path.exists(env) else None
    for name in APP_PROCESS_NAMES:
        try:
            path = subprocess.run(['powershell', '-NoProfile', '-Command',
                                   '(Get-Process %s -ErrorAction SilentlyContinue | Select-Object -First 1).Path' % name],
                                  capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:
            path = ''
        if path:
            cand = os.path.join(os.path.dirname(path), 'resources', 'codex.exe')
            if os.path.exists(cand):
                return cand
    program_files = os.environ.get('ProgramFiles', r'C:\Program Files')
    found = glob.glob(os.path.join(program_files, 'WindowsApps', 'OpenAI.Codex_*', 'app', 'resources', 'codex.exe'))
    if found:
        return max(found, key=_app_version)
    return shutil.which('codex')


def codex_cmd():
    """The command prefix that starts Codex (a list, so tests can substitute a fake)."""
    exe = find_codex_exe()
    if not exe:
        die('codex.exe not found. Install the Codex desktop app (or the Codex CLI), open the app once, '
            'or set CODEX_EXE to the full path of codex.exe.')
    return [exe]


def norm(p):
    p = (p or '').replace('\\\\?\\', '').replace('/', '\\').rstrip('\\')
    return os.path.normcase(p)


def under(folder, root):
    """True if folder is root or inside it (compares whole path parts, not string prefixes)."""
    f, r = norm(folder), norm(root)
    return bool(r) and (f == r or f.startswith(r + '\\'))


def state_db_path():
    """The app's thread database. The file name carries a schema number (state_5.sqlite in 2026)."""
    found = glob.glob(os.path.join(CODEX_HOME, 'state_*.sqlite'))

    def num(p):
        m = re.search(r'state_(\d+)\.sqlite$', p)
        return int(m.group(1)) if m else -1
    return max(found, key=num) if found else None


def open_state_db():
    """Open the thread database read-only. Falls back to a temporary copy if it is locked."""
    db = state_db_path()
    if not db:
        return None, None
    try:
        con = sqlite3.connect('file:///' + db.replace('\\', '/') + '?mode=ro', uri=True, timeout=5)
        con.execute('select 1 from projects limit 1')
        return con, None
    except Exception:
        tmp = tempfile.mkdtemp(prefix='codexdb_')
        for f in glob.glob(db + '*'):
            shutil.copy(f, tmp)
        return sqlite3.connect(os.path.join(tmp, os.path.basename(db))), tmp


def list_projects():
    """{project name: [folders]} from the app's database; {} if there is none or its layout changed."""
    con, tmp = open_state_db()
    if con is None:
        return {}
    try:
        rows = con.execute('select p.name, r.position, r.path from projects p join project_roots r '
                           'on r.project_id = p.id order by p.position, r.position').fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    projects = {}
    for name, _pos, path in rows:
        projects.setdefault(name, []).append(path)
    return projects


def resolve_project(arg):
    """Return (folder, project_name). A folder argument is matched to the project that owns it."""
    projects = list_projects()
    if os.path.isdir(arg):
        folder = os.path.abspath(arg)
        owner = next((n for n, roots in projects.items() if any(under(folder, r) for r in roots)), None)
        return folder, owner
    for name, roots in projects.items():
        if name.casefold() == arg.casefold():
            return roots[0], name
    known = ', '.join(projects) if projects else '(none found; pass a folder path instead)'
    die('unknown project %r. Known projects: %s' % (arg, known))


def read_prompt(a):
    if a.prompt_file:
        with open(a.prompt_file, encoding='utf-8-sig') as f:
            text = f.read().strip()
    elif a.prompt:
        text = a.prompt.strip()
    else:
        die('give --prompt-file FILE or --prompt TEXT')
    if not text:
        die('the prompt is empty')
    return text


def rollout_path(session_id):
    if not re.fullmatch(r'[0-9a-fA-F-]{8,36}', session_id or ''):
        die('not a session id: %r' % session_id)
    hits = glob.glob(os.path.join(SESSIONS, '**', '*%s*.jsonl' % session_id), recursive=True)
    return max(hits, key=os.path.getmtime) if hits else None


def parse_rollout(path):
    """Return dict with cwd, source, model, effort, user_messages, answers (one per finished turn)."""
    info = {'session_id': None, 'cwd': None, 'source': None, 'model': None, 'effort': None,
            'user_messages': [], 'answers': [], 'finished': False}
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            t, pl = d.get('type'), d.get('payload') or {}
            if t == 'session_meta':
                info['session_id'] = pl.get('id')
                info['cwd'] = (pl.get('cwd') or '').replace('\\\\?\\', '')
                src = pl.get('source')
                info['source'] = src if isinstance(src, str) else json.dumps(src)
            elif t == 'turn_context':
                info['model'] = pl.get('model') or info['model']
                info['effort'] = pl.get('effort') or pl.get('reasoning_effort') or info['effort']
            elif t == 'event_msg' and pl.get('type') == 'thread_settings_applied':
                s = pl.get('thread_settings') or {}
                info['model'] = s.get('model') or info['model']
                info['effort'] = s.get('reasoning_effort') or s.get('effort') or info['effort']
            elif t == 'event_msg' and pl.get('type') == 'item_completed':
                item = pl.get('item') or {}
                if item.get('type') == 'UserMessage':
                    txt = ' '.join(c.get('text', '') for c in item.get('content') or [] if isinstance(c, dict))
                    info['user_messages'].append(txt)
            elif t == 'event_msg' and pl.get('type') == 'task_complete':
                info['answers'].append(pl.get('last_agent_message') or '')
                info['finished'] = True
            elif t == 'event_msg' and pl.get('type') == 'task_started':
                info['finished'] = False
    return info


def run_codex(cmd, prompt, folder, timeout):
    """Run Codex with the prompt on stdin as UTF-8 bytes (no shell quoting problems)."""
    t0 = time.time()
    try:
        r = subprocess.run(cmd, input=prompt.encode('utf-8'), capture_output=True, timeout=timeout, cwd=folder)
    except subprocess.TimeoutExpired:
        die('Codex did not finish within %d s (raise --timeout, or check the thread later with read)' % timeout)
    stdout = r.stdout.decode('utf-8', errors='replace')
    text = stdout + '\n' + r.stderr.decode('utf-8', errors='replace')
    return r.returncode, stdout, text, round(time.time() - t0)


def open_link(url):
    os.startfile(url)  # Windows: hands the codex:// link to the desktop app


def thread_link(session_id):
    return 'codex://threads/%s' % session_id


# ---------- commands ----------
def cmd_doctor(a):
    res = {'script_version': __version__, 'codex_home': CODEX_HOME, 'codex_home_exists': os.path.isdir(CODEX_HOME)}
    exe = find_codex_exe()
    res['codex_exe'] = exe
    if exe:
        for key, args in (('codex_version', ['--version']), ('login', ['login', 'status'])):
            try:
                r = subprocess.run([exe] + args, capture_output=True, timeout=30)
                res[key] = (r.stdout + r.stderr).decode('utf-8', errors='replace').strip()
            except Exception as e:
                res[key] = 'failed: %s' % e
        res['bundled_with_desktop_app'] = 'WindowsApps' in exe or os.path.basename(os.path.dirname(exe)) == 'resources'
    res['state_db'] = state_db_path()
    res['projects_found'] = len(list_projects())
    res['session_records'] = os.path.isdir(SESSIONS)
    res['models_cache'] = os.path.exists(os.path.join(CODEX_HOME, 'models_cache.json'))
    problems = []
    if not exe:
        problems.append('codex.exe not found: install or open the Codex desktop app, or set CODEX_EXE')
    elif 'not logged in' in (res.get('login') or '').lower():
        problems.append('Codex is not logged in: sign in once in the desktop app')
    if not res['state_db']:
        problems.append('no app database: project names will not resolve, so pass folder paths to --project')
    res['ok'] = not problems
    res['problems'] = problems
    out(res)


def cmd_projects(a):
    out(list_projects())


def cmd_models(a):
    res = {'models': {}, 'app_default': {}}
    try:
        with open(os.path.join(CODEX_HOME, 'models_cache.json'), encoding='utf-8') as f:
            raw = json.load(f)
        for m in raw.get('models', []):
            if m.get('visibility') == 'list':
                res['models'][m['slug']] = {
                    'efforts': [e.get('effort') for e in m.get('supported_reasoning_levels', [])],
                    'default_effort': m.get('default_reasoning_level'),
                    'description': m.get('description')}
    except Exception as e:
        res['models_error'] = 'could not read models_cache.json (%s); open the app once to create it' % e
    try:
        with open(os.path.join(CODEX_HOME, 'config.toml'), encoding='utf-8') as f:
            for line in f:
                m = re.match(r'^(model|model_reasoning_effort|service_tier)\s*=\s*"([^"]*)"', line)
                if m:
                    res['app_default'][m.group(1)] = m.group(2)
    except Exception:
        pass
    out(res)


def cmd_run(a):
    folder, project = resolve_project(a.project)
    prompt = read_prompt(a)
    cmd = codex_cmd() + ['exec', '--skip-git-repo-check', '-s', a.sandbox, '-C', folder]
    if a.model:
        cmd += ['-m', a.model]
    if a.effort:
        cmd += ['-c', 'model_reasoning_effort="%s"' % a.effort]
    if a.ephemeral:
        cmd += ['--ephemeral']
    for img in a.image or []:
        cmd += ['-i', img]
    cmd += ['-']  # read the prompt from stdin
    code, stdout, text, secs = run_codex(cmd, prompt, folder, a.timeout)
    m = re.search(r'session id:\s*([0-9a-f-]{36})', text)
    sid = m.group(1) if m else None
    res = {'mode': 'background', 'project': project, 'folder': folder, 'session_id': sid,
           'exit_code': code, 'seconds': secs}
    path = rollout_path(sid) if sid and not a.ephemeral else None
    if path:
        info = parse_rollout(path)
        res.update(model=info['model'], effort=info['effort'],
                   answer=info['answers'][-1] if info['answers'] else None)
    else:
        mm = re.search(r'model:\s*(\S+)', text)
        me = re.search(r'reasoning effort:\s*(\S+)', text)
        res.update(model=mm and mm.group(1), effort=me and me.group(1))
        # No session record (--ephemeral): codex exec prints only the final message on stdout, the log on stderr.
        res['answer'] = stdout.strip() or None
    if code != 0 or not res.get('answer'):
        res['log_tail'] = text[-3000:]
    if sid and not a.ephemeral:
        res['open_link'] = thread_link(sid)
        if a.open:
            open_link(thread_link(sid))
    out(res)


def cmd_continue(a):
    """BACKGROUND follow-up in an existing thread (codex exec resume)."""
    path = rollout_path(a.session_id)
    if not path:
        die('no session record found for %s under %s' % (a.session_id, SESSIONS))
    info = parse_rollout(path)
    prompt = read_prompt(a)
    n_before = len(info['answers'])
    cmd = codex_cmd() + ['exec', 'resume', '--skip-git-repo-check', '-c', 'sandbox_mode="%s"' % a.sandbox]
    if a.model:
        cmd += ['-m', a.model]
    if a.effort:
        cmd += ['-c', 'model_reasoning_effort="%s"' % a.effort]
    cmd += [a.session_id, '-']
    folder = info['cwd'] if info['cwd'] and os.path.isdir(info['cwd']) else None
    code, _stdout, text, secs = run_codex(cmd, prompt, folder, a.timeout)
    info = parse_rollout(path)
    res = {'mode': 'background-continue', 'session_id': a.session_id, 'folder': folder, 'exit_code': code,
           'seconds': secs, 'model': info['model'], 'effort': info['effort'], 'turns': len(info['answers']),
           'answer': info['answers'][-1] if len(info['answers']) > n_before else None,
           'open_link': thread_link(a.session_id)}
    if 'active writer' in text:
        res['blocked'] = ('the Codex app has this thread open, so Codex refused a second writer and nothing '
                          'changed. Use: visible --session %s --prompt-file F' % a.session_id)
    elif code != 0 or not res['answer']:
        res['log_tail'] = text[-3000:]
    out(res)


def prefill_url(base, params):
    url = base + '?' + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    if len(url) > URL_LIMIT:
        die('the prompt is too long for an app link (%d characters, limit %d). Put the long material in a file '
            'inside the project folder and make the prompt point to it, or use background mode.' % (len(url), URL_LIMIT))
    return url


def cmd_visible_followup(a, prompt):
    """VISIBLE follow-up: open an existing thread with the next message prefilled; wait for Send + answer."""
    path = rollout_path(a.session_id)
    if not path:
        die('no session record found for %s under %s' % (a.session_id, SESSIONS))
    n_before = len(parse_rollout(path)['answers'])
    open_link(prefill_url(thread_link(a.session_id), {'prompt': prompt}))
    res = {'mode': 'visible-continue', 'session_id': a.session_id,
           'note': 'Opened the thread in the Codex app with the follow-up prefilled; it runs after the user presses Send.'}
    if not a.no_wait:
        deadline = time.time() + a.wait
        while time.time() < deadline:
            info = parse_rollout(path)
            if info['finished'] and len(info['answers']) > n_before:
                res.update(model=info['model'], effort=info['effort'], answer=info['answers'][-1])
                break
            time.sleep(5)
        else:
            res['status'] = 'no new answer yet: the user has probably not pressed Send'
    out(res)


def find_new_thread(folder, prompt, t0):
    """The app thread started after t0 in this folder; prefer the one whose first message matches the prompt
    (the user may have edited it, so fall back to the newest). Returns (matched, info) or None."""
    key = prompt[:40]
    cands = []
    for p in glob.glob(os.path.join(SESSIONS, '**', '*.jsonl'), recursive=True):
        if os.path.getmtime(p) < t0 - 5 or os.path.getctime(p) < t0 - 5:
            continue
        info = parse_rollout(p)
        if norm(info['cwd']) != norm(folder) or 'subagent' in (info['source'] or ''):
            continue
        match = any(key and key in u for u in info['user_messages'])
        cands.append((match, os.path.getctime(p), info))
    if not cands:
        return None
    match, _, info = max(cands, key=lambda c: (c[0], c[1]))
    return match, info


def cmd_visible(a):
    prompt = read_prompt(a)
    if a.session_id:
        return cmd_visible_followup(a, prompt)
    if not a.project:
        die('give --project (new thread) or --session (follow-up in an existing thread)')
    folder, project = resolve_project(a.project)
    url = prefill_url('codex://threads/new', {'path': folder, 'prompt': prompt})
    t0 = time.time()
    open_link(url)
    res = {'mode': 'visible', 'project': project, 'folder': folder,
           'note': 'Opened a prefilled new thread in the Codex app. It runs with the model selected there, '
                   'and only after the user presses Send.'}
    if a.no_wait:
        return out(res)
    found = None
    while time.time() < t0 + a.wait:
        found = find_new_thread(folder, prompt, t0)
        if found and found[1]['finished'] and found[1]['answers']:
            match, info = found
            res.update(session_id=info['session_id'], model=info['model'], effort=info['effort'],
                       prompt_matched=match, answer=info['answers'][-1], open_link=thread_link(info['session_id']))
            return out(res)
        time.sleep(5)
    if found:
        res.update(session_id=found[1]['session_id'], status='still running when waiting stopped; use read later')
    else:
        res['status'] = 'no new thread found: the user has probably not pressed Send yet'
    out(res)


def cmd_read(a):
    path = rollout_path(a.session_id)
    if not path:
        die('no session record found for %s under %s' % (a.session_id, SESSIONS))
    info = parse_rollout(path)
    res = {k: info[k] for k in ('session_id', 'cwd', 'source', 'model', 'effort', 'finished')}
    if a.all:
        res['answers'] = info['answers']
    else:
        res['answer'] = info['answers'][-1] if info['answers'] else None
    out(res)


def cmd_open(a):
    rollout_path(a.session_id)  # validates the id
    open_link(thread_link(a.session_id))
    out({'opened': thread_link(a.session_id)})


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--version', action='version', version=__version__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('doctor').set_defaults(f=cmd_doctor)
    sub.add_parser('projects').set_defaults(f=cmd_projects)
    sub.add_parser('models').set_defaults(f=cmd_models)

    r = sub.add_parser('run'); r.set_defaults(f=cmd_run)
    v = sub.add_parser('visible'); v.set_defaults(f=cmd_visible)
    c = sub.add_parser('continue'); c.set_defaults(f=cmd_continue)
    c.add_argument('session_id')
    r.add_argument('--project', required=True, help='Codex app project name or folder path')
    v.add_argument('--project', help='project for a NEW thread')
    v.add_argument('--session', dest='session_id', help='existing thread to prefill a follow-up into')
    for p in (r, v, c):
        p.add_argument('--prompt-file')
        p.add_argument('--prompt')
    for p in (r, c):
        p.add_argument('--model', help='model slug (see: models); default is the app default')
        p.add_argument('--effort', help='reasoning effort, e.g. low|medium|high|xhigh (see: models)')
        p.add_argument('--sandbox', default='read-only', choices=['read-only', 'workspace-write'])
        p.add_argument('--timeout', type=int, default=3600)
    r.add_argument('--ephemeral', action='store_true', help='keep no session record (cannot be opened later)')
    r.add_argument('--image', action='append', help='attach an image (repeatable)')
    r.add_argument('--open', action='store_true', help='open the finished thread in the Codex app')
    v.add_argument('--wait', type=int, default=1800, help='seconds to wait for Send + answer')
    v.add_argument('--no-wait', action='store_true')

    rd = sub.add_parser('read'); rd.set_defaults(f=cmd_read)
    rd.add_argument('session_id'); rd.add_argument('--all', action='store_true')
    o = sub.add_parser('open'); o.set_defaults(f=cmd_open); o.add_argument('session_id')
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.f(a)


if __name__ == '__main__':
    main()
