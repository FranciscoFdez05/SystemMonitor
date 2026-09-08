from .base import Sink, format_message
from .http_sinks import DiscordSink, TelegramSink, WebhookSink
from .log_sink import LogSink

SINKS: dict[str, Sink] = {
    sink.name: sink for sink in (LogSink(), WebhookSink(), TelegramSink(), DiscordSink())
}

__all__ = ["SINKS", "Sink", "format_message"]
