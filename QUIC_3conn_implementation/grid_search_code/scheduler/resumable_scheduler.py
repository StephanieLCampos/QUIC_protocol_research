"""
Resumable scheduler for grid search.

Tracks completed combinations and enables resuming interrupted searches.
"""

import sys
from pathlib import Path
from typing import List, Optional

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.parameter_space import ParameterSpace, ParameterCombination


class ResumableScheduler:
    """
    Tracks grid search progress and enables resumability.

    Checks which parameter combinations have already been completed
    by looking for existing result files, allowing the search to
    resume from where it left off after an interruption.
    """

    def __init__(self, output_dir: str = "output/measurements"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def is_completed(self, combo: ParameterCombination) -> bool:
        """Check if a combination has already been completed."""
        result_file = self.output_dir / combo.get_filename()
        return result_file.exists() and result_file.stat().st_size > 0

    def get_completed_count(self) -> int:
        """Get count of completed combinations."""
        return len(list(self.output_dir.glob("*.csv")))

    def get_pending_combinations(
        self,
        reduced: bool = True,
        app_type: Optional[str] = None
    ) -> List[ParameterCombination]:
        """
        Get list of combinations that haven't been completed yet.

        Args:
            reduced: Use reduced search space (4 params instead of 6)
            app_type: Filter to specific app type (optional)

        Returns:
            List of ParameterCombination objects that need to be run
        """
        if app_type:
            all_combos = list(ParameterSpace.generate_for_app_type(
                app_type, reduced=reduced
            ))
        elif reduced:
            all_combos = list(ParameterSpace.generate_reduced_combinations())
        else:
            all_combos = list(ParameterSpace.generate_full_combinations())

        pending = [
            combo for combo in all_combos
            if not self.is_completed(combo)
        ]

        return pending

    def get_progress(self, reduced: bool = True) -> dict:
        """Get progress summary."""
        total = (
            ParameterSpace.get_reduced_combinations_count()
            if reduced
            else ParameterSpace.get_full_combinations_count()
        )
        completed = self.get_completed_count()
        pending = total - completed

        return {
            "total": total,
            "completed": completed,
            "pending": pending,
            "percent_complete": (completed / total * 100) if total > 0 else 0,
        }

    def clear_results(self):
        """Clear all existing results (use with caution)."""
        for csv_file in self.output_dir.glob("*.csv"):
            csv_file.unlink()
        print(f"Cleared all results from {self.output_dir}")
