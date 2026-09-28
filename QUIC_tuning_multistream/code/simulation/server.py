"""
QUIC server endpoint for the research simulations.

Accepts client connections, accumulates received stream data, and reports the
byte totals used to cross-check client-side throughput. `ServerProtocol`
handles per-connection events; `QuicServer` owns the listening socket and the
set of live protocol instances.

The server exposes callback hooks (`set_data_received_callback`,
`set_connection_callback`) so a harness can observe reception without
subclassing, and echoes a short acknowledgement on client-initiated
bidirectional streams so that round-trip-sensitive workloads such as the
conference-call model have return traffic to measure against.

Connections:
    Imports from: aioquic.asyncio, aioquic.quic
    Imported by:  simulation/__init__.py, simulation.runner,
                  examples.run_app_with_real_bottleneck
    Requires:     TLS certificate and key (see certs/, paths from config.settings)
"""

import asyncio
from typing import Optional, Dict, Callable, Any
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

            # Echo a short acknowledgement so latency- and jitter-sensitive
            # workloads have return traffic to measure against.
            #
            # The stream_id % 4 == 0 test selects client-initiated
            # bidirectional streams: QUIC encodes stream type in the two low
            # bits of the ID, where 0b00 is exactly that class. Echoing on a
            # unidirectional stream would be a protocol violation.
            if stream_id % 4 == 0:
                # Send acknowledgment
                self._quic.send_stream_data(stream_id, b"ACK", end_stream=False)

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

        # serve() is a coroutine that returns a Server object
        self._server = await serve(
            self.host,
            self.port,
            configuration=configuration,
            create_protocol=self._create_protocol,
        )
        self._running = True

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


async def run_server_standalone(
    host: str = "localhost",
    port: int = 4433,
    cert_file: str = "certs/cert.pem",
    key_file: str = "certs/key.pem",
):
    """
    Run the server as a standalone process.

    This is useful for testing or running the server independently.
    """
    server = QuicServer(host, port, cert_file, key_file)
    await server.start()
    print(f"QUIC server listening on {host}:{port}")

    try:
        # Run forever
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(run_server_standalone())
