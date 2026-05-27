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
        token_bucket=None,
    ):
        self.config = config
        self.server_host = server_host
        self.server_port = server_port
        self.command_pipe = command_pipe
        self.metrics_queue = metrics_queue
        self.start_barrier = start_barrier
        self.network_scenario = network_scenario
        self.network_config = network_config or {}
        self._token_bucket = token_bucket  #SharedTokenBucket or None

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

        # Get delta throughput (per-epoch, responsive to changes)
        throughput_acked_delta = self._metrics_collector.get_throughput_acked_delta()

        # Calculate cwnd-limited throughput (theoretical max given cwnd and RTT)
        # This is more accurate than bytes_acked when there's buffering
        cwnd_samples = self._metrics_collector.cwnd_samples
        rtt_samples = self._metrics_collector.rtt_samples
        throughput_cwnd = 0.0
        if cwnd_samples and rtt_samples:
            avg_cwnd = sum(cwnd_samples[-20:]) / len(cwnd_samples[-20:])
            avg_rtt = sum(rtt_samples[-20:]) / len(rtt_samples[-20:])
            if avg_rtt > 0:
                throughput_cwnd = avg_cwnd / avg_rtt  # bytes/sec

        msg = IPCMessage(
            msg_type=MessageType.METRICS,
            connection_id=self.config.connection_id,
            timestamp=time.time(),
            payload={
                "throughput": metrics.throughput,
                "throughput_acked": metrics.throughput_acked,
                "throughput_acked_delta": throughput_acked_delta,  # Per-epoch delta
                "throughput_cwnd": throughput_cwnd,  # Cwnd-limited estimate (more accurate)
                "rtt": metrics.rtt,
                "latency": metrics.latency,
                "jitter": metrics.jitter,
                "packet_loss_rate": metrics.packet_loss_rate,
                "bytes_sent": self._metrics_collector.bytes_sent,
                "bytes_acked": metrics.bytes_acked,
                "current_params": {
                    "loss_reduction_factor": self.config.loss_reduction_factor,
                    "cubic_c": self.config.cubic_c,
                    "minimum_window": self.config.minimum_window,
                    "packet_threshold": self.config.packet_threshold,
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
        #reduce flow control window to limit in flight data
        #default 1MB at 30 Mbps = ~267ms one way queuing = ~1500ms smoothed RTT
        #128KB at 30 Mbps = ~34ms one-way giving realistic ~100-200ms RTT
        configuration.max_data = 131072
        configuration.max_stream_data_bidi_local = 131072
        configuration.max_stream_data_bidi_remote = 131072

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
                    # Check for stop signals frequently
                    self._check_commands()

                    if not self._running or (time.time() - start_time) >= duration:
                        break

                    if stream_closed:
                        break

                    #enforce shared bandwidth cap before sending
                    if self._token_bucket is not None:
                        # Add timeout to avoid getting stuck waiting for tokens
                        try:
                            await asyncio.wait_for(
                                self._token_bucket.consume_async(packet.size),
                                timeout=1.0
                            )
                        except asyncio.TimeoutError:
                            # Check if we should stop
                            if not self._running or (time.time() - start_time) >= duration:
                                break
                            continue  # Try again

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

                    # Sample RTT for average RTT calculation
                    rtt = self._get_rtt_latest(protocol)
                    if rtt and rtt > 0:
                        self._metrics_collector.record_rtt_sample(rtt)

                    # Sample RTTVAR directly for jitter calculation
                    # RTTVAR is aioquic's measure of RTT variation (RFC 6298)
                    rttvar = self._get_rtt_variance(protocol)
                    if rttvar is not None:
                        self._metrics_collector.record_rtt_variance(rttvar)

                    # Sample network metrics for ACK-verified throughput
                    self._sample_network_metrics(protocol)

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
        """Get current smoothed RTT from aioquic (for display)."""
        try:
            return protocol._quic._loss._rtt_smoothed
        except AttributeError:
            return None

    def _get_rtt_latest(self, protocol) -> Optional[float]:
        """Get latest RTT sample from aioquic (for jitter calculation)."""
        try:
            # _rtt_latest shows actual RTT variation, better for jitter
            return protocol._quic._loss._rtt_latest
        except AttributeError:
            try:
                return protocol._quic._loss._rtt_smoothed
            except AttributeError:
                return None

    def _get_rtt_variance(self, protocol) -> Optional[float]:
        """
        Get RTT variance (RTTVAR) from aioquic for direct jitter measurement.

        RTTVAR from RFC 6298 represents the variation in RTT, which is
        essentially what jitter measures. This is more reliable than
        trying to calculate jitter from consecutive smoothed RTT samples.
        """
        try:
            return protocol._quic._loss._rtt_variance
        except AttributeError:
            return None

    def _sample_network_metrics(self, protocol) -> None:
        """
        Sample network metrics from aioquic for ACK-verified throughput.

        Accesses congestion_window and bytes_in_flight from aioquic's
        loss recovery module to calculate bytes_acked.
        """
        try:
            loss = protocol._quic._loss
            cwnd = getattr(loss, "congestion_window", 0)
            bytes_in_flight = getattr(loss, "bytes_in_flight", 0)

            if cwnd > 0:
                self._metrics_collector.cwnd_samples.append(cwnd)
            if bytes_in_flight >= 0:
                self._metrics_collector.bytes_in_flight_samples.append(bytes_in_flight)

            # Compute bytes acknowledged: bytes_sent - bytes_in_flight
            current_acked = self._metrics_collector.bytes_sent - bytes_in_flight
            if current_acked > self._metrics_collector.bytes_acked:
                self._metrics_collector.bytes_acked = current_acked

            # Track loss indicators from aioquic's loss recovery module
            # Method 1: PTO count (Probe Timeout - indicates packet loss)
            pto_count = getattr(loss, "_pto_count", 0)

            # Method 2: Check ssthresh changes (set when loss detected)
            # ssthresh < cwnd indicates loss has occurred
            ssthresh = getattr(loss, "ssthresh", float('inf'))
            if ssthresh < float('inf') and cwnd > 0:
                # Loss has occurred - ssthresh is set
                # Estimate lost packets based on cwnd reduction
                if not hasattr(self, '_last_ssthresh'):
                    self._last_ssthresh = ssthresh
                if ssthresh < self._last_ssthresh:
                    # ssthresh dropped - new loss event
                    # Estimate ~2-5 packets lost per event
                    self._metrics_collector.packets_lost += 3
                self._last_ssthresh = ssthresh

            # Method 3: Track cwnd reductions as loss indicator
            # More sensitive threshold (15% drop) to catch continuous low-rate loss
            if not hasattr(self, '_prev_cwnd'):
                self._prev_cwnd = cwnd
                self._cwnd_drop_cooldown = 0
            # Only count if cwnd actually dropped and we're not in cooldown
            if cwnd < self._prev_cwnd * 0.85 and self._prev_cwnd > 1000 and self._cwnd_drop_cooldown <= 0:
                # cwnd drop (>15%) indicates loss event
                drop_ratio = 1 - (cwnd / self._prev_cwnd)
                estimated_lost = max(1, int(drop_ratio * 5))
                self._metrics_collector.packets_lost += estimated_lost
                self._cwnd_drop_cooldown = 5  # Cooldown to avoid double-counting
            elif self._cwnd_drop_cooldown > 0:
                self._cwnd_drop_cooldown -= 1
            self._prev_cwnd = max(cwnd, self._prev_cwnd * 0.95)  # Slowly decay reference

            # Method 4: PTO events
            if pto_count > 0:
                # Each PTO typically means packets weren't ACKed
                new_ptos = pto_count - getattr(self, '_last_pto_count', 0)
                if new_ptos > 0:
                    self._metrics_collector.packets_lost += new_ptos * 3
                self._last_pto_count = pto_count

            # Method 5: Try to get loss stats from congestion controller
            cc = getattr(loss, "_cc", None)
            if cc is not None:
                # Check for direct loss counters
                packets_lost = getattr(cc, "packets_lost", 0) or getattr(cc, "_packets_lost", 0)
                if packets_lost > self._metrics_collector.packets_lost:
                    self._metrics_collector.packets_lost = packets_lost

                bytes_lost = getattr(cc, "bytes_lost", 0) or getattr(cc, "_bytes_lost", 0)
                if bytes_lost > 0:
                    self._metrics_collector.bytes_lost = bytes_lost

        except AttributeError:
            pass


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
    token_bucket=None,
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
            token_bucket=token_bucket,
        )
        print(f"[Worker Entry] Worker object created, starting run loop", flush=True)
        #cancel_join_thread() prevents the worker from blocking at exit waiting for unread items to drain through the pipe and avoids deadlock with main process
        metrics_queue.cancel_join_thread()

        async def _run():
            try:
                await asyncio.wait_for(worker.run(duration), timeout=duration + 8)
            except asyncio.TimeoutError:
                print(f"[Worker Entry] Timed out after {duration + 8:.0f}s, forcing exit", flush=True)

        asyncio.run(_run())
        print(f"[Worker Entry] Worker finished", flush=True)
    except Exception as e:
        import traceback
        print(f"[Worker Entry] EXCEPTION: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        raise
