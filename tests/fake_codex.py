"""A stand-in for codex.exe used by the tests. It never contacts anything.

`exec ...  -`            reads the prompt from stdin, writes a made-up session record under
                         CODEX_HOME/sessions, prints "session id: <uuid>" the way codex does.
`exec resume ... ID -`   appends a turn to that record; with FAKE_CODEX_BUSY=1 it fails the way
                         codex does when the desktop app has the thread open.
Every call saves its arguments and prompt to CODEX_HOME/fake_call.json for the tests to inspect.
"""
import glob, json, os, sys, uuid

home = os.environ['CODEX_HOME']
args = sys.argv[1:]
prompt = sys.stdin.buffer.read().decode('utf-8')
with open(os.path.join(home, 'fake_call.json'), 'w', encoding='utf-8') as f:
    json.dump({'args': args, 'prompt': prompt, 'cwd': os.getcwd()}, f, ensure_ascii=False)


def opt(flag):
    return args[args.index(flag) + 1] if flag in args else None


def effort():
    for i, a in enumerate(args):
        if a == '-c' and args[i + 1].startswith('model_reasoning_effort='):
            return args[i + 1].split('=', 1)[1].strip('"')
    return 'medium'


def turn(model, eff, text):
    return [
        {'type': 'event_msg', 'payload': {'type': 'task_started'}},
        {'type': 'turn_context', 'payload': {'model': model, 'effort': eff}},
        {'type': 'event_msg', 'payload': {'type': 'item_completed',
                                          'item': {'type': 'UserMessage', 'content': [{'type': 'text', 'text': text}]}}},
        {'type': 'event_msg', 'payload': {'type': 'task_complete', 'last_agent_message': 'echo: ' + text}},
    ]


if args[:2] == ['exec', 'resume']:
    sid = args[-2]
    if os.environ.get('FAKE_CODEX_BUSY') == '1':
        sys.stderr.write('Error: thread-store conflict: thread %s already has an active writer\n' % sid)
        sys.exit(1)
    path = glob.glob(os.path.join(home, 'sessions', '**', '*%s*.jsonl' % sid), recursive=True)[0]
    with open(path, 'a', encoding='utf-8') as f:
        for e in turn(opt('-m') or 'fake-model', effort(), prompt):
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    sys.stderr.write('session id: %s\n' % sid)
    sys.exit(0)

sid = str(uuid.uuid4())
if '--ephemeral' in args:  # no session record; the log goes to stderr, the final message alone to stdout
    sys.stderr.write('model: %s\nreasoning effort: %s\nsession id: %s\ncodex\necho: %s\ntokens used\n1,234\n'
                     % (opt('-m') or 'fake-model', effort(), sid, prompt))
    print('echo: ' + prompt)
    sys.exit(0)
cwd = opt('-C') or os.getcwd()
folder = os.path.join(home, 'sessions', '2026', '01', '01')
os.makedirs(folder, exist_ok=True)
events = [{'type': 'session_meta', 'payload': {'id': sid, 'cwd': cwd, 'source': 'exec'}}]
events += turn(opt('-m') or 'fake-model', effort(), prompt)
with open(os.path.join(folder, 'rollout-2026-01-01T00-00-00-%s.jsonl' % sid), 'w', encoding='utf-8') as f:
    for e in events:
        f.write(json.dumps(e, ensure_ascii=False) + '\n')
sys.stderr.write('OpenAI Codex (fake)\nsession id: %s\n' % sid)
print('echo: ' + prompt)
