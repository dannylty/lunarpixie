"""Interactive config UI for Telegram inline keyboards.

Handles /configs command and cfg:* callback queries.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TypedDict


class ButtonDict(TypedDict):
    text: str
    callback_data: str

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext
from nanobot.config.loader import get_config_path

# ── Editable settings ────────────────────────────────────────────────

CATEGORIES = {
    "provider": "Provider",
    "channel": "Channel",
    "tools": "Tools",
    "session": "Session",
    "dream": "Dream",
}

# (json_path, display_name, type, description, options_or_range)
# json_path uses dot notation for nested keys in config.json
FIELDS = {
    "provider": [
        ("agents.defaults.model", "Model", "str", "LLM model name", None),
        ("agents.defaults.provider", "Provider", "str", "Provider (custom, openai, ...)", None),
        ("agents.defaults.temperature", "Temperature", "float", "Sampling temperature", (0.0, 2.0, 0.1)),
        ("agents.defaults.context_window_tokens", "Context Window", "int", "Max context tokens", None),
        ("agents.defaults.max_tokens", "Max Output", "int", "Max output tokens", None),
        ("agents.defaults.max_tool_iterations", "Max Iterations", "int", "Max tool call rounds", (1, 2000, 50)),
    ],
    "channel": [
        ("streaming", "Streaming", "bool", "Stream responses globally", None),
        ("channels.telegram.streaming", "TG Streaming", "bool", "Telegram streaming", None),
        ("channels.send_tool_hints", "Tool Hints", "bool", "Show tool usage hints", None),
        ("channels.send_progress", "Progress", "bool", "Show progress indicators", None),
        ("channels.send_perf_hints", "Perf Hints", "bool", "Show perf metrics", None),
    ],
    "tools": [
        ("tools.web.enable", "Web", "bool", "Allow web search/fetch", None),
        ("tools.exec.enable", "Exec", "bool", "Allow shell commands", None),
        ("tools.my.enable", "My", "bool", "Allow self-config", None),
        ("tools.image_generation.enabled", "Image Gen", "bool", "Allow image generation", None),
        ("tools.restrict_to_workspace", "Workspace Only", "bool", "Restrict file access", None),
    ],
    "session": [
        ("agents.defaults.session_ttl_minutes", "Idle Timeout", "int", "Minutes before timeout (0=off)", None),
        ("agents.defaults.max_messages", "Max Messages", "int", "Max msgs per session", None),
        ("agents.defaults.unified_session", "Unified Session", "bool", "Single shared session", None),
        ("agents.defaults.consolidation_ratio", "Consolidation", "float", "Context consolidation ratio", (0.0, 1.0, 0.1)),
    ],
    "dream": [
        ("agents.defaults.dream.interval_h", "Interval", "int", "Hours between runs", None),
        ("agents.defaults.dream.max_iterations", "Max Iterations", "int", "Max iterations per run", None),
        ("agents.defaults.dream.max_batch_size", "Batch Size", "int", "Max lines per batch", None),
        ("agents.defaults.dream.annotate_line_ages", "Line Ages", "bool", "Annotate line ages", None),
    ],
}

# ── Per-user state ───────────────────────────────────────────────────

_editing: dict[str, str] = {}  # sender_id -> field key


# ── Public API ───────────────────────────────────────────────────────

def load_cfg() -> dict[str, Any]:
    """Load current config as a plain dict from disk (raw JSON, no Pydantic)."""
    path = get_config_path()
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cfg(data: dict[str, Any]) -> None:
    """Save config dict to disk."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def handle_callback(
    action: str,
    param: str = "",
    value: str = "",
) -> tuple[str, list[list[ButtonDict]]]:
    """Process a cfg:* callback. Returns (message_text, keyboard_buttons)."""
    if action == "menu":
        return _build_menu()
    if action == "cat":
        return _build_category(param)
    if action == "edit":
        return _build_edit(param)
    if action == "toggle":
        return _do_toggle(param)
    if action == "inc":
        return _do_increment(param, 1)
    if action == "dec":
        return _do_increment(param, -1)
    if action == "input":
        _editing[param] = True
        return _build_input_prompt(param)
    if action == "reset":
        return _do_reset(param)
    if action == "back":
        # param is the category to go back to
        return _build_category(param) if param in CATEGORIES else _build_menu()
    return ("Unknown action", [])


def handle_input(sender_id: str, text: str) -> tuple[str, list[list[ButtonDict]]]:
    """Process text input for a setting being edited."""
    field_key = _editing.pop(sender_id, None)
    if not field_key:
        return ("Not editing any setting. Tap [/configs](/configs) to start.", [])
    return _do_set(field_key, text)


# ── Command handler ──────────────────────────────────────────────────

