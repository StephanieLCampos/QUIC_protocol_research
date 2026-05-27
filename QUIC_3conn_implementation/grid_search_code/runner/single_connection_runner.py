"""
Single connection runner for grid search.

Runs one QUIC connection with specified parameters in an isolated process.
This ensures aioquic module-level globals don't interfere between runs.
"""

import asyncio
import sys
from pathlib import Path
from multiprocessing import Process, Queue
from dataclasses import dataclass
from typing import Optional

# Add 3_conn_code to path for imports
CONN_CODE_PATH = Path(__file__).parent.parent.parent / "3_conn_code"
sys.path.insert(0, str(CONN_CODE_PATH))

from config.parameter_space import ParameterCombination


@dataclass
class RunResult:
    """Result from a single parameter combination run."""
    success: bool
    combo: ParameterCombination
    throughput: float = 0.0
    latency: float = 0.0
    jitter: float = 0.0
    rtt: float = 0.0
    packet_loss_rate: float = 0.0
    bytes_sent: int = 0
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "parameters": self.combo.to_dict(),
            "throughput": self.throughput,
            "latency": self.latency,
            "jitter": self.jitter,
            "rtt": self.rtt,
            "packet_loss_rate": self.packet_loss_rate,
            "bytes_sent": self.bytes_sent,
            "error_message": self.error_message,
        }


def _apply_parameters(combo: ParameterCombination):
    """
    Apply parameters to aioquic globals.

    Must be called in the worker process before creating any connections.
    These are module-level globals in aioquic that control CUBIC behavior.
    """
    # Import aioquic modules here (in the worker process)
    from aioquic.quic.congestion import cubic as aioquic_cubic
    from aioquic.quic import recovery as aioquic_recovery

    # Dynamic parameters (CUBIC CC)
    aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = combo.loss_reduction_factor
    aioquic_cubic.K_CUBIC_C = combo.cubic_c
    aioquic_cubic.K_MINIMUM_WINDOW = combo.minimum_window
    aioquic_recovery.K_PACKET_THRESHOLD = combo.packet_threshold
    aioquic_recovery.K_TIME_THRESHOLD = combo.time_threshold
    aioquic_cubic.K_CUBIC_MAX_IDLE_TIME = combo.cubic_max_idle_time

    # Start-only parameters (initial window is calculated from initial_cw)
    # Assuming 1200 byte packets (standard QUIC MTU)
    initial_window_packets = combo.initial_cw // 1200
    aioquic_cubic.K_INITIAL_WINDOW = initial_window_packets


async def _run_connection(
    combo: ParameterCombination,
    server_host: str,
    server_port: int,
    duration: float,
    cert_path: Path,
) -> RunResult:
    """Run a single connection with the given parameters."""
    # Apply parameters to aioquic globals
    _apply_parameters(combo)

    # Import 3_conn_code modules (must be done after path is set up)
    from aioquic.asyncio import connect
    from aioquic.quic.configuration import QuicConfiguration
    from metrics.collector import MetricsCollector
    from synthesizers import SynthesizerFactory

    metrics_collector = MetricsCollector()

    try:
        configuration = QuicConfiguration(is_client=True)
        configuration.verify_mode = False
        configuration.max_datagram_frame_size = 65536
        configuration.max_ack_delay = combo.max_ack_delay

        async with connect(
            server_host,
            server_port,
            configuration=configuration,
        ) as protocol:
            metrics_collector.connection = protocol._quic
            metrics_collector.start()
            metrics_collector.record_connection_ready()

            # Create synthesizer for this app type
            synthesizer = SynthesizerFactory.create(
                combo.app_type,
                duration_seconds=duration,
            )

            stream_id = protocol._quic.get_next_available_stream_id()
            start_time = asyncio.get_event_loop().time()

            # Send data for the specified duration
            async for packet in synthesizer.generate():
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= duration:
                    break

                try:
                    protocol._quic.send_stream_data(stream_id, packet.data, end_stream=False)
                    protocol.transmit()
                except AssertionError:
                    # Stream may be closed, get a new one
                    stream_id = protocol._quic.get_next_available_stream_id()
                    protocol._quic.send_stream_data(stream_id, packet.data, end_stream=False)
                    protocol.transmit()
                except Exception:
                    break

                metrics_collector.record_packet_sent(packet.size)

                # Sample RTT from connection
                try:
                    rtt = protocol._quic._loss._rtt_smoothed
                    if rtt and rtt > 0:
                        metrics_collector.record_rtt_sample(rtt)
                except AttributeError:
                    pass

                # Small delay to avoid overwhelming
                await asyncio.sleep(0.001)

            metrics_collector.stop()
            final_metrics = metrics_collector.calculate_metrics()

            return RunResult(
                success=True,
                combo=combo,
                throughput=final_metrics.throughput,
                latency=final_metrics.latency,
                jitter=final_metrics.jitter,
                rtt=final_metrics.rtt,
                packet_loss_rate=final_metrics.packet_loss_rate,
                bytes_sent=metrics_collector.bytes_sent,
            )

    except Exception as e:
        import traceback
        return RunResult(
            success=False,
            combo=combo,
            error_message=f"{str(e)}\n{traceback.format_exc()}",
        )


