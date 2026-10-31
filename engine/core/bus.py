"""The message bus: how parts of the engine tell each other (and the screens) what happened.

A part "publishes" a message on a topic, such as "tick" or "order". Anything
that "subscribed" to that topic is called with the message. Publishing never
fails because a listener broke: the problem is logged and the others still
get the message.
"""

import logging
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger(__name__)

Listener = Callable[[str, Any], None]


class MessageBus:
    def __init__(self):
        self._listeners: dict[str, list[Listener]] = defaultdict(list)

    def subscribe(self, topic: str, listener: Listener) -> None:
        """Listen to one topic, or to every topic with "*"."""
        self._listeners[topic].append(listener)

    def unsubscribe(self, topic: str, listener: Listener) -> None:
        if listener in self._listeners.get(topic, []):
            self._listeners[topic].remove(listener)

    def publish(self, topic: str, message: Any) -> None:
        for listener in list(self._listeners.get(topic, [])) + list(self._listeners.get("*", [])):
            try:
                listener(topic, message)
            except Exception:  # one broken listener must not stop the others
                log.exception("A listener for '%s' failed", topic)