async def cmd_configs(ctx: CommandContext) -> OutboundMessage | None:
    """Handle /configs command — show the main config menu."""
    cfg = load_cfg()
    content, buttons = _build_menu(cfg)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        buttons=buttons,
    )


def register_config_command(router: CommandRouter) -> None:
    """Register /configs command with the given router."""
    router.register(r"^/configs$", cmd_configs, priority=True)


# ── Button helper ────────────────────────────────────────────────────

def _btn(text: str, data: str) -> dict:
    """Create a button dict with display text and callback data."""
    return {"text": text, "callback_data": f"cfg:{data}"}


# ── View builders ────────────────────────────────────────────────────

def _build_menu(cfg: dict | None = None) -> tuple[str, list[list[dict]]]:
    if cfg is None:
        cfg = load_cfg()
    model = _get_nested(cfg, "agents.defaults.model") or "—"
    temp = _get_nested(cfg, "agents.defaults.temperature") or "—"
    iters = _get_nested(cfg, "agents.defaults.max_tool_iterations") or "—"
    ctx = _get_nested(cfg, "agents.defaults.context_window_tokens") or "—"
    lines = [
        "⚙️ *Config Editor*",
        "",
        f"Model: `{model}`",
        f"Temp: {temp} · Iterations: {iters} · Context: {ctx}",
        "",
    ]
    cat_buttons: list[list[dict]] = [
        [_btn(CATEGORIES[k], f"cat:{k}") for k in list(CATEGORIES.keys())[:3]],
        [_btn(CATEGORIES[k], f"cat:{k}") for k in list(CATEGORIES.keys())[3:]],
        [_btn("❌ Close", "close")],
    ]
    return "\n".join(lines), cat_buttons


def _build_category(cat: str) -> tuple[str, list[list[dict]]]:
    cfg = load_cfg()
    title = CATEGORIES.get(cat, cat.title())
    lines = [f"⚙️ *{title} Settings*", ""]

    for key, name, ftype, desc, _ in FIELDS.get(cat, []):
        val = _get_nested(cfg, key)
        val_str = _format_value(val, ftype)
        lines.append(f"  {name}: `{val_str}` — _{desc}_")

    # Build keyboard: 3 buttons per row
    btn_rows: list[list[dict]] = []
    current_row: list[dict] = []
    for key, name, ftype, _, _ in FIELDS.get(cat, []):
        val = _get_nested(cfg, key)
        val_str = _format_value(val, ftype)
        label = f"{name}: {val_str}"
        current_row.append(_btn(label, f"edit:{key}"))
        if len(current_row) >= 3:
            btn_rows.append(current_row)
            current_row = []
    if current_row:
        btn_rows.append(current_row)
    btn_rows.append([_btn("⬅️ Back", "back:"), _btn("❌ Close", "close")])

    return "\n".join(lines), btn_rows


def _build_edit(field_key: str) -> tuple[str, list[list[dict]]]:
    cfg = load_cfg()
    cat, name, ftype, desc, opts = _find_field(field_key)
    val = _get_nested(cfg, field_key)
    val_str = _format_value(val, ftype)

    lines = [
        f"⚙️ *{name}*",
        f"_Current: `{val_str}`_",
        f"_({desc})_",
        "",
    ]
    buttons: list[list[dict]] = []

    if ftype == "bool":
        buttons.append([_btn(f"✅ Toggle (→ {str(not val).capitalize()})", f"toggle:{field_key}")])
    elif ftype in ("int", "float"):
        step = (opts[2] if opts and len(opts) > 2 else 1)
        buttons.append([
            _btn(f"➖ -{step}", f"dec:{field_key}"),
            _btn(f"➕ +{step}", f"inc:{field_key}"),
        ])
    buttons.append([_btn("✏️ Set Custom", f"input:{field_key}")])
    if opts:
        buttons.append([_btn("🔄 Reset", f"reset:{field_key}")])
    buttons.append([_btn(f"⬅️ {CATEGORIES.get(cat, cat)}", f"back:{cat}")])

    return "\n".join(lines), buttons


def _build_input_prompt(field_key: str) -> tuple[str, list[list[dict]]]:
    _, name, ftype, desc, _ = _find_field(field_key)
    type_hint = {"int": "number", "float": "number", "str": "text", "bool": "true/false"}.get(ftype, "text")
    return (
        f"✏️ *Set {name}*\n\n"
        f"Reply with the new {type_hint} value.\n"
        f"_({desc})_\n\n"
        f"Or tap Cancel to abort.",
        [_btn("❌ Cancel", f"back:{_find_field(field_key)[0]}")],
    )


# ── Actions ──────────────────────────────────────────────────────────

