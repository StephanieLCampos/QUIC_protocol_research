"""
QUIC server implementation for the research project.

The server accepts connections, opens streams, and receives
synthesized data from clients for metric collection.
"""

import asyncio
from typing import Optional, Dict, Callable
from pathlib import Path

from aioquic.asyncio import serve, QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, HandshakeCompleted, ConnectionTerminated


class ServerProtocol(QuicConnectionProtocol):
    """
    QUIC server protocol handler.

    Handles incoming connections and stream data, collecting
    metrics during data reception.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.streams: Dict[int, bytes] = {}
        self.total_bytes_received = 0
        self.handshake_complete = False
        self._data_received_callback: Optional[Callable] = None
        self._connection_callback: Optional[Callable] = None

    def set_data_received_callback(self, callback: Callable):
        """Set callback for when data is received."""
        self._data_received_callback = callback

    def set_connection_callback(self, callback: Callable):
        """Set callback for connection events."""
        self._connection_callback = callback

    def quic_event_received(self, event):
        """Handle QUIC events."""
        if isinstance(event, HandshakeCompleted):
            self.handshake_complete = True
            if self._connection_callback:
                self._connection_callback("handshake_complete")

        elif isinstance(event, StreamDataReceived):
            # Accumulate stream data
            stream_id = event.stream_id
            if stream_id not in self.streams:
                self.streams[stream_id] = b""
            self.streams[stream_id] += event.data
            self.total_bytes_received += len(event.data)

            # Notify callback
            if self._data_received_callback:
                self._data_received_callback(stream_id, len(event.data))

        elif isinstance(event, ConnectionTerminated):
            if self._connection_callback:
                self._connection_callback("connection_terminated")


class QuicServer:
    """
    QUIC server for receiving synthesized data.

    The server listens for connections, receives data on streams,
    and optionally echoes data back for bidirectional testing.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 4433,
        cert_file: str = "certs/cert.pem",
        key_file: str = "certs/key.pem",
        max_ack_delay: float = 0.025,
    ):
        """
        Initialize the QUIC server.

        Args:
            host: Host to bind to.
            port: Port to listen on.
            cert_file: Path to TLS certificate file.
            key_file: Path to TLS private key file.
            max_ack_delay: Maximum ACK delay in seconds.
        """
        self.host = host
        self.port = port
        self.cert_file = Path(cert_file)
        self.key_file = Path(key_file)
        self.max_ack_delay = max_ack_delay

        self._server = None
        self._protocols: list = []
        self._running = False

    def _create_protocol(self, *args, **kwargs) -> ServerProtocol:
        """Create a new server protocol instance."""
        protocol = ServerProtocol(*args, **kwargs)
        self._protocols.append(protocol)
        return protocol

    async def start(self):
        """Start the QUIC server."""
        print(f"[Server] Starting QUIC server on {self.host}:{self.port}", flush=True)
        configuration = QuicConfiguration(
            is_client=False,
            max_datagram_frame_size=65536,
        )

        # Load certificates
        configuration.load_cert_chain(
            str(self.cert_file),
            str(self.key_file),
        )

        # Set max ACK delay
        configuration.max_ack_delay = self.max_ack_delay

        # serve() starts the server and keeps accepting connections.
        # It returns a Server object that needs to be kept alive.
        self._server = await serve(
            self.host,
            self.port,
            configuration=configuration,
            create_protocol=self._create_protocol,
        )
        self._running = True
        print(f"[Server] QUIC server started successfully", flush=True)

    async def stop(self):
        """Stop the QUIC server."""
        if self._server:
            self._server.close()
            self._running = False

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    def get_total_bytes_received(self) -> int:
        """Get total bytes received across all connections."""
        return sum(p.total_bytes_received for p in self._protocols)
