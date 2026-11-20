---
name: codex-bridge
description: Hand a task, or part of one, to the user's local OpenAI Codex (the Codex desktop app on Windows) and bring the answer back. Codex runs under the user's own ChatGPT account with their Codex skills, plugins and AGENTS.md. You choose the Codex app project and, in background mode, the model and reasoning effort; in visible mode the prompt is prefilled in the app for the user to check and send. Use it when the user explicitly asks for Codex, GPT or ChatGPT to do, draft or check something, e.g. "ask Codex too", "have GPT write a version", "run this in Codex in the background", "put it in Codex so I can look before sending", "let Codex and you both do it and compare", "让 GPT 也做一份", "派给 Codex", "发到 Codex 里我看一下再发送", or names a GPT model for a subtask. Do not use it on your own initiative (it spends the user's ChatGPT quota), for general questions about OpenAI, or to configure or install Codex.
---

# Hand work to the local Codex

The user has the Codex desktop app on Windows. Its bundled `codex.exe` can run tasks headlessly under the user's account. `scripts/codex_task.py` in this skill's folder wraps both ways of using it. Run it with Python 3.8 or newer:

```
python -I "<this skill's folder>/scripts/codex_task.py" <command> ...
```

Use the base directory shown when this skill loaded as `<this skill's folder>`. If `python` is not on PATH, try `py -3`. Every command prints JSON.

| | Background mode (`run`) | Visible mode (`visible`) |
|---|---|---|
| Use for | automated subtasks, "same task to several models" comparisons | tasks the user wants to read, edit or start themselves |
| Model and effort | you choose with `--model` and `--effort` | whatever is selected in the app; the user can change it before sending |
| Who sends | runs at once | the user presses Send in the app |
| In the app's thread list | no, but `open <id>` shows it in the app | yes, as a normal thread |
| Answer comes back | yes | yes, after Send |

Both modes put the thread under the Codex app project that owns the working folder, and both load the same skills and AGENTS.md. Threads started in the app also get a few app-only tools (reading other threads, automations, handoff), which most writing or analysis tasks don't need.

## First use

Run `doctor`. It reports where `codex.exe` is, the Codex version, whether Codex is logged in and whether the app's project list can be read. Fix what `problems` lists before dispatching. If `codex.exe` is not found, the user can open the app once or set `CODEX_EXE`.

## Choose the mode and model

- The user wants it in the background, wants several models compared, or the subtask is routine: use **background**.
- The user wants to see or approve the prompt, pick the model in the app's menu, or keep the thread in their app history: use **visible**.
- If the user named a model or effort, use exactly that. Otherwise run `models`, pick, and say what you picked: a stronger model with higher effort for writing, review or hard reasoning; a smaller model with low effort for lookups, reformatting or simple arithmetic. Leaving `--model` out uses the app's default.
- If `models` shows `service_tier = "priority"` in the app defaults, runs use more quota. Mention it before many or long runs.

## How to dispatch

1. **Write a self-contained prompt.** Codex cannot see this conversation. Give it:
   - the goal and what you want back;
   - the inputs as absolute file paths;
   - what it may change, in words, e.g. "Read only: don't modify any files, don't use the network." Codex runs these tasks without asking for approval, so the prompt and the sandbox are the only guardrails.

   Write it the way the user would brief a colleague. Leave out remarks such as "this was dispatched by another AI": they can colour the answer. In background mode Codex can read its own past threads from `~/.codex/sessions`, so to build on an earlier thread, name it or its topic.
2. **Save the prompt to a UTF-8 file** with your file-writing tool and pass `--prompt-file`. Don't put long or non-ASCII prompts on a PowerShell command line: curly quotes end PowerShell strings, and Windows PowerShell 5.1 re-encodes piped text.
3. **Pick the project.** `--project` takes a project name or a folder path; `projects` lists the names with their folders. If the task doesn't clearly belong to one, ask the user which to use rather than inventing a folder.
4. **Run it.** For anything longer than about a minute, start the command in the background (for example with your shell tool's background option) and get on with your own part.
   ```
   python -I "<this skill's folder>/scripts/codex_task.py" run --project "My project" --prompt-file task.txt --model <slug> --effort high
   python -I "<this skill's folder>/scripts/codex_task.py" visible --project "My project" --prompt-file task.txt
   ```
   In visible mode, tell the user the prefilled thread is open in the Codex app: they can edit the prompt or switch the model, then press Send. The command waits up to `--wait` seconds (default 1800) and returns the answer.
5. **Follow-ups go into the same thread** when the user wants Codex to keep its context:
   - Background: `continue <session_id> --prompt-file F`, optionally with `--model` or `--effort`. This works for any thread, including ones started in the app. If the app has that thread open, Codex refuses a second writer and changes nothing; the result then carries `blocked`, and you switch to the visible way.
   - Visible: `visible --session <session_id> --prompt-file F` prefills the next message in that thread. The user sends it and the answer comes back.
   - Take the session id from an earlier result. Otherwise ask the user which thread they mean.
6. **Report.** Say which model and effort actually ran (from the JSON, not from what you asked for), give or summarise the answer, and offer `open <session_id>` to show the thread. Treat the answer as a colleague's work and check it before relying on it. When comparing answers, judge them on their merits and say where they disagree.

## Limits and safety

- Default to `--sandbox read-only`. Use `workspace-write` only when the user asked Codex to edit files, and name the folder in the prompt. Don't let Codex delete files, push code, or act on remote machines unless the user approved that specific step.
- Don't edit Codex's config, database or session files. The script only reads them.
- Don't save extra copies of answers. Codex keeps its own record of each run in `~/.codex/sessions`; add `--ephemeral` for throwaway runs, which then can't be opened later.
- Background threads don't appear in the app's thread list; `open <id>` shows one.
- Visible-mode links can't choose the model and can't press Send. Prompts longer than about 8000 characters once encoded don't fit in a link; put the material in a file and point to it.
- Usage counts against the user's ChatGPT plan, and OpenAI's terms apply to the output.

## Command reference

- `doctor`: check the setup.
- `projects`: list app projects with their folders.
- `models`: list model slugs, effort levels and the app's defaults.
- `run --project P --prompt-file F [--model M] [--effort E] [--sandbox read-only|workspace-write] [--image IMG] [--ephemeral] [--open] [--timeout S]`
- `visible --project P --prompt-file F [--wait S | --no-wait]`
- `visible --session ID --prompt-file F [--wait S | --no-wait]`: follow-up prefilled in an existing thread.
- `continue ID --prompt-file F [--model M] [--effort E] [--sandbox ...] [--timeout S]`: background follow-up.
- `read ID [--all]`: show the answer, or every answer, of a past session.
- `open ID`: show a session in the app.

`answer` is Codex's final message. `log_tail` appears when something went wrong, and `error` when the script could not start.
