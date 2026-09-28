"""
Resumable scheduling for the grid search.

Determines which parameter combinations still need to run. A full sweep takes
hours, so it must survive interruption; this scheduler provides that without a
state file or database.

How resumability works
----------------------
Completion is inferred from the filesystem. Each result CSV is named after the
exact parameter combination that produced it, so the presence of that file is
proof the combination has been measured. Restarting therefore requires no
recovery step: the scheduler re-derives progress by checking which expected
filenames exist.

    fresh start      -> all 192 combinations pending
    interrupted at 50 -> the remaining 142 returned
    finished         -> empty list

One consequence worth knowing: because a file's existence alone marks
completion, a run interrupted midway through *writing* a CSV would leave a
truncated file that is then treated as done. In practice each file is a single
small row written in one call, so the window is negligible.

The filename format here must stay in step with `metrics.exporter`, which
performs the actual writing; the two construct the same name independently.

Connections:
    Imports from: .parameter_space (ParameterSpace, ParameterCombination)
    Imported by:  grid_search/__init__.py, .executor, main.py
    Reads:        output/measurements/*.csv (existence only, never contents)
"""

from pathlib import Path
from typing import List, Tuple

from .parameter_space import ParameterSpace, ParameterCombination


class ResumableScheduler:
    """
    Enables resuming grid search after crash/interruption.

    The scheduler determines which simulations have been completed
    by checking for existing CSV output files. This allows the
    grid search to resume from where it stopped after a crash.

    Behavior:
    - Fresh start: Returns all 192 combinations as pending
    - Crash at #50: Returns remaining 142 combinations
    - All complete: Returns empty list
    """

    def __init__(self, output_dir: str = "output/measurements"):
        """
        Initialize the scheduler.

        Args:
            output_dir: Directory where CSV files are saved.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_filename(
        self,
        app_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_factor: float,
    ) -> str:
        """
        Build the CSV filename a given combination would produce.

        Must remain identical to MetricsExporter.get_filename: the two derive
        the same name independently, and a divergence would make finished work
        look pending and be silently repeated.
        """
        return f"{app_type}_{initial_cw}_{max_ack_delay}_{loss_factor}.csv"

    def is_completed(
        self,
        app_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_factor: float,
    ) -> bool:
        """
        Check if a parameter combination has been completed.

        A combination is considered complete if its CSV file exists.

        Args:
            app_type: Application type.
            initial_cw: Initial congestion window.
            max_ack_delay: Max ACK delay.
            loss_factor: Loss reduction factor.

        Returns:
            True if the combination has been completed.
        """
        filename = self._get_filename(app_type, initial_cw, max_ack_delay, loss_factor)
        return (self.output_dir / filename).exists()

    def is_combination_completed(self, combo: ParameterCombination) -> bool:
        """
        Check if a ParameterCombination has been completed.

        Args:
            combo: The parameter combination to check.

        Returns:
            True if the combination has been completed.
        """
        return self.is_completed(
            combo.app_type,
            combo.initial_cw,
            combo.max_ack_delay,
            combo.loss_factor,
        )

    def get_pending_combinations(self) -> List[ParameterCombination]:
        """
        Get all combinations that haven't been completed yet.

        Returns:
            List of pending ParameterCombination objects.
        """
        pending = []

        for combo in ParameterSpace.generate_all_combinations():
            if not self.is_combination_completed(combo):
                pending.append(combo)

        return pending

    def get_completed_count(self) -> int:
        """
        Get the number of completed simulations.

        Returns:
            Number of CSV files in the output directory.
        """
        # Counts every CSV present rather than re-checking each expected name.
        # Faster, but it assumes the directory holds only results from the
        # current parameter space; stale files from an earlier grid would
        # inflate the count.
        return len(list(self.output_dir.glob("*.csv")))

    def get_progress(self) -> Tuple[int, int]:
        """
        Get the current progress.

        Returns:
            Tuple of (completed_count, total_count).
        """
        total = ParameterSpace.get_total_combinations()
        completed = self.get_completed_count()
        return completed, total

    def get_progress_string(self) -> str:
        """
        Get a human-readable progress string.

        Returns:
            String like "50/192 completed (26%), 142 remaining"
        """
        completed, total = self.get_progress()
        remaining = total - completed
        percentage = (completed / total * 100) if total > 0 else 0

        return (
            f"{completed}/{total} completed ({percentage:.1f}%), "
            f"{remaining} remaining"
        )

    def is_all_complete(self) -> bool:
        """
        Check if all simulations are complete.

        Returns:
            True if all combinations have CSV files.
        """
        completed, total = self.get_progress()
        return completed >= total

    def clear_results(self):
        """
        Clear all result files (for fresh start).

        Warning: This deletes all CSV files in the output directory.
        """
        # Destructive: every result file is removed, which resets the sweep to
        # a fresh start. Exposed through `main.py clear`, which prompts for
        # confirmation before calling this.
        for csv_file in self.output_dir.glob("*.csv"):
            csv_file.unlink()