def _worker_entry(
    combo_dict: dict,
    server_host: str,
    server_port: int,
    duration: float,
    conn_code_path: str,
    cert_path: str,
    result_queue: Queue
):
    """
    Entry point for worker process.

    Runs in a completely isolated process to ensure aioquic globals
    don't interfere between different parameter combinations.
    """
    # Set up path for imports
    sys.path.insert(0, conn_code_path)

    # Reconstruct the combination
    combo = ParameterCombination(**combo_dict)

    # Run the connection
    result = asyncio.run(_run_connection(
        combo,
        server_host,
        server_port,
        duration,
        Path(cert_path),
    ))

    # Put result in queue
    result_queue.put(result.to_dict())


class SingleConnectionRunner:
    """
    Runs a single QUIC connection in an isolated process.

    Each run creates a new process to ensure aioquic module-level
    globals are freshly initialized with the test parameters.
    """

    def __init__(
        self,
        server_host: str = "localhost",
        server_port: int = 4433,
        duration: float = 30.0,
        conn_code_path: Optional[Path] = None,
    ):
        self.server_host = server_host
        self.server_port = server_port
        self.duration = duration
        self.conn_code_path = conn_code_path or CONN_CODE_PATH
        self.cert_path = self.conn_code_path / "certs"

    def run(self, combo: ParameterCombination) -> RunResult:
        """
        Run a single parameter combination in an isolated process.

        Args:
            combo: Parameter combination to test

        Returns:
            RunResult with metrics or error information
        """
        result_queue = Queue()

        process = Process(
            target=_worker_entry,
            args=(
                combo.to_dict(),
                self.server_host,
                self.server_port,
                self.duration,
                str(self.conn_code_path),
                str(self.cert_path),
                result_queue,
            ),
        )

        process.start()

        # Wait for completion with extra time for setup/teardown
        process.join(timeout=self.duration + 60)

        if process.is_alive():
            # Process took too long, terminate it
            process.terminate()
            process.join(timeout=5)
            return RunResult(
                success=False,
                combo=combo,
                error_message="Process timeout - exceeded maximum allowed time",
            )

        try:
            result_dict = result_queue.get_nowait()

            # Reconstruct parameters dict into combo for the result
            params = result_dict.get("parameters", {})
            result_combo = ParameterCombination(**params)

            return RunResult(
                success=result_dict.get("success", False),
                combo=result_combo,
                throughput=result_dict.get("throughput", 0),
                latency=result_dict.get("latency", 0),
                jitter=result_dict.get("jitter", 0),
                rtt=result_dict.get("rtt", 0),
                packet_loss_rate=result_dict.get("packet_loss_rate", 0),
                bytes_sent=result_dict.get("bytes_sent", 0),
                error_message=result_dict.get("error_message"),
            )
        except Exception as e:
            return RunResult(
                success=False,
                combo=combo,
                error_message=f"Failed to get result from worker process: {e}",
            )
