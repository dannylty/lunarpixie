---
name: memory
description: Two-layer memory system with Dream-managed knowledge files.
always: true
---

# Memory

## Structure

- `.nanobot/SOUL.md` — Bot personality and communication style. **Managed by Dream.** Do NOT edit.
- `.nanobot/USER.md` — User profile and preferences. **Managed by Dream.** Do NOT edit.
- `.nanobot/memory/MEMORY.md` — Long-term facts (project context, important events). **Managed by Dream.** Do NOT edit.
- `.nanobot/memory/history.jsonl` — append-only JSONL, not loaded into context. Prefer the built-in `grep` tool to search it.

## Search Past Events

`.nanobot/memory/history.jsonl` is JSONL format — each line is a JSON object with `cursor`, `timestamp`, `content`.

- For broad searches, start with `grep(..., path=".nanobot/memory", glob="*.jsonl", output_mode="count")` or the default `files_with_matches` mode before expanding to full content
- Use `output_mode="content"` plus `context_before` / `context_after` when you need the exact matching lines
- Use `fixed_strings=true` for literal timestamps or JSON fragments
- Use `head_limit` / `offset` to page through long histories
- Use `exec` only as a last-resort fallback when the built-in search cannot express what you need

Examples (replace `keyword`):
- `grep(pattern="keyword", path=".nanobot/memory/history.jsonl", case_insensitive=true)`
- `grep(pattern="2026-04-02 10:00", path=".nanobot/memory/history.jsonl", fixed_strings=true)`
- `grep(pattern="keyword", path=".nanobot/memory", glob="*.jsonl", output_mode="count", case_insensitive=true)`
- `grep(pattern="oauth|token", path=".nanobot/memory", glob="*.jsonl", output_mode="content", case_insensitive=true)`

## Important

  - **Do NOT edit SOUL.md, USER.md, or MEMORY.md.** They are automatically managed by Dream.
- If you notice outdated information, it will be corrected when Dream runs next.
