"""
Grid search executor.

Orchestrates running all parameter combinations and collecting results.
Supports resumability and parallel execution.
"""

import csv
import time
import sys
import subprocess
import signal
from pathlib import Path
from typing import Optional, Callable, List
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import Manager

# Add parent directories for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.parameter_space import ParameterSpace, ParameterCombination
from runner.single_connection_runner import SingleConnectionRunner, RunResult
from scheduler.resumable_scheduler import ResumableScheduler


def _run_single_combo(args: tuple) -> dict:
    """
    Worker function for parallel execution.

    Runs a single parameter combination against a server on the specified port.
    """
    combo_dict, server_port, duration, conn_code_path = args

    # Import here to ensure fresh process state
    import sys
    sys.path.insert(0, str(conn_code_path))

    from runner.single_connection_runner import SingleConnectionRunner, ParameterCombination

    combo = ParameterCombination(**combo_dict)
    runner = SingleConnectionRunner(
        server_port=server_port,
        duration=duration,
        conn_code_path=Path(conn_code_path),
    )

    result = runner.run(combo)
    return result.to_dict()


class GridSearchExecutor:
    """
    Executes grid search over parameter combinations.

    Features:
    - Resumability: Skips completed combinations
    - Parallel execution: Run multiple combinations simultaneously
    - Progress tracking: Reports completion status
    - CSV export: Saves results per combination
    """

    def __init__(
        self,
        output_dir: str = "output/measurements",
        duration: float = 30.0,
        reduced_search: bool = True,
        conn_code_path: Optional[Path] = None,
        num_workers: int = 4,
    ):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.duration = duration
        self.reduced_search = reduced_search
        self.num_workers = num_workers

        # Path to 3_conn_code (use absolute path)
        self.conn_code_path = (conn_code_path or (
            Path(__file__).parent.parent.parent / "3_conn_code"
        )).resolve()

        self.scheduler = ResumableScheduler(str(self.output_dir))

        # Server processes (one per worker for parallel execution)
        self._server_processes: List[subprocess.Popen] = []
        self._base_port = 4433

        self._progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable):
        """Set callback for progress updates: callback(current, total, combo_str)"""
        self._progress_callback = callback

    def _save_result(self, result: RunResult):
        """Save result to CSV file."""
        filepath = self.output_dir / result.combo.get_filename()

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "app_type", "loss_reduction_factor", "cubic_c", "minimum_window",
                "packet_threshold", "time_threshold", "cubic_max_idle_time",
                "initial_cw", "max_ack_delay", "throughput", "latency", "jitter",
                "rtt", "packet_loss_rate", "bytes_sent",
            ])
            writer.writerow([
                result.combo.app_type, result.combo.loss_reduction_factor,
                result.combo.cubic_c, result.combo.minimum_window,
                result.combo.packet_threshold, result.combo.time_threshold,
                result.combo.cubic_max_idle_time, result.combo.initial_cw,
                result.combo.max_ack_delay, result.throughput, result.latency,
                result.jitter, result.rtt, result.packet_loss_rate, result.bytes_sent,
            ])

    def _start_server(self, port: int) -> subprocess.Popen:
        """Start a QUIC server on the specified port."""
        # Create server runner script with absolute path
        server_runner = self.output_dir / f"_server_{port}.py"
        server_runner.write_text(f'''
import sys
sys.path.insert(0, "{self.conn_code_path}")
import asyncio
from simulation.server import QuicServer

async def main():
    server = QuicServer(port={port})
    await server.start()
    print("Server started on port {port}", flush=True)
    while True:
        await asyncio.sleep(1)

asyncio.run(main())
''')

        # Use absolute path for the script
        proc = subprocess.Popen(
            [sys.executable, str(server_runner.resolve())],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.conn_code_path),
        )

        # Wait for server to start
        time.sleep(1.5)

        # Check if server started successfully
        if proc.poll() is not None:
            stdout, stderr = proc.communicate()
            raise RuntimeError(
                f"Server on port {port} failed to start:\n"
                f"STDOUT: {stdout.decode()}\n"
                f"STDERR: {stderr.decode()}"
            )

        return proc

    def _start_servers(self, count: int) -> List[int]:
        """Start multiple servers and return their ports."""
        ports = []
        for i in range(count):
            port = self._base_port + i
            try:
                proc = self._start_server(port)
                self._server_processes.append(proc)
                ports.append(port)
                print(f"  Server {i+1}/{count} started on port {port}")
            except RuntimeError as e:
                print(f"  Warning: {e}")
        return ports

    def _stop_servers(self):
        """Stop all server processes."""
        for proc in self._server_processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._server_processes = []

    def execute(
        self,
        dry_run: bool = False,
        app_type: Optional[str] = None,
        parallel: bool = True,
    ) -> dict:
        """
        Execute the grid search.

        Args:
            dry_run: If True, only show what would run
            app_type: If specified, only run for this app type
            parallel: If True, run multiple combinations in parallel

        Returns:
            Summary dictionary with results
        """
        start_time = time.time()

        # Get pending combinations
        pending = self.scheduler.get_pending_combinations(
            reduced=self.reduced_search,
            app_type=app_type,
        )
        completed_before = self.scheduler.get_completed_count()

        # Calculate total
        if app_type:
            total = 81 if self.reduced_search else 729
        else:
            total = (
                ParameterSpace.get_reduced_combinations_count()
                if self.reduced_search
                else ParameterSpace.get_full_combinations_count()
            )

        # Adjust worker count
        actual_workers = min(self.num_workers, len(pending)) if parallel else 1

        # Print header
        print(f"\n{'='*60}")
        print("QUIC Parameter Grid Search")
        print(f"{'='*60}")
        print(f"Mode: {'Reduced (4 params)' if self.reduced_search else 'Full (6 params)'}")
        print(f"Duration per run: {self.duration}s")
        print(f"Parallel workers: {actual_workers}")
        print(f"Progress: {completed_before}/{total} completed")
        print(f"Pending: {len(pending)}")
        if app_type:
            print(f"App type filter: {app_type}")

        # Estimate time
        est_time = (len(pending) / actual_workers) * (self.duration + 5) / 60
        print(f"Estimated time: ~{est_time:.0f} minutes")
        print(f"{'='*60}\n")

        if not pending:
            print("All combinations complete!")
            return {"status": "complete", "total": total, "completed": total}

        if dry_run:
            print("DRY RUN - Would execute:")
            for i, combo in enumerate(pending[:10]):
                print(f"  {i+1}. {combo}")
            if len(pending) > 10:
                print(f"  ... and {len(pending) - 10} more")
            return {"status": "dry_run", "pending": len(pending)}

        # Start servers (one per worker)
        print(f"Starting {actual_workers} QUIC server(s)...")
        ports = self._start_servers(actual_workers)

        if not ports:
            print("ERROR: No servers could be started!")
            return {"status": "error", "message": "Failed to start servers"}

        print(f"Servers ready.\n")

        successes = 0
        failures = 0

        # Create work items (cycle through ports)
        work_items = [
            (combo.to_dict(), ports[i % len(ports)], self.duration, str(self.conn_code_path))
            for i, combo in enumerate(pending)
        ]

        try:
            if parallel and actual_workers > 1:
                # Parallel execution
                with ProcessPoolExecutor(max_workers=actual_workers) as executor:
                    future_to_combo = {
                        executor.submit(_run_single_combo, item): item[0]
                        for item in work_items
                    }

                    for i, future in enumerate(as_completed(future_to_combo), start=1):
                        combo_dict = future_to_combo[future]
                        current_num = completed_before + i
                        combo = ParameterCombination(**combo_dict)

                        print(f"[{current_num}/{total}] Completed: {combo}")

                        try:
                            result_dict = future.result()

                            if result_dict.get("success"):
                                result = RunResult(
                                    success=True,
                                    combo=combo,
                                    throughput=result_dict.get("throughput", 0),
                                    latency=result_dict.get("latency", 0),
                                    jitter=result_dict.get("jitter", 0),
                                    rtt=result_dict.get("rtt", 0),
                                    packet_loss_rate=result_dict.get("packet_loss_rate", 0),
                                    bytes_sent=result_dict.get("bytes_sent", 0),
                                )
                                self._save_result(result)
                                successes += 1
                                print(
                                    f"  OK: throughput={result.throughput:.0f} B/s, "
                                    f"latency={result.latency*1000:.2f}ms"
                                )
                            else:
                                failures += 1
                                error_msg = result_dict.get("error_message", "Unknown error")
                                print(f"  FAILED: {error_msg[:60]}")
                        except Exception as e:
                            failures += 1
                            print(f"  FAILED: {str(e)[:60]}")
            else:
                # Sequential execution
                runner = SingleConnectionRunner(
                    server_port=ports[0],
                    duration=self.duration,
                    conn_code_path=self.conn_code_path,
                )

                for i, combo in enumerate(pending, start=1):
                    current_num = completed_before + i
                    print(f"\n[{current_num}/{total}] Testing: {combo}")

                    if self._progress_callback:
                        self._progress_callback(current_num, total, str(combo))

                    result = runner.run(combo)

                    if result.success:
                        self._save_result(result)
                        successes += 1
                        print(
                            f"  OK: throughput={result.throughput:.0f} B/s, "
                            f"latency={result.latency*1000:.2f}ms, "
                            f"jitter={result.jitter*1000:.2f}ms"
                        )
                    else:
                        failures += 1
                        error_msg = result.error_message or "Unknown error"
                        print(f"  FAILED: {error_msg.split(chr(10))[0][:60]}")

                    time.sleep(0.5)

        except KeyboardInterrupt:
            print("\n\nInterrupted by user. Progress saved.")
            print("Run again to resume from where you left off.")
        finally:
            print("\nStopping servers...")
            self._stop_servers()

        elapsed = time.time() - start_time

        print(f"\n{'='*60}")
        print("Grid Search Summary")
        print(f"{'='*60}")
        print(f"Successes: {successes}")
        print(f"Failures: {failures}")
        print(f"Time: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
        print(f"{'='*60}")

        return {
            "status": "complete" if failures == 0 else "partial",
            "successes": successes,
            "failures": failures,
            "elapsed_seconds": elapsed,
            "completed_total": completed_before + successes,
            "total": total,
        }


def run_quick_test():
    """Quick test to verify the executor works."""
    print("Running quick test...")

    executor = GridSearchExecutor(
        output_dir="output/test_run",
        duration=5.0,
        reduced_search=True,
        num_workers=1,
    )

    combos = list(ParameterSpace.generate_reduced_combinations())[:1]
    if combos:
        print(f"Testing: {combos[0]}")
        result = executor.execute(app_type="file_transfer", parallel=False)
        print(f"Result: {result}")


if __name__ == "__main__":
    run_quick_test()
