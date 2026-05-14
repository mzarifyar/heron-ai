"""In-memory storage abstractions for early Heron development.

"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Deque, Dict, Iterable, List, Optional

from ..schemas.signal import BufferedSignal, SignalContext, SignalPayload


class SignalBuffer:
    """Provides SignalBuffer behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, capacity: int = 512) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.capacity = capacity
        self._buffer: Deque[tuple[datetime, BufferedSignal]] = deque(maxlen=capacity)

    def add(self, context: SignalContext, payload: SignalPayload, annotations: Optional[Dict[str, object]] = None) -> BufferedSignal:
        """Builds add using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        buffered = BufferedSignal(context=context, signal=payload, annotations=annotations or {})
        self._buffer.append((payload.detected_at, buffered))
        return buffered

    def get_recent(self, limit: int = 50) -> List[BufferedSignal]:
        """Gets recent using local state or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        if limit <= 0:
            return []

        length = len(self._buffer)
        if limit >= length:
            iterable: Iterable[tuple[datetime, BufferedSignal]] = self._buffer
        else:
            # Avoid copying the entire deque when limit << len(buffer)
            iterable = list(self._buffer)[-limit:]
        return [buffered for _, buffered in iterable]

    def __len__(self) -> int:
        """Handles len protocol behavior using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        return len(self._buffer)

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._buffer.clear()