"""
QUIC client implementation for the research project.

The client connects to the server, opens streams, and sends
synthesized data while collecting metrics.
"""

import asyncio
import time
from typing import Optional, List, AsyncIterator

from aioquic.asyncio import connect, QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, HandshakeCompleted


class ClientProtocol(QuicConnectionProtocol):
    """
    QUIC client protocol handler.

    Handles stream operations and tracks metrics during
    data transmission.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handshake_complete = asyncio.Event()
        self.streams_opened: List[int] = []
        self.bytes_received = 0
        self.receive_timestamps: List[float] = []

    def quic_event_received(self, event):
        """Handle QUIC events."""
        if isinstance(event, HandshakeCompleted):
            self.handshake_complete.set()

        elif isinstance(event, StreamDataReceived):
            self.bytes_received += len(event.data)
            self.receive_timestamps.append(time.time())

    async def wait_handshake(self, timeout: float = 10.0):
        """Wait for handshake to complete."""
        await asyncio.wait_for(self.handshake_complete.wait(), timeout=timeout)

    def open_stream(self) -> int:
        """
        Open a new bidirectional stream.

        Returns:
            The stream ID.
        """
        stream_id = self._quic.get_next_available_stream_id()
        self.streams_opened.append(stream_id)
        return stream_id

    def send_data(self, stream_id: int, data: bytes, end_stream: bool = False):
        """
        Send data on a stream.

        Args:
            stream_id: The stream to send on.
            data: The data to send.
            end_stream: Whether to close the stream after sending.
        """
        self._quic.send_stream_data(stream_id, data, end_stream=end_stream)

    def get_rtt(self) -> Optional[float]:
        """Get the current smoothed RTT."""
        try:
            return self._quic._loss._rtt_smoothed
        except AttributeError:
            return None

    def get_connection_stats(self) -> dict:
        """Get connection statistics."""
        try:
            loss = self._quic._loss
            return {
                "rtt_smoothed": getattr(loss, "_rtt_smoothed", 0),
                "rtt_min": getattr(loss, "_rtt_min", 0),
                "congestion_window": getattr(loss, "congestion_window", 0),
                "bytes_in_flight": getattr(loss, "bytes_in_flight", 0),
            }
        except AttributeError:
            return {}


class QuicClient:
    """
    QUIC client for sending synthesized data.

    The client connects to a server, opens streams as required,
    and sends data through them while collecting metrics.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 4433,
        max_ack_delay: float = 0.025,
        verify_cert: bool = False,
    ):
        """
        Initialize the QUIC client.

        Args:
            host: Server host to connect to.
            port: Server port.
            max_ack_delay: Maximum ACK delay in seconds.
            verify_cert: Whether to verify server certificate.
        """
        self.host = host
        self.port = port
        self.max_ack_delay = max_ack_delay
        self.verify_cert = verify_cert

        self._protocol: Optional[ClientProtocol] = None
        self._connection_cm = None

    async def connect(self) -> ClientProtocol:
        """
        Connect to the QUIC server.

        Returns:
            The client protocol instance.
        """
        configuration = QuicConfiguration(
            is_client=True,
            max_datagram_frame_size=65536,
        )

        # Set max ACK delay
        configuration.max_ack_delay = self.max_ack_delay

        # Disable certificate verification for testing
        if not self.verify_cert:
            configuration.verify_mode = False

        # connect() returns an async context manager
        self._connection_cm = connect(
            self.host,
            self.port,
            configuration=configuration,
            create_protocol=ClientProtocol,
        )
        # Enter the context manager
        self._protocol = await self._connection_cm.__aenter__()

        # Wait for handshake
        await self._protocol.wait_handshake()

        return self._protocol

    async def open_streams(self, count: int = 3) -> List[int]:
        """
        Open multiple streams.

        Args:
            count: Number of streams to open.

        Returns:
            List of stream IDs.
        """
        if self._protocol is None:
            raise RuntimeError("Not connected. Call connect() first.")

        stream_ids = []
        for _ in range(count):
            stream_id = self._protocol.open_stream()
            stream_ids.append(stream_id)

        return stream_ids

    async def send_synthesized_data(
        self,
        stream_id: int,
        data_generator: AsyncIterator,
        metrics_collector=None,
    ) -> int:
        """
        Send synthesized data through a stream.

        Args:
            stream_id: The stream to send on.
            data_generator: Async generator yielding DataPacket objects.
            metrics_collector: Optional metrics collector for recording.

        Returns:
            Total bytes sent.
        """
        if self._protocol is None:
            raise RuntimeError("Not connected. Call connect() first.")

        total_bytes = 0

        async for packet in data_generator:
            # Send the packet
            self._protocol.send_data(stream_id, packet.data)
            total_bytes += packet.size

            # Record metrics
            if metrics_collector:
                metrics_collector.record_packet_sent(packet.size)

                # Sample RTT periodically
                rtt = self._protocol.get_rtt()
                if rtt is not None and rtt > 0:
                    metrics_collector.record_rtt_sample(rtt)

            # Allow event loop to process
            await asyncio.sleep(0)

        return total_bytes

    async def close(self):
        """Close the connection."""
        if self._connection_cm:
            try:
                await self._connection_cm.__aexit__(None, None, None)
            except Exception:
                pass  # Ignore errors during cleanup

    def get_protocol(self) -> Optional[ClientProtocol]:
        """Get the current protocol instance."""
        return self._protocol
