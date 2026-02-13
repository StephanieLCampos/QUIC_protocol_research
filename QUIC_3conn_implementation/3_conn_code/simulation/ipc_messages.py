"""
IPC message definitions for inter-process communication.

Defines message types and formats for communication between
the main process (orchestrator) and worker processes.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class MessageType(Enum):
    """Types of messages exchanged between processes."""

    # Commands (Main -> Worker)
    START = "start"
    STOP = "stop"
    UPDATE_PARAM = "update_param"
    UPDATE_MULTIPLE_PARAMS = "update_multiple_params"
    GET_METRICS = "get_metrics"
    GET_BUFFER_STATE = "get_buffer_state"

    # Responses (Worker -> Main)
    METRICS = "metrics"
    STATUS = "status"
    ACK = "ack"
    ERROR = "error"
    FINISHED = "finished"
    BUFFER_STATE = "buffer_state"


@dataclass
class IPCMessage:
    """Standard message format for IPC."""

    msg_type: MessageType
    connection_id: int  # 1, 2, or 3
    timestamp: float
    payload: Dict[str, Any]

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "msg_type": self.msg_type.value,
            "connection_id": self.connection_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IPCMessage":
        """Create from dictionary."""
        return cls(
            msg_type=MessageType(data["msg_type"]),
            connection_id=data["connection_id"],
            timestamp=data["timestamp"],
            payload=data["payload"],
        )
