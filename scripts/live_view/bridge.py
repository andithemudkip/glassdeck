"""Thread-safe handoff between the capture thread and the Textual main thread."""

from __future__ import annotations

import queue
import threading


class LiveBridge:
    """Thread-safe handoff between the capture thread (frame producer +
    serial read) and the Textual main thread (UI + keyboard)."""

    def __init__(self) -> None:
        self.frame_q: queue.Queue[tuple[float, int, bytes]] = queue.Queue(maxsize=20000)
        self.stop = threading.Event()
        self.dropped = 0

    def feed_frame(self, ts: float, arb_id: int, data: bytes) -> None:
        try:
            self.frame_q.put_nowait((ts, arb_id, data))
        except queue.Full:
            self.dropped += 1
