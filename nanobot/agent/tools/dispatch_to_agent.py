"""Tool for handing a task off to another nanobot agent over NATS.

Used by a coordinator (e.g. papapixie) to route work to a specialist agent
running as a separately deployed nanobot instance/container, when the two
can't talk over the chat platform directly — Telegram never delivers one
bot's messages to another bot in the same chat, so @mentioning a specialist
bot doesn't work. See ``nanobot/channels/nats/runtime.py`` for the consumer
side that receives what this tool publishes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.schema import ObjectSchema, StringSchema, tool_parameters_schema
from nanobot.channels.nats.runtime import NatsConfig

_PARAMETERS = tool_parameters_schema(
    agent=StringSchema(
        "Target agent's configured channels.nats agentName (e.g. 'lunarpixie', 'lusterpixie', 'lucida')."
    ),
    group_id=StringSchema(
        "Telegram chat/group id the target agent should reply into — normally the "
        "chat_id of the current session, i.e. the group this task came from."
    ),
    message=StringSchema("Task or instruction for the target agent to execute."),
    sender_label=StringSchema(
        "Optional label identifying who/what is dispatching this. Defaults to this bot's own name."
    ),
    metadata=ObjectSchema(description="Optional extra key/value context passed through to the target agent."),
    required=["agent", "group_id", "message"],
)


@tool_parameters(_PARAMETERS)
class DispatchToAgentTool(Tool):
    """Publish a routed task envelope to a specialist agent over NATS."""

    def __init__(self, nats_config: NatsConfig, *, bot_name: str | None = None):
        self._config = nats_config
        self._bot_name_override = bot_name
        self._nc: Any = None
        self._connect_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "dispatch_to_agent"

    @property
    def description(self) -> str:
        return (
            "Hand a task off to another nanobot agent (a separately deployed bot "
            "persona) so it executes the task and replies directly in a Telegram "
            "group under its own identity. Use this instead of @mentioning another "
            "bot — bots cannot see each other's messages on Telegram, so a mention "
            "alone will never reach them."
        )

    @staticmethod
    def _load_nats_config() -> NatsConfig:
        from nanobot.config.loader import load_config, resolve_config_env_vars

        # load_config() alone leaves ``${VAR}`` placeholders unresolved — that
        # substitution only happens when a caller explicitly asks for it (the
        # channel manager does this for enabled channels before constructing
        # them). Tools reading config directly must do the same, or secrets
        # like the NATS token get passed through as the literal "${...}" text.
        config = resolve_config_env_vars(load_config())
        raw = getattr(config.channels, "nats", None)
        return NatsConfig.model_validate(raw or {})

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return cls._load_nats_config().publish_enabled

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        # bot_name is resolved lazily: loading the full config here would add a
        # second load_config() call during tool-registry construction.
        return cls(cls._load_nats_config())

    @property
    def _bot_name(self) -> str:
        if self._bot_name_override is not None:
            return self._bot_name_override
        from nanobot.config.loader import load_config

        self._bot_name_override = load_config().agents.defaults.bot_name or "coordinator"
        return self._bot_name_override

    async def _connection(self) -> Any:
        import nats  # deferred: only required when dispatch_to_agent is enabled

        async with self._connect_lock:
            if self._nc is None or self._nc.is_closed:
                token = self._config.token
                logger.info(
                    "dispatch_to_agent connecting: servers={} token_len={} token_prefix={!r}",
                    self._config.servers, len(token), token[:4],
                )
                self._nc = await nats.connect(
                    servers=self._config.servers,
                    token=token or None,
                    name=f"nanobot-{self._bot_name}-dispatch",
                    allow_reconnect=False,
                    connect_timeout=5,
                )
            return self._nc

    async def execute(
        self,
        agent: str,
        group_id: str,
        message: str,
        sender_label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        agent = agent.strip()
        if not agent:
            return ToolResult.error("agent is required")
        if not str(group_id).strip():
            return ToolResult.error("group_id is required")
        if not message.strip():
            return ToolResult.error("message is required")
        if not self._config.servers:
            return ToolResult.error("channels.nats.servers is empty — NATS is not configured")

        subject = f"{self._config.subject_prefix}.{agent}.inbound"
        envelope = {
            "group_id": str(group_id),
            "content": message,
            "sender_id": sender_label or self._bot_name,
            "from": self._bot_name,
            "metadata": metadata or {},
        }
        try:
            nc = await self._connection()
            await nc.publish(subject, json.dumps(envelope).encode("utf-8"))
            await nc.flush()
        except Exception as exc:
            logger.exception("Failed to dispatch task to agent '{}'", agent)
            return ToolResult.error(f"Failed to dispatch to '{agent}': {exc}")
        return f"Dispatched task to '{agent}' (subject {subject}), targeting group {group_id}."
