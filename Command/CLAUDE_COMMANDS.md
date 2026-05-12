# Claude Code — Complete Command Reference

This file is a personal reference. All commands are typed at the `>` prompt inside a Claude Code session.

---

## Slash Commands

### Session

| Command | What it does | When to use |
|---|---|---|
| `/clear` | Wipes the full conversation history | Starting a new unrelated task; context too large |
| `/compact` | Summarizes + compresses history, keeps key context | Long session getting slow; before a big new task |
| `/exit` / `/quit` | Ends the session | Done working |

---

### Help & Info

| Command | What it does |
|---|---|
| `/help` | Lists all built-in commands and keyboard shortcuts |
| `/status` | Shows current model, token count, session info |
| `/cost` | Token usage + estimated USD cost for this session |
| `/doctor` | Diagnoses your install: auth, version, connectivity |
| `/version` | Shows Claude Code version number |

---

### Configuration

| Command | What it does | Notes |
|---|---|---|
| `/config` | Opens interactive settings menu | Change model, theme, auto-approve rules |
| `/model` | Switch the AI model mid-session | e.g. switch to Opus for harder reasoning |
| `/fast` | Toggle fast mode (Opus 4.6, faster output) | Only works on Opus 4.6 |
| `/theme` | Switch between light / dark / system theme | |

---

### Memory & Context

| Command | What it does | When to use |
|---|---|---|
| `/init` | Reads codebase → generates `CLAUDE.md` | **Run once per new project.** Gives Claude persistent project context |
| `/memory` | Opens your memory files for editing | Review or correct what Claude has learned about you |

> **How CLAUDE.md works:** Claude reads it at the start of every session. It stores commands, architecture notes, conventions. Edit it like any file — Claude will follow whatever is in it.

> **How memory works:** Project-specific facts Claude should always remember (your preferences, project decisions) go here. Stored in `~/.claude/projects/…/memory/`.

---

### Code & Review

| Command | What it does |
|---|---|
| `/review` | Code review of current staged/unstaged diff |
| `/ultrareview` | Deep multi-agent cloud review of current branch |
| `/ultrareview <PR#>` | Deep review of a specific GitHub PR number |

> `/ultrareview` is billed separately (spins up multiple agents). Use for important PRs.

---

### Permissions & Safety

| Command | What it does |
|---|---|
| `/permissions` | Show what tool calls are auto-approved vs need confirmation |

You can also configure auto-approve in `/config` → "Allowed Tools".

---

## Keyboard Shortcuts

These work inside the Claude Code terminal prompt:

| Shortcut | Action |
|---|---|
| `Ctrl + C` | Cancel current Claude response |
| `Ctrl + L` | Clear screen (keeps history) |
| `Up / Down` | Navigate command history |
| `Ctrl + R` | Search command history |
| `Shift + Enter` | New line in your message (without sending) |
| `Tab` | Autocomplete file paths in your message |

---

## Special Prompt Prefixes

These are typed as part of your message, not as slash commands:

| Prefix | What it does | Example |
|---|---|---|
| `!` | Run a shell command directly in the session | `! git status` |
| `#` | Add a note to memory immediately | `# always use tabs not spaces` |
| `@filename` | Reference a file in your message | `@backend/app/main.py what does this route do?` |

> The `!` prefix is very useful — it lets you run interactive shell commands (like `gcloud auth login`) and the output lands directly in the conversation.

---

## MCP (Model Context Protocol) Plugins

MCP servers extend Claude Code with new tools. They are configured in `~/.claude/claude_code_config.json` or via `/config`.

### Check what MCP servers are active

```bash
# View your current MCP config
cat ~/.claude/claude_code_config.json
```

### Common MCP plugin types

| Category | What it adds |
|---|---|
| **Filesystem** | Read/write files beyond the current project |
| **Browser** | Control a real browser, take screenshots, click |
| **Database** | Query Postgres/SQLite directly |
| **GitHub** | Create PRs, read issues, manage repos |
| **Slack / Notion** | Send messages, read docs |
| **Custom** | Any tool you build that follows the MCP spec |

> If an MCP server is active, its tools appear as available tools in Claude's context automatically. You don't need a slash command — just describe what you want.

---

## Settings File Locations

| File | Purpose |
|---|---|
| `~/.claude/CLAUDE.md` | Global instructions (applies to ALL projects) |
| `<project>/CLAUDE.md` | Project-level instructions (checked into git) |
| `~/.claude/claude_code_config.json` | CLI config: MCP servers, theme, model defaults |
| `~/.claude/projects/<hash>/memory/` | Auto-memory for this project |

---

## Most Useful Commands to Learn First

1. **`/init`** — run once in every new project
2. **`/clear`** — fresh context when switching tasks
3. **`/compact`** — keep session alive when it gets long
4. **`/cost`** — track how much you're spending
5. **`! <cmd>`** — run shell commands inline
6. **`/config`** — set auto-approve so Claude doesn't ask permission for every file edit
7. **`/help`** — always there if you forget something
