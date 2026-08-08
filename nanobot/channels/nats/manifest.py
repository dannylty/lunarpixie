"""NATS bridge channel management contract."""

from nanobot.channels._manifest import field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "servers": field("list", default=["nats://127.0.0.1:4222"]),
        "token": field("secret"),
        "agentName": field("string"),
        "subjectPrefix": field("string", default="nanobot.agents"),
        "publishEnabled": field("bool", default=False),
    },
    required=(required("servers"), required("agentName")),
)

PLUGIN = ChannelPlugin(
    name="nats",
    display_name="NATS Bridge",
    runtime=f"{__package__}.runtime:NatsChannel",
    setup=SETUP_SPEC,
    dependencies=(
        "nats-py>=2.7.0,<3.0.0",
    ),
)
