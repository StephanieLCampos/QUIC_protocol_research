"""
Simulation runner that orchestrates a complete test run.

The runner sets up the server and client, sends synthesized data,
and collects metrics for analysis.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

# Import aioquic congestion control module for parameter patching
from aioquic.quic.congestion import cubic as aioquic_cubic

from config.settings import Settings, DEFAULT_SETTINGS
from synthesizers import SynthesizerFactory
from metrics.collector import MetricsCollector
from metrics.calculator import MetricsResult

from .server import QuicServer
from .client import QuicClient

# Store original aioquic values to restore later
# K_INITIAL_WINDOW is in packets (multiplied by max_datagram_size internally)
_ORIGINAL_K_INITIAL_WINDOW = aioquic_cubic.K_INITIAL_WINDOW
# K_CUBIC_LOSS_REDUCTION_FACTOR is the beta for multiplicative decrease
_ORIGINAL_K_LOSS_REDUCTION_FACTOR = aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR


@dataclass
class SimulationResult:
    """Results from a simulation run."""

    application_type: str
    initial_cw: int
    max_ack_delay: float
    loss_reduction_factor: float
    metrics: MetricsResult
    success: bool
    error_message: Optional[str] = None
    duration: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = {
            "application_type": self.application_type,
            "initial_cw": self.initial_cw,
            "max_ack_delay": self.max_ack_delay,
            "loss_reduction_factor": self.loss_reduction_factor,
            "success": self.success,
            "duration": self.duration,
        }
        if self.metrics:
            result.update(self.metrics.to_dict())
        if self.error_message:
            result["error_message"] = self.error_message
        return result


class SimulationRunner:
    """
    Executes a single simulation with given parameters.

    The runner:
    1. Configures QUIC parameters
    2. Starts the server
    3. Connects the client with 3 streams
    4. Sends synthesized data through one stream
    5. Collects metrics
    6. Returns results
    """

    def __init__(
        self,
        application_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_reduction_factor: float,
        settings: Optional[Settings] = None,
    ):
        """
        Initialize the simulation runner.

        Args:
            application_type: Type of application (video_streaming, file_transfer, conference_call).
            initial_cw: Initial congestion window in bytes.
            max_ack_delay: Maximum ACK delay in seconds.
            loss_reduction_factor: Loss reduction factor (0.0 to 1.0).
            settings: Optional settings override.
        """
        self.application_type = application_type
        self.initial_cw = initial_cw
        self.max_ack_delay = max_ack_delay
        self.loss_reduction_factor = loss_reduction_factor
        self.settings = settings or DEFAULT_SETTINGS

        self._server: Optional[QuicServer] = None
        self._client: Optional[QuicClient] = None
        self._metrics_collector: Optional[MetricsCollector] = None

    def _apply_recovery_parameters(self):
        """
        Apply congestion control parameters by patching aioquic module.

        This modifies the aioquic cubic congestion control constants at runtime:
        - K_INITIAL_WINDOW: Initial congestion window in packets
        - K_CUBIC_LOSS_REDUCTION_FACTOR: Multiplicative decrease factor on loss (beta)
        """
        # Convert initial_cw from bytes to packets (aioquic uses ~1200 bytes per packet)
        max_datagram_size = 1200
        initial_window_packets = self.initial_cw // max_datagram_size

        # Patch aioquic cubic module with our parameter values
        aioquic_cubic.K_INITIAL_WINDOW = initial_window_packets
        aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = self.loss_reduction_factor

    def _restore_recovery_parameters(self):
        """
        Restore original aioquic congestion control parameters.

        Called after simulation to ensure clean state for next run.
        """
        aioquic_cubic.K_INITIAL_WINDOW = _ORIGINAL_K_INITIAL_WINDOW
        aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = _ORIGINAL_K_LOSS_REDUCTION_FACTOR

    async def run(self) -> SimulationResult:
        """
        Execute the simulation.

        Returns:
            SimulationResult with metrics and status.
        """
        start_time = time.time()

        try:
            # Apply parameters (documented for manual modification)
            self._apply_recovery_parameters()

            # Initialize metrics collector
            self._metrics_collector = MetricsCollector()
            self._metrics_collector.start()

            # Start server
            self._server = QuicServer(
                host=self.settings.server_host,
                port=self.settings.server_port,
                cert_file=str(self.settings.cert_file),
                key_file=str(self.settings.key_file),
                max_ack_delay=self.max_ack_delay,
            )
            print(f"Starting QUIC server on {self.settings.server_host}:{self.settings.server_port}...")
            await self._server.start()
            print(f"✓ Server started")

            # Small delay to ensure server is ready
            await asyncio.sleep(0.5)

            # Connect client
            self._client = QuicClient(
                host=self.settings.server_host,
                port=self.settings.server_port,
                max_ack_delay=self.max_ack_delay,
                verify_cert=False,
            )
            print(f"Connecting client to {self.settings.server_host}:{self.settings.server_port}...")
            await self._client.connect()
            print(f"✓ Client connected")

            # Record connection ready
            self._metrics_collector.record_connection_ready()

            # Open 3 streams
            stream_ids = await self._client.open_streams(3)

            # Get the stream to use based on application type
            # Stream 0 = Video, Stream 1 = File, Stream 2 = Conference
            stream_index = {
                "video_streaming": 0,
                "file_transfer": 1,
                "conference_call": 2,
            }.get(self.application_type, 0)
            active_stream = stream_ids[stream_index]

            # Create synthesizer
            synthesizer = SynthesizerFactory.create(
                self.application_type,
                duration_seconds=self.settings.simulation_duration,
            )

            # Set connection in metrics collector
            if self._client.get_protocol():
                self._metrics_collector.connection = self._client.get_protocol()._quic

            # Send synthesized data
            await self._client.send_synthesized_data(
                active_stream,
                synthesizer.generate(),
                self._metrics_collector,
            )

            # Stop timing
            self._metrics_collector.stop()

            # Calculate metrics
            metrics = self._metrics_collector.calculate_metrics()

            duration = time.time() - start_time

            return SimulationResult(
                application_type=self.application_type,
                initial_cw=self.initial_cw,
                max_ack_delay=self.max_ack_delay,
                loss_reduction_factor=self.loss_reduction_factor,
                metrics=metrics,
                success=True,
                duration=duration,
            )

        except Exception as e:
            duration = time.time() - start_time
            # Return failure result with properly initialized MetricsResult
            return SimulationResult(
                application_type=self.application_type,
                initial_cw=self.initial_cw,
                max_ack_delay=self.max_ack_delay,
                loss_reduction_factor=self.loss_reduction_factor,
                metrics=MetricsResult(
                    throughput=0.0,
                    rtt=0.0,
                    latency=0.0,
                    jitter=0.0,
                    packet_loss_rate=0.0,
                    connection_establishment_time=0.0
                ),
                success=False,
                error_message=str(e),
                duration=duration,
            )

        finally:
            # Cleanup
            if self._client:
                await self._client.close()
            if self._server:
                await self._server.stop()
            # Restore original aioquic parameters
            self._restore_recovery_parameters()

    async def run_with_retry(self, max_retries: int = 3) -> SimulationResult:
        """
        Run simulation with retry on failure.

        Args:
            max_retries: Maximum number of retry attempts.

        Returns:
            SimulationResult from successful run or last attempt.
        """
        last_result = None

        for attempt in range(max_retries):
            result = await self.run()

            if result.success:
                return result

            last_result = result

            # Wait before retry
            await asyncio.sleep(1.0)

        return last_result


async def run_single_simulation(
    application_type: str = "video_streaming",
    initial_cw: int = 12000,
    max_ack_delay: float = 0.025,
    loss_reduction_factor: float = 0.5,
) -> SimulationResult:
    """
    Run a single simulation with specified parameters.

    This is a convenience function for testing.
    """
    runner = SimulationRunner(
        application_type=application_type,
        initial_cw=initial_cw,
        max_ack_delay=max_ack_delay,
        loss_reduction_factor=loss_reduction_factor,
    )
    return await runner.run()


if __name__ == "__main__":
    # Test run
    result = asyncio.run(run_single_simulation())
    print(f"Simulation completed: {result.success}")
    if result.success:
        print(f"Throughput: {result.metrics.throughput:.2f} bytes/s")
        print(f"RTT: {result.metrics.rtt * 1000:.2f} ms")
        print(f"Jitter: {result.metrics.jitter * 1000:.2f} ms")
