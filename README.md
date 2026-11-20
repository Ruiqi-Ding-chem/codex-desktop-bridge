# codex-desktop-bridge

[中文说明](README.zh-CN.md)

A Claude Code skill that lets Claude hand a task, or part of one, to the **OpenAI Codex desktop app on Windows** and bring the answer back. Use it to get a second draft from GPT, have Codex check Claude's work, or give the same task to both and compare.

Codex runs under your own ChatGPT account, with your Codex skills, plugins and `AGENTS.md`. No API key, Node or extra Python packages are needed: the skill uses the `codex.exe` that ships with the desktop app.

> Unofficial. Not affiliated with or endorsed by OpenAI or Anthropic. Windows only.

## What you can ask Claude

- "Ask Codex to write a version of this section too, then compare it with yours."
- "Run this check in Codex in the background with high effort."
- "Put the prompt in Codex so I can look at it before sending."
- "Continue that Codex thread and ask it to shorten the summary."

The skill only runs when you ask for Codex, GPT or ChatGPT. Claude won't use it on its own, because every run spends your ChatGPT quota.

## Two modes

| | Background (`run`) | Visible (`visible`) |
|---|---|---|
| Good for | automated subtasks, comparisons | prompts you want to read, edit or approve first |
| Model and effort | chosen per run | whatever you pick in the app |
| Who presses Send | nobody: it runs at once | you, in the app |
| Shows in the app's thread list | no (Claude can open it by link) | yes |
| Answer returned to Claude | yes | yes, after you send |

Both modes put the thread under the Codex app project that owns the working folder. Follow-ups can go into the same thread in either mode.

## Requirements

- Windows 10 or 11.
- The Codex desktop app, installed and signed in. If you only have the Codex CLI from npm, background mode works but visible mode needs the app.
- [Claude Code](https://claude.com/claude-code).
- Python 3.8 or newer on PATH (`python` or `py -3`). Only the standard library is used.

## Install

As a plugin, from inside Claude Code:

```
/plugin marketplace add Ruiqi-Ding-chem/codex-desktop-bridge
/plugin install codex-desktop-bridge@codex-desktop-bridge
```

Or by hand: copy the folder `skills/codex-bridge` into `%USERPROFILE%\.claude\skills\`, so that `%USERPROFILE%\.claude\skills\codex-bridge\SKILL.md` exists.

Then check the setup, either by asking Claude to "check the Codex bridge setup" or by running:

```powershell
python -I "$env:USERPROFILE\.claude\skills\codex-bridge\scripts\codex_task.py" doctor
```

`doctor` reports where `codex.exe` is, the Codex version, whether Codex is logged in, and whether the app's project list can be read. If `codex.exe` is not found, open the app once, or set the environment variable `CODEX_EXE` to its full path.

## How it works

- **Background mode** runs `codex exec` (and `codex exec resume` for follow-ups) with the model, reasoning effort, sandbox and working folder you choose. The prompt goes in on stdin as UTF-8, so long or non-English prompts are safe. The answer, model and effort are read from Codex's own session record in `~/.codex/sessions`.
- **Visible mode** opens a `codex://threads/new?path=…&prompt=…` link, so the app shows a new thread in the right project with the prompt filled in. The script waits for you to press Send and then picks up the answer the same way.
- **Project names** come from the app's local database, opened read-only.

The script prints JSON for Claude to read. It writes nothing itself: Codex keeps its usual session record, and changes files only if Claude passes `--sandbox workspace-write`, which the skill reserves for tasks where you asked Codex to edit files.

## Limits

- Background threads don't appear in the app's thread list. That is how the app filters threads started from the command line; Claude can still open one by link.
- Visible-mode links can't pick the model or press Send, and the prompt must fit in a link (about 8000 characters once encoded). Longer material goes in a file that the prompt points to.
- If the app has a thread open, Codex refuses a background follow-up to it. The script reports this as `blocked` and changes nothing, and the visible follow-up works instead.
- `codex exec` is documented by OpenAI for scripting. The `codex://` links and the app's database layout are not documented and may change with app updates. If something breaks after an update, run `doctor` and please open an issue.

Tested with Codex desktop app 26.1111 (codex-cli 0.169.1) on Windows 11.

## Privacy and safety

- Nothing is sent anywhere except what Codex itself sends to OpenAI when it runs your prompt.
- The default sandbox is read-only, and the skill tells Claude to state in every prompt what Codex may change.
- Runs count against your ChatGPT plan, and OpenAI's terms of use apply to Codex's output. Check them before using it at volume.

## Related projects

If you mainly want code review or coding hand-offs inside a git repository, OpenAI's own Codex plugin for Claude Code ([openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc)) is built for that. This project is for people who already work in the Codex desktop app and want Claude to use its projects and threads, including prefilled prompts you send yourself.

## Development

Run the tests (standard library only, no Codex needed):

```powershell
python -m unittest discover -s tests -v
```

The tests use made-up session records and a made-up app database, never real ones. Issues and pull requests are welcome. macOS and Linux are not planned, but a clean pull request is welcome.

## License

[MIT](LICENSE). Codex, ChatGPT and OpenAI are trademarks of OpenAI; Claude is a trademark of Anthropic.
