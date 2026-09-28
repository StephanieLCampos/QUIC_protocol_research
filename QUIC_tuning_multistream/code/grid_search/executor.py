"""
Grid search executor: runs the parameter sweep end to end.

Ties the sweep together. For every combination the scheduler reports as
pending, the executor constructs a SimulationRunner, awaits the measured run,
and exports the resulting metrics to CSV.

    ResumableScheduler -> pending combinations
                       -> SimulationRunner (one measured run each)
                       -> MetricsExporter (one CSV each)

Error policy: individual failures are counted and reported, never propagated.
A combination that fails leaves no CSV behind, so it is simply reported as
pending again on the next invocation and retried then. This keeps a single
misbehaving configuration from ending a multi-hour sweep.

Runs are executed strictly sequentially. This is deliberate rather than an
oversight: SimulationRunner tunes aioquic's process-global congestion-control
constants, so two concurrent runs in one process would overwrite each other's
parameters and silently corrupt both measurements.

Connections:
    Imports from: config.settings, simulation.runner (SimulationRunner),
                  metrics.exporter (MetricsExporter), .parameter_space, .scheduler
    Imported by:  grid_search/__init__.py, main.py
"""

import asyncio
import time
from typing import Optional, Callable

from config.settings import Settings, DEFAULT_SETTINGS
from simulation.runner import SimulationRunner
from metrics.exporter import MetricsExporter

from .parameter_space import ParameterSpace, ParameterCombination
from .scheduler import ResumableScheduler


