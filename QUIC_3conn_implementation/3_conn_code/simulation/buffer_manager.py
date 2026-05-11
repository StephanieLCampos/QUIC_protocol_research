"""
Buffer manager for send buffer visualization.

Provides a thread-safe send buffer for monitoring packet queues
in the UI (read-only observation).
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from collections import deque
import threading
import time


@dataclass
class BufferPacket:
    """A packet in the send buffer."""
    data: bytes
    size: int
    packet_type: str
    timestamp: float = field(default_factory=time.time)


class SendBuffer:
    """
    Thread-safe send buffer for a QUIC connection.

    The buffer holds packets waiting to be sent. The synthesizer adds
    packets automatically. The UI can observe the buffer state (read-only).
    """

    def __init__(self, max_size: int = 1000):
        self._buffer: deque = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._total_added = 0
        self._total_sent = 0

    def add_packet(self, packet: BufferPacket):
        """Add a packet to the buffer (called by synthesizer)."""
        with self._lock:
            self._buffer.append(packet)
            self._total_added += 1

    def get_packet(self) -> Optional[BufferPacket]:
        """Get and remove the next packet to send (FIFO)."""
        with self._lock:
            if self._buffer:
                self._total_sent += 1
                return self._buffer.popleft()
            return None

    def peek(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Peek at the first N packets without removing them.

        Returns summary info suitable for UI display.
        """
        with self._lock:
            packets = []
            for i, pkt in enumerate(self._buffer):
                if i >= count:
                    break
                packets.append({
                    "size": pkt.size,
                    "type": pkt.packet_type,
                    "age_ms": (time.time() - pkt.timestamp) * 1000,
                })
            return packets

    def get_state(self) -> Dict[str, Any]:
        """Get current buffer state for UI display."""
        with self._lock:
            sizes = [p.size for p in self._buffer]
            return {
                "queue_length": len(self._buffer),
                "total_bytes": sum(sizes),
                "total_added": self._total_added,
                "total_sent": self._total_sent,
                "pending_bytes": sum(sizes),
                "packet_types": self._count_types(),
            }

    def _count_types(self) -> Dict[str, int]:
        """Count packets by type."""
        counts = {}
        for pkt in self._buffer:
            counts[pkt.packet_type] = counts.get(pkt.packet_type, 0) + 1
        return counts

    def clear(self):
        """Clear all packets from the buffer."""
        with self._lock:
            self._buffer.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)


class BufferManager:
    """
    Manages send buffers for all connections.

    Provides a centralized view of buffer states for UI display.
    """

    def __init__(self):
        self._buffers: Dict[int, SendBuffer] = {}

    def create_buffer(self, connection_id: int, max_size: int = 1000) -> SendBuffer:
        """Create a new buffer for a connection."""
        buffer = SendBuffer(max_size=max_size)
        self._buffers[connection_id] = buffer
        return buffer

    def get_buffer(self, connection_id: int) -> Optional[SendBuffer]:
        """Get buffer for a specific connection."""
        return self._buffers.get(connection_id)

    def get_all_states(self) -> Dict[int, Dict[str, Any]]:
        """Get states for all buffers."""
        return {
            conn_id: buffer.get_state()
            for conn_id, buffer in self._buffers.items()
        }

    def clear_all(self):
        """Clear all buffers."""
        for buffer in self._buffers.values():
            buffer.clear()
