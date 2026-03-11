"""
Worker process for QUIC connection isolation.

Each worker runs a single QUIC connection in an isolated process,
enabling true per-connection parameter isolation.
"""

import asyncio
import time
from multiprocessing import Queue
from multiprocessing.connection import Connection
from typing import Optional

from aioquic.quic.congestion import cubic as aioquic_cubic
from aioquic.quic import recovery as aioquic_recovery
from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio import connect

from config.connection_config import ConnectionConfig, DYNAMIC_PARAMETERS
from metrics.collector import MetricsCollector
from metrics.epoch import ParameterSnapshot, EpochManager, EpochConfig
from synthesizers import SynthesizerFactory
from .ipc_messages import IPCMessage, MessageType


class ConnectionWorker:
    """
    Worker that runs a single QUIC connection in an isolated process.

    Each worker has its own copy of aioquic module globals, enabling
    true per-connection parameter isolation.
    """

    def __init__(
        self,
        config: ConnectionConfig,
        server_host: str,
        server_port: int,
        command_pipe: Connection,
        metrics_queue: Queue,
        start_barrier,
        network_scenario: str = "",
        network_config: dict = None,
    ):
        self.config = config
        self.server_host = server_host
        self.server_port = server_port
        self.command_pipe = command_pipe
        self.metrics_queue = metrics_queue
        self.start_barrier = start_barrier
        self.network_scenario = network_scenario
        self.network_config = network_config or {}

        self._running = False
        self._metrics_collector = MetricsCollector()
        self._param_history = []
        self._epoch_manager = None  # Initialized in run()

    def _apply_initial_parameters(self):
        """Apply initial CC parameters to aioquic globals (isolated to this process)."""
        initial_window_packets = self.config.initial_cw // self.config.max_datagram_size
        aioquic_cubic.K_INITIAL_WINDOW = initial_window_packets

        aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = self.config.loss_reduction_factor
        aioquic_cubic.K_CUBIC_C = self.config.cubic_c
        aioquic_cubic.K_MINIMUM_WINDOW = self.config.minimum_window
        aioquic_cubic.K_CUBIC_MAX_IDLE_TIME = self.config.cubic_max_idle_time
        aioquic_recovery.K_PACKET_THRESHOLD = self.config.packet_threshold
        aioquic_recovery.K_TIME_THRESHOLD = self.config.time_threshold

    def _update_parameter(self, param_name: str, value):
        """Update a single parameter mid-connection."""
        if param_name not in DYNAMIC_PARAMETERS:
            self._send_error(f"Parameter '{param_name}' cannot be changed mid-connection")
            return

        old_value = getattr(self.config, param_name)
        setattr(self.config, param_name, value)

        # Update aioquic globals
        if param_name == "loss_reduction_factor":
            aioquic_cubic.K_CUBIC_LOSS_REDUCTION_FACTOR = value
        elif param_name == "cubic_c":
            aioquic_cubic.K_CUBIC_C = value
        elif param_name == "minimum_window":
            aioquic_cubic.K_MINIMUM_WINDOW = value
        elif param_name == "packet_threshold":
            aioquic_recovery.K_PACKET_THRESHOLD = value
        elif param_name == "time_threshold":
            aioquic_recovery.K_TIME_THRESHOLD = value
        elif param_name == "cubic_max_idle_time":
            aioquic_cubic.K_CUBIC_MAX_IDLE_TIME = value

        self._param_history.append({
            "timestamp": time.time(),
            "param_name": param_name,
            "old_value": old_value,
            "new_value": value,
        })

        # Notify EpochManager of parameter change (starts new epoch after settling)
        if self._epoch_manager:
            new_params = ParameterSnapshot(
                loss_reduction_factor=self.config.loss_reduction_factor,
                cubic_c=self.config.cubic_c,
                minimum_window=self.config.minimum_window,
                packet_threshold=self.config.packet_threshold,
                time_threshold=self.config.time_threshold,
                cubic_max_idle_time=self.config.cubic_max_idle_time,
                initial_cw=self.config.initial_cw,
                max_ack_delay=self.config.max_ack_delay,
                max_data=self.config.max_data,
                max_stream_data=self.config.max_stream_data,
            )
            self._epoch_manager.on_parameter_change(new_params)

    def _check_commands(self):
        """Check for commands from main process (non-blocking)."""
        while self.command_pipe.poll():
            try:
                msg_dict = self.command_pipe.recv()
                msg = IPCMessage.from_dict(msg_dict)

                if msg.msg_type == MessageType.UPDATE_PARAM:
                    self._update_parameter(msg.payload["param_name"], msg.payload["value"])
                    self._send_ack(msg)
                elif msg.msg_type == MessageType.UPDATE_MULTIPLE_PARAMS:
                    for param_name, value in msg.payload["params"].items():
                        self._update_parameter(param_name, value)
                    self._send_ack(msg)
                elif msg.msg_type == MessageType.STOP:
                    self._running = False
            except Exception as e:
                self._send_error(str(e))

    def _send_metrics(self):
        """Send current metrics to main process."""
        metrics = self._metrics_collector.calculate_metrics()
        msg = IPCMessage(
            msg_type=MessageType.METRICS,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={
                "throughput": metrics.throughput,
                "rtt": metrics.rtt,
                "latency": metrics.latency,
                "jitter": metrics.jitter,
                "packet_loss_rate": metrics.packet_loss_rate,
                "bytes_sent": self._metrics_collector.bytes_sent,
                "current_params": {
                    "loss_reduction_factor": self.config.loss_reduction_factor,
                    "cubic_c": self.config.cubic_c,
                    "minimum_window": self.config.minimum_window,
                },
            },
        )
        self.metrics_queue.put(msg)

    def _send_ack(self, original_msg: IPCMessage):
        """Send acknowledgment for received command."""
        msg = IPCMessage(
            msg_type=MessageType.ACK,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={"original_timestamp": original_msg.timestamp},
        )
        self.metrics_queue.put(msg)

    def _send_error(self, error_msg: str):
        """Send error message to main process."""
        msg = IPCMessage(
            msg_type=MessageType.ERROR,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={"error": error_msg},
        )
        self.metrics_queue.put(msg)

    def _send_finished(self, final_metrics: dict, epoch_history: dict = None):
        """Send finished message with final results including epoch history."""
        msg = IPCMessage(
            msg_type=MessageType.FINISHED,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={
                "final_metrics": final_metrics,
                "param_history": self._param_history,
                "epoch_history": epoch_history or {},
                "metrics_history": self._metrics_history,
                "success": True,
            },
        )
        self.metrics_queue.put(msg)

    async def run(self, duration: float):
        """Main worker loop with epoch-based metrics collection."""
        print(f"[Worker {self.config.connection_id}] run() started for {self.config.application_type}", flush=True)
        self._apply_initial_parameters()
        self._metrics_history = []

        # Create initial parameter snapshot (includes all parameters)
        initial_params = ParameterSnapshot(
            loss_reduction_factor=self.config.loss_reduction_factor,
            cubic_c=self.config.cubic_c,
            minimum_window=self.config.minimum_window,
            packet_threshold=self.config.packet_threshold,
            time_threshold=self.config.time_threshold,
            cubic_max_idle_time=self.config.cubic_max_idle_time,
            initial_cw=self.config.initial_cw,
            max_ack_delay=self.config.max_ack_delay,
            max_data=self.config.max_data,
            max_stream_data=self.config.max_stream_data,
        )

        # Initialize EpochManager with full context
        self._epoch_manager = EpochManager(
            connection_id=self.config.connection_id,
            application_type=self.config.application_type,
            network_scenario=self.network_scenario,
            network_config=self.network_config,
            initial_params=initial_params,
            config=EpochConfig(
                settling_time=2.0,  # 2 seconds settling time
                min_epoch_duration=2.0,
                sample_interval=0.1,
            ),
        )

        print(f"[Worker {self.config.connection_id}] Waiting at barrier...", flush=True)
        self.start_barrier.wait()
        print(f"[Worker {self.config.connection_id}] Barrier released, starting connection", flush=True)

        self._running = True
        start_time = time.time()
        last_sample_time = start_time

        print(f"[Worker {self.config.connection_id}] Starting {self.config.application_type} connection to {self.server_host}:{self.server_port}", flush=True)

        configuration = QuicConfiguration(is_client=True)
        configuration.verify_mode = False
        configuration.max_datagram_frame_size = 65536
        configuration.max_ack_delay = self.config.max_ack_delay

        print(f"[Worker {self.config.connection_id}] Configuration created, connecting...", flush=True)
        try:
            async with connect(
                self.server_host,
                self.server_port,
                configuration=configuration,
            ) as protocol:
                print(f"[Worker {self.config.connection_id}] Connected to server, starting to send data...", flush=True)
                self._metrics_collector.connection = protocol._quic
                self._metrics_collector.start()
                self._metrics_collector.record_connection_ready()

                # Connect epoch manager to metrics collector
                self._epoch_manager.set_metrics_collector(self._metrics_collector)
                self._epoch_manager.start()

                synthesizer = SynthesizerFactory.create(
                    self.config.application_type,
                    duration_seconds=duration,
                )

                stream_id = protocol._quic.get_next_available_stream_id()
                stream_closed = False

                async for packet in synthesizer.generate():
                    if not self._running or (time.time() - start_time) >= duration:
                        break

                    if stream_closed:
                        break

                    # Send data with proper error handling
                    try:
                        protocol._quic.send_stream_data(stream_id, packet.data, end_stream=False)
                        protocol.transmit()  # Trigger actual transmission
                    except AssertionError:
                        # Stream was closed (FIN received), open a new one
                        stream_id = protocol._quic.get_next_available_stream_id()
                        try:
                            protocol._quic.send_stream_data(stream_id, packet.data, end_stream=False)
                            protocol.transmit()
                        except Exception:
                            stream_closed = True
                            break
                    except Exception as e:
                        # Connection might be closed
                        stream_closed = True
                        break

                    self._metrics_collector.record_packet_sent(packet.size)

                    rtt = self._get_rtt(protocol)
                    if rtt and rtt > 0:
                        self._metrics_collector.record_rtt_sample(rtt)

                    self._check_commands()

                    # Collect epoch sample at interval (100ms)
                    now = time.time()
                    if now - last_sample_time >= 0.1:
                        # EpochManager collects sample (handles settling internally)
                        self._epoch_manager.collect_sample()

                        # Always record to metrics history for time-series export
                        metrics = self._metrics_collector.calculate_metrics()
                        self._metrics_history.append({
                            "timestamp": now - start_time,
                            **metrics.to_dict(),
                        })

                        # Always send metrics to UI (settling only affects epoch collection)
                        self._send_metrics()

                        last_sample_time = now

                    # Allow event loop to process incoming data
                    await asyncio.sleep(0.001)

                self._metrics_collector.stop()

                # Finalize epoch collection and get history
                self._epoch_manager.finalize()
                epoch_history = self._epoch_manager.get_history()

                final_metrics = self._metrics_collector.calculate_metrics()

                # Send finished with epoch history converted to dict
                self._send_finished(final_metrics.to_dict(), epoch_history.to_dict())

        except asyncio.TimeoutError:
            error_msg = f"Connection timeout: Could not connect to {self.server_host}:{self.server_port} within 5 seconds"
            print(f"[Worker {self.config.connection_id}] {error_msg}", flush=True)
            self._send_error(error_msg)
        except ConnectionError as e:
            error_msg = f"Connection error: {str(e)}"
            print(f"[Worker {self.config.connection_id}] {error_msg}", flush=True)
            self._send_error(error_msg)
        except OSError as e:
            error_msg = f"OS error (likely connection refused): {str(e)}"
            print(f"[Worker {self.config.connection_id}] {error_msg}", flush=True)
            self._send_error(error_msg)
        except Exception as e:
            import traceback
            error_msg = f"Worker error: {str(e)}\n{traceback.format_exc()}"
            print(f"[Worker {self.config.connection_id}] {error_msg}", flush=True)
            self._send_error(error_msg)
            raise

    def _get_rtt(self, protocol) -> Optional[float]:
        """Get current RTT from aioquic."""
        try:
            return protocol._quic._loss._rtt_smoothed
        except AttributeError:
            return None


def worker_process_entry(
    config_dict: dict,
    server_host: str,
    server_port: int,
    command_pipe: Connection,
    metrics_queue: Queue,
    start_barrier,
    duration: float,
    network_scenario: str = "",
    network_config: dict = None,
):
    """Entry point for worker process."""
    try:
        print(f"[Worker Entry] Starting worker process for connection type", flush=True)
        config = ConnectionConfig.from_dict(config_dict)
        print(f"[Worker Entry] Connection ID: {config.connection_id}, Type: {config.application_type}", flush=True)
        worker = ConnectionWorker(
            config=config,
            server_host=server_host,
            server_port=server_port,
            command_pipe=command_pipe,
            metrics_queue=metrics_queue,
            start_barrier=start_barrier,
            network_scenario=network_scenario,
            network_config=network_config or {},
        )
        print(f"[Worker Entry] Worker object created, starting run loop", flush=True)
        asyncio.run(worker.run(duration))
        print(f"[Worker Entry] Worker finished", flush=True)
    except Exception as e:
        import traceback
        print(f"[Worker Entry] EXCEPTION: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        raise
