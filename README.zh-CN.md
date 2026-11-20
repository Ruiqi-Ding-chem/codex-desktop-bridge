# codex-desktop-bridge

[English](README.md)

这是一个 Claude Code 的 skill。Claude 可以用它把任务（或任务的一部分）交给 **Windows 上的 OpenAI Codex 桌面应用**去做，再把回答拿回来。可以用来让 GPT 另写一稿，让 Codex 检查 Claude 的结果，或者让两边做同一个任务再比较。

Codex 用的是你自己的 ChatGPT 账号，也会加载你在 Codex 里的 skill、插件和 `AGENTS.md`。不需要 API key、Node，也不需要额外的 Python 包：skill 直接调用桌面应用自带的 `codex.exe`。

> 非官方项目，与 OpenAI 和 Anthropic 无关，也没有得到它们的认可。只支持 Windows。

## 可以这样跟 Claude 说

- “让 Codex 也写一版这一节，然后和你的比较一下。”
- “在后台让 Codex 用 high 强度检查一遍。”
- “把提示词发到 Codex 里，我先看一下再发送。”
- “接着刚才那个 Codex 对话，让它把总结缩短一点。”

只有你明确提到 Codex、GPT 或 ChatGPT 时，Claude 才会用这个 skill，不会自己主动用，因为每次运行都会消耗你的 ChatGPT 额度。

## 两种模式

| | 后台模式（`run`） | 可见模式（`visible`） |
|---|---|---|
| 适合 | 自动化的子任务、多模型比较 | 想先看、改或确认提示词的任务 |
| 模型和推理强度 | 每次运行时指定 | 用应用里选中的模型 |
| 谁点发送 | 不用点，立即运行 | 你在应用里点 |
| 是否出现在应用的对话列表 | 不出现（Claude 可以用链接打开） | 出现 |
| 回答能否回到 Claude | 能 | 能，在你发送之后 |

两种模式都会把对话放在拥有该工作文件夹的 Codex 项目下。两种模式都可以在同一条对话里接着问。

## 需要什么

- Windows 10 或 11。
- 已安装并登录的 Codex 桌面应用。只有 npm 装的 Codex CLI 也能用后台模式，但可见模式需要桌面应用。
- [Claude Code](https://claude.com/claude-code)。
- PATH 里有 Python 3.8 或更新版本（`python` 或 `py -3`）。只用标准库。

## 安装

在 Claude Code 里作为插件安装：

```
/plugin marketplace add Ruiqi-Ding-chem/codex-desktop-bridge
/plugin install codex-desktop-bridge@codex-desktop-bridge
```

或者手动安装：把 `skills/codex-bridge` 文件夹复制到 `%USERPROFILE%\.claude\skills\`，复制后应该有 `%USERPROFILE%\.claude\skills\codex-bridge\SKILL.md` 这个文件。

装好后检查一下环境。可以跟 Claude 说“检查一下 Codex bridge 的设置”，或者直接运行：

```powershell
python -I "$env:USERPROFILE\.claude\skills\codex-bridge\scripts\codex_task.py" doctor
```

`doctor` 会报告 `codex.exe` 的位置、Codex 版本、是否已登录，以及能否读到应用的项目列表。如果找不到 `codex.exe`，先打开一次应用，或者把环境变量 `CODEX_EXE` 设为它的完整路径。

## 工作原理

- **后台模式**运行 `codex exec`（接着问时用 `codex exec resume`），模型、推理强度、沙箱和工作文件夹都由 Claude 指定。提示词以 UTF-8 从 stdin 传入，长提示词和中文都不会乱码。回答、实际用的模型和强度，从 Codex 自己在 `~/.codex/sessions` 里的会话记录读取。
- **可见模式**打开一个 `codex://threads/new?path=…&prompt=…` 链接，应用会在对应的项目里新建一条对话并填好提示词。脚本等你点发送，然后用同样的方式取回回答。
- **项目名**从应用的本地数据库读取，只读打开。

脚本输出 JSON 给 Claude 读，自己不写任何文件。Codex 照常保存它的会话记录。只有 Claude 传了 `--sandbox workspace-write`，Codex 才会改文件；skill 规定只有你要求 Codex 改文件时才这样做。

## 限制

- 后台模式的对话不会出现在应用的对话列表里，因为应用会过滤掉从命令行启动的对话。Claude 仍然可以用链接打开它。
- 可见模式的链接不能选模型，也不能自动发送。提示词必须放得进链接（编码后约 8000 个字符），更长的材料放进文件，在提示词里指向这个文件。
- 如果应用当前打开着某条对话，Codex 会拒绝在后台往这条对话里追加消息。脚本会返回 `blocked`，什么都不改，这时可以改用可见模式追问。
- `codex exec` 是 OpenAI 为脚本调用写了文档的命令。`codex://` 链接和应用数据库的结构没有公开文档，应用更新后可能变化。如果更新后出了问题，请先运行 `doctor`，然后开一个 issue。

测试环境：Windows 11，Codex 桌面应用 26.1111（codex-cli 0.169.1）。

## 隐私与安全

- 除了 Codex 运行提示词时自己发给 OpenAI 的内容，不会向任何地方发送数据。
- 默认沙箱是只读的，skill 要求 Claude 在每个提示词里写明 Codex 可以改什么。
- 运行会计入你的 ChatGPT 额度，Codex 的输出受 OpenAI 使用条款约束。大量使用前请先看一下条款。

## 相关项目

如果你主要想在 git 仓库里做代码审查或把编程任务交给 Codex，OpenAI 官方的 Claude Code 插件（[openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc)）就是为此做的。本项目面向已经在用 Codex 桌面应用的人，让 Claude 能使用应用里的项目和对话，包括填好提示词、由你自己发送。

## 开发

运行测试（只用标准库，不需要安装 Codex）：

```powershell
python -m unittest discover -s tests -v
```

测试只用虚构的会话记录和虚构的应用数据库，不用真实数据。欢迎提 issue 和 pull request。没有计划支持 macOS 和 Linux，但欢迎干净的 pull request。

## 许可证

[MIT](LICENSE)。Codex、ChatGPT 和 OpenAI 是 OpenAI 的商标，Claude 是 Anthropic 的商标。
