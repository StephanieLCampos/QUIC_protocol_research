"""
Orchestration of a single measured simulation run.

`SimulationRunner` performs one complete experiment for one parameter
combination: it applies the congestion-control parameters, starts a server,
connects a client, drives the appropriate synthesizer to completion, collects
metrics, and tears everything down.

    apply params -> start server -> connect client -> open streams
                 -> send synthesized data -> collect metrics -> restore params

Key design constraint (the central one in this project)
-------------------------------------------------------
aioquic exposes its CUBIC tuning values as *module-level globals*
(`K_INITIAL_WINDOW`, `K_CUBIC_LOSS_REDUCTION_FACTOR`), not as per-connection
configuration. The only way to vary them is to patch the module before the
connection is created, as `_apply_recovery_parameters` does below, restoring
the captured originals afterwards in a `finally` block.

Because those globals are process-wide, every connection inside one process
necessarily shares them. That is workable here, where each run measures a
single connection in isolation, but it is precisely the limitation that forced
the Generation 2 design (QUIC_3conn_implementation) to place each of its three
concurrent connections in a separate OS process so they could hold different
parameter values simultaneously.

Failure handling: `run()` never raises. A failed run returns a
SimulationResult with success=False and a zero-filled MetricsResult, so that
one bad combination cannot abort a multi-hour sweep.

Connections:
    Imports from: aioquic.quic.congestion.cubic (patched at runtime),
                  config.settings, synthesizers, metrics.collector,
                  metrics.calculator, .server, .client
    Imported by:  simulation/__init__.py, grid_search.executor, examples/,
                  setup_namespace_bottleneck, the test_* diagnostic scripts
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

# Capture aioquic's stock congestion-control constants at import time, before
# anything has had a chance to patch them. These are the values restored after
# each run so that one combination's settings cannot leak into the next.
#
# K_INITIAL_WINDOW is expressed in packets; aioquic multiplies it by the
# datagram size internally.
_ORIGINAL_K_INITIAL_WINDOW = aioquic_cubic.K_INITIAL_WINDOW
# K_CUBIC_LOSS_REDUCTION_FACTOR is CUBIC's beta: the multiplicative-decrease
# factor applied to the congestion window on a loss event.
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
        # The parameter space is expressed in bytes (the unit an operator
        # thinks in), while aioquic's K_INITIAL_WINDOW is in packets. Convert
        # using the standard 1200-byte QUIC datagram size. Integer division
        # floors, so a requested window is never rounded upward.
        max_datagram_size = 1200
        initial_window_packets = self.initial_cw // max_datagram_size

        # Mutate the module globals in place. This must happen before any
        # connection is constructed, because aioquic reads these constants when
        # it builds a congestion controller, not on every send.
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

            # Give the listening socket a moment to bind before dialling it.
            # Without this pause the client can race ahead and fail to connect
            # on a loaded machine.
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

            # Three streams are always opened so that every run presents the
            # server with an identical connection shape, but only one carries
            # traffic: the workload under measurement. Holding the stream
            # layout constant keeps results comparable across application types.
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
            # Failures are reported as data, never raised. A single bad
            # combination in a sweep of hundreds must not terminate the run,
            # so the error is recorded and a zero-filled metrics object is
            # returned in place of real measurements.
            duration = time.time() - start_time
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
            # Teardown runs on every path, successful or not. Restoring the
            # patched aioquic globals here is essential: leaving them modified
            # would silently contaminate every subsequent run in this process.
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