class GridSearchExecutor:
    """
    Executes grid search over all parameter combinations.

    Features:
    - Resumability: Skips already-completed simulations
    - Progress tracking: Reports completion status
    - Error handling: Continues on individual simulation failures

    Total combinations: 192 (4 × 4 × 4 × 3)
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        output_dir: str = "output/measurements",
    ):
        """
        Initialize the grid search executor.

        Args:
            settings: Optional settings override.
            output_dir: Directory for saving results.
        """
        self.settings = settings or DEFAULT_SETTINGS
        self.output_dir = output_dir

        self.scheduler = ResumableScheduler(output_dir)
        self.exporter = MetricsExporter(output_dir)

        self._progress_callback: Optional[Callable] = None
        self._current_combo: Optional[ParameterCombination] = None
        self._start_time: Optional[float] = None

    def set_progress_callback(self, callback: Callable):
        """
        Set a callback for progress updates.

        The callback receives (current, total, combo_str) arguments.
        """
        self._progress_callback = callback

    def _report_progress(self, current: int, total: int, combo: ParameterCombination):
        """Report progress via callback if set."""
        if self._progress_callback:
            self._progress_callback(current, total, str(combo))

    async def execute(self, dry_run: bool = False) -> dict:
        """
        Execute the grid search.

        Args:
            dry_run: If True, only show what would be run without executing.

        Returns:
            Dictionary with execution summary.
        """
        self._start_time = time.time()

        # Get pending combinations
        pending = self.scheduler.get_pending_combinations()
        completed_before, total = self.scheduler.get_progress()

        print(f"\n{'='*60}")
        print("QUIC Parameter Grid Search")
        print(f"{'='*60}")
        print(f"Progress: {self.scheduler.get_progress_string()}")
        print(f"{'='*60}\n")

        if not pending:
            print("All simulations complete!")
            return {
                "status": "complete",
                "total": total,
                "completed": total,
                "new_completions": 0,
                "failures": 0,
            }

        if dry_run:
            print("DRY RUN - Would execute the following simulations:")
            # Number each line from the global position in the sweep, not from
            # 1, so a resumed run continues the original numbering.
            for i, combo in enumerate(pending, start=1):
                print(f"  {completed_before + i}/{total}: {combo}")
            return {
                "status": "dry_run",
                "pending": len(pending),
            }

        # Execute pending simulations
        successes = 0
        failures = 0

        # Sequential by necessity: SimulationRunner patches process-global
        # aioquic constants, so overlapping runs would corrupt each other.
        for i, combo in enumerate(pending, start=1):
            current_num = completed_before + i
            self._current_combo = combo

            print(f"\n[{current_num}/{total}] Running: {combo}")
            self._report_progress(current_num, total, combo)

            try:
                # Create and run simulation
                runner = SimulationRunner(
                    application_type=combo.app_type,
                    initial_cw=combo.initial_cw,
                    max_ack_delay=combo.max_ack_delay,
                    loss_reduction_factor=combo.loss_factor,
                    settings=self.settings,
                )

                result = await runner.run()

                if result.success:
                    # Export metrics to CSV
                    self.exporter.export(
                        application_type=combo.app_type,
                        initial_cw=combo.initial_cw,
                        max_ack_delay=combo.max_ack_delay,
                        loss_factor=combo.loss_factor,
                        metrics=result.metrics,
                    )
                    successes += 1
                    print(f"  ✓ Success - Throughput: {result.metrics.throughput:.0f} B/s, "
                          f"RTT: {result.metrics.rtt*1000:.1f}ms")
                else:
                    failures += 1
                    print(f"  ✗ Failed: {result.error_message}")

            except Exception as e:
                # Caught at the sweep level as a backstop. SimulationRunner
                # already converts its own failures into a result object, so
                # reaching here means something outside the run itself broke
                # (export, scheduling). Either way the sweep continues; the
                # combination simply stays pending and is retried on restart.
                failures += 1
                print(f"  ✗ Error: {e}")

            # Brief pause between runs so the previous server's socket is fully
            # released before the next run binds the same port.
            await asyncio.sleep(0.5)

        # Summary
        elapsed = time.time() - self._start_time
        completed_after, _ = self.scheduler.get_progress()

        print(f"\n{'='*60}")
        print("Grid Search Complete")
        print(f"{'='*60}")
        print(f"Completed: {completed_after}/{total}")
        print(f"New completions: {successes}")
        print(f"Failures: {failures}")
        print(f"Time elapsed: {elapsed:.1f}s")
        print(f"{'='*60}\n")

        # Summary dictionary consumed by main.py for its exit reporting.
        return {
            "status": "complete" if completed_after >= total else "partial",
            "total": total,
            "completed": completed_after,
            "new_completions": successes,
            "failures": failures,
            "elapsed_seconds": elapsed,
        }

    async def execute_single(self, combo: ParameterCombination) -> bool:
        """
        Execute a single parameter combination.

        Args:
            combo: The parameter combination to execute.

        Returns:
            True if successful, False otherwise.
        """
        try:
            runner = SimulationRunner(
                application_type=combo.app_type,
                initial_cw=combo.initial_cw,
                max_ack_delay=combo.max_ack_delay,
                loss_reduction_factor=combo.loss_factor,
                settings=self.settings,
            )

            result = await runner.run()

            if result.success:
                self.exporter.export(
                    application_type=combo.app_type,
                    initial_cw=combo.initial_cw,
                    max_ack_delay=combo.max_ack_delay,
                    loss_factor=combo.loss_factor,
                    metrics=result.metrics,
                )
                return True

            return False

        except Exception:
            # Boolean contract: callers of execute_single only need to know
            # whether a result was produced, not why one was not.
            return False

    def get_status(self) -> dict:
        """Get current execution status."""
        completed, total = self.scheduler.get_progress()
        return {
            "completed": completed,
            "total": total,
            "remaining": total - completed,
            "is_complete": self.scheduler.is_all_complete(),
            "current": str(self._current_combo) if self._current_combo else None,
        }

# Module-level convenience wrapper. Constructing the executor here lets other
# modules launch a sweep with default settings in one call, rather than
# repeating the executor setup at each call site.
async def run_grid_search(dry_run: bool = False) -> dict:
    """
    Run the complete grid search.

    This is a convenience function for running from the command line.
    """
    executor = GridSearchExecutor()
    return await executor.execute(dry_run=dry_run)

# Direct-execution entry point, used for checking the sweep configuration in
# isolation. Defaults to a dry run so that invoking this module by hand cannot
# start a multi-hour experiment by accident. The supported entry point for real
# runs is main.py.
if __name__ == "__main__":
    result = asyncio.run(run_grid_search(dry_run=True))
    print(f"\nResult: {result}")