def _do_toggle(field_key: str) -> tuple[str, list[list[dict]]]:
    cfg = load_cfg()
    cat, name, _, desc, _ = _find_field(field_key)
    old = _get_nested(cfg, field_key)
    if old is None:
        old = False
    _set_nested(cfg, field_key, not old)
    save_cfg(cfg)
    val_str = _format_value(not old, "bool")
    return (
        f"✅ *{name}* → `{val_str}`\n_({desc})_",
        [
            [_btn(f"⬅️ {CATEGORIES.get(cat, cat)}", f"back:{cat}"), _btn("🏠 Home", "menu")],
        ],
    )


def _do_increment(field_key: str, direction: int) -> tuple[str, list[list[dict]]]:
    cfg = load_cfg()
    cat, name, ftype, desc, opts = _find_field(field_key)
    val = _get_nested(cfg, field_key)
    if val is None:
        val = _default_value(ftype, opts)
    step = (opts[2] if opts and len(opts) > 2 else 1)
    new_val = val + direction * step
    if opts and len(opts) >= 2:
        new_val = max(opts[0], min(opts[1], new_val))
    if ftype == "int":
        new_val = int(new_val)
    _set_nested(cfg, field_key, new_val)
    save_cfg(cfg)
    val_str = _format_value(new_val, ftype)
    return (
        f"📊 *{name}* → `{val_str}`\n_({desc})_",
        [
            [
                _btn(f"➖ -{step}", f"dec:{field_key}"),
                _btn(f"➕ +{step}", f"inc:{field_key}"),
            ],
            [_btn(f"⬅️ {CATEGORIES.get(cat, cat)}", f"back:{cat}"), _btn("🏠 Home", "menu")],
        ],
    )


def _do_set(field_key: str, raw: str) -> tuple[str, list[list[dict]]]:
    cfg = load_cfg()
    cat, name, ftype, desc, opts = _find_field(field_key)
    try:
        if ftype == "int":
            new_val = int(raw)
        elif ftype == "float":
            new_val = float(raw)
        elif ftype == "bool":
            new_val = raw.lower() in ("true", "yes", "on", "1")
        else:
            new_val = raw
    except (ValueError, TypeError):
        return (f"❌ Invalid value `{raw}` for {name}. Please enter a valid {ftype}.", [])

    _set_nested(cfg, field_key, new_val)
    save_cfg(cfg)
    val_str = _format_value(new_val, ftype)
    restart = _needs_restart(field_key)
    note = "\n⚠️ *Restart required* for this change to take effect." if restart else ""
    return (
        f"✅ *{name}* → `{val_str}`\n_({desc})_{note}",
        [
            [_btn(f"⬅️ {CATEGORIES.get(cat, cat)}", f"back:{cat}"), _btn("🏠 Home", "menu")],
        ],
    )


def _do_reset(field_key: str) -> tuple[str, list[list[dict]]]:
    cfg = load_cfg()
    _, name, ftype, desc, opts = _find_field(field_key)
    default = _default_value(ftype, opts)
    _set_nested(cfg, field_key, default)
    save_cfg(cfg)
    val_str = _format_value(default, ftype)
    cat = _find_field(field_key)[0]
    return (
        f"🔄 *{name}* → `{val_str}` (default)\n_({desc})_",
        [
            [_btn(f"⬅️ {CATEGORIES.get(cat, cat)}", f"back:{cat}"), _btn("🏠 Home", "menu")],
        ],
    )


# ── Helpers ──────────────────────────────────────────────────────────

def _find_field(key: str) -> tuple[str, str, str, str, Any]:
    """Return (category, name, type, desc, opts) for a field key."""
    for cat, fields in FIELDS.items():
        for field in fields:
            if field[0] == key:
                return (cat, field[1], field[2], field[3], field[4])
    raise KeyError(f"Unknown field: {key}")


def _get_nested(cfg: dict, path: str) -> Any:
    """Get a config value using dot-notation path (e.g., 'agents.defaults.model')."""
    keys = path.split(".")
    current = cfg
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _set_nested(cfg: dict, path: str, value: Any) -> None:
    """Set a config value using dot-notation path, creating intermediate dicts as needed."""
    keys = path.split(".")
    current = cfg
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def _format_value(val: Any, ftype: str) -> str:
    if val is None:
        return "—"
    if ftype == "bool":
        return "On" if val else "Off"
    if ftype == "int" and isinstance(val, (int, float)):
        return str(int(val))
    if ftype == "float" and isinstance(val, (int, float)):
        return f"{val:.2f}".rstrip("0").rstrip(".")
    return str(val)


def _default_value(ftype: str, opts: Any) -> Any:
    if ftype == "bool":
        return False
    if ftype == "int":
        return opts[0] if opts and len(opts) >= 1 else 0
    if ftype == "float":
        return opts[0] if opts and len(opts) >= 1 else 0.0
    return ""


def _needs_restart(field_key: str) -> bool:
    """Check if a setting change requires a restart."""
    restart_fields = {"model", "api_key", "provider", "base_url"}
    return field_key in restart_fields
