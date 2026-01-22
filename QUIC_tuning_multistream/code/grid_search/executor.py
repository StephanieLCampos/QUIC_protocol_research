"""
Grid search executor.

Orchestrates the complete parameter sweep, running simulations
for all combinations and saving results.
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
            for i, combo in enumerate(pending, start=1): #for each combo in pending 
                print(f"  {completed_before + i}/{total}: {combo}")
            return {
                "status": "dry_run",
                "pending": len(pending),
            }

        # Execute pending simulations
        successes = 0
        failures = 0

        for i, combo in enumerate(pending, start=1): #for each combo in pending
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
                failures += 1
                print(f"  ✗ Error: {e}")

            # Small delay between simulations
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

        return { # returns a dictionary of the results
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

#like a main function, creates a GridSearchExecutor object and runs the execute method
async def run_grid_search(dry_run: bool = False) -> dict: # having this function allows you to reuse the created object in other files,
                                                          # Rather than having to create a new one each time you want to run a grid search in another file
    """
    Run the complete grid search.

    This is a convenience function for running from the command line.
    """
    executor = GridSearchExecutor()
    return await executor.execute(dry_run=dry_run)

#What actually runs the run_grid_search
if __name__ == "__main__":  #This code only runs if you execute this file directly (like python executor.py). 
                            #If another file imports this module, this block is skipped.
    # Test run
    result = asyncio.run(run_grid_search(dry_run=True))
    print(f"\nResult: {result}")
