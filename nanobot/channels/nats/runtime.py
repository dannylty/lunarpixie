"""NATS bridge channel.

Lets separately-deployed nanobot agents hand a task to one another without
relying on the chat platform to deliver bot-to-bot messages. Telegram, in
particular, never delivers one bot's messages to another bot in the same
chat/group — so a coordinator agent (e.g. papapixie) can't just @mention a
specialist bot and expect it to see the message.

Coordinator side: the ``dispatch_to_agent`` tool
(``nanobot/agent/tools/dispatch_to_agent.py``) publishes a JSON envelope to
``<subjectPrefix>.<agent>.inbound``.

Specialist side (this channel): subscribes to its own subject and injects the
envelope as a normal turn — but tagged with ``channel="telegram"`` rather than
``channel="nats"``. That's deliberate, not a bug: every reply and every
progress/tool/perf-hint message this turn produces is stamped with the same
``channel``/``chat_id`` as the InboundMessage that started it
(see ``nanobot/bus/progress.py``), and gets dispatched to whichever
``BaseChannel`` is registered under that channel name
(``nanobot/channels/manager.py:_dispatch_outbound``). Using ``"telegram"``
here means the reply — and all its hints — flow back out through *this
container's own, already-configured* Telegram channel/bot, into the
originating group. This channel's own ``send()`` is essentially unused.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field, model_validator

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base

DEFAULT_SUBJECT_PREFIX = "nanobot.agents"


class NatsConfig(Base):
    """NATS bridge configuration.

    Both roles read the same ``channels.nats`` config section:

    - Consumer (a specialist container): set ``enabled: true`` and
      ``agentName`` to subscribe and receive dispatched tasks.
    - Producer (the coordinator container): set ``publishEnabled: true`` to
      expose the ``dispatch_to_agent`` tool. It does not need ``agentName``
      and should leave ``enabled: false`` (it isn't itself a dispatch target).
    """

    enabled: bool = False
    publish_enabled: bool = False
    agent_name: str = ""
    servers: list[str] = Field(default_factory=lambda: ["nats://127.0.0.1:4222"])
    token: str = ""
    subject_prefix: str = DEFAULT_SUBJECT_PREFIX

    @model_validator(mode="after")
    def _validate_agent_name(self) -> "NatsConfig":
        if self.enabled and not self.agent_name.strip():
            raise ValueError("channels.nats.agentName is required when channels.nats.enabled is true")
        return self

    @property
    def inbound_subject(self) -> str:
        return f"{self.subject_prefix}.{self.agent_name}.inbound"

    @property
    def status_subject(self) -> str:
        return f"{self.subject_prefix}.{self.agent_name}.status"


class NatsChannel(BaseChannel):
    """Subscribes to routed task envelopes and injects them as Telegram-routed turns."""

    name = "nats"
    display_name = "NATS Bridge"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return NatsConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = NatsConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: NatsConfig = config
        self._nc: Any = None
        self._sub: Any = None

    async def start(self) -> None:
        import nats  # deferred: only required when this channel is enabled

        if not self.config.agent_name.strip():
            raise RuntimeError("nats channel requires channels.nats.agentName to be set")

        self._nc = await nats.connect(
            servers=self.config.servers,
            token=self.config.token or None,
            name=f"nanobot-{self.config.agent_name}",
        )
        self._running = True
        subject = self.config.inbound_subject
        self._sub = await self._nc.subscribe(subject, cb=self._on_message)
        self.logger.info("NATS bridge listening on {}", subject)

    async def stop(self) -> None:
        self._running = False
        sub, self._sub = self._sub, None
        if sub is not None:
            try:
                await sub.unsubscribe()
            except Exception as exc:
                self.logger.warning("Error unsubscribing from NATS: {}", exc)
        nc, self._nc = self._nc, None
        if nc is not None:
            try:
                await nc.drain()
            except Exception as exc:
                self.logger.warning("Error draining NATS connection: {}", exc)

    async def _on_message(self, msg: Any) -> None:
        try:
            envelope = json.loads(msg.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.logger.warning("Dropping malformed NATS envelope: {}", exc)
            return
        if not isinstance(envelope, dict):
            self.logger.warning("Dropping non-object NATS envelope")
            return

        group_id = str(envelope.get("group_id") or "").strip()
        content = str(envelope.get("content") or "").strip()
        if not group_id or not content:
            self.logger.warning("Dropping NATS envelope missing group_id/content: {}", envelope)
            return

        sender_id = str(envelope.get("sender_id") or envelope.get("from") or "coordinator")
        raw_metadata = envelope.get("metadata")
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        metadata["_relayed_via"] = "nats"
        metadata["_relay_from"] = str(envelope.get("from") or "")

        # channel="telegram" (not self.name) is deliberate — see module docstring.
        # Authorization here is enforced by NATS server auth (token) and subject
        # scoping, not BaseChannel.is_allowed(): publishing directly to
        # bus.inbound bypasses that check entirely, unlike _handle_message().
        inbound = InboundMessage(
            channel="telegram",
            sender_id=sender_id,
            chat_id=group_id,
            content=content,
            metadata=metadata,
        )
        await self.bus.publish_inbound(inbound)

    async def send(self, msg: OutboundMessage) -> None:
        """Not part of the normal flow — replies exit via the Telegram channel.

        Only reached if something explicitly targets ``channel="nats"``.
        Publishes a best-effort status event instead of silently dropping it.
        """
        if self._nc is None:
            self.logger.warning("nats channel.send() called while disconnected; dropping message to {}", msg.chat_id)
            return
        payload = json.dumps({"chat_id": msg.chat_id, "content": msg.content}).encode("utf-8")
        await self._nc.publish(self.config.status_subject, payload)
