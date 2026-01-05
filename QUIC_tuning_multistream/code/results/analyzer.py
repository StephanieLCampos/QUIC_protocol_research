"""
Results analyzer for grid search data.

Loads CSV files from completed simulations and provides
analysis methods to find optimal parameters for each
application type.
"""

import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class OptimalParameters:
    """Optimal parameters for a specific application type."""

    app_type: str
    initial_cw: int
    max_ack_delay: float
    loss_factor: float
    primary_metric: str
    primary_metric_value: float
    all_metrics: Dict[str, float]


class ResultsAnalyzer:
    """
    Analyzes grid search results to find optimal parameters.

    Optimization targets by application type:
    - video_streaming: Minimize RTT (for responsive playback)
    - file_transfer: Maximize throughput (for fast transfers)
    - conference_call: Minimize jitter (for smooth audio/video)
    """

    # Optimization targets for each application type
    OPTIMIZATION_TARGETS = {
        "video_streaming": ("rtt", "min"),
        "file_transfer": ("throughput", "max"),
        "conference_call": ("jitter", "min"),
    }

    def __init__(self, data_dir: str = "output/measurements"):
        """
        Initialize the analyzer.

        Args:
            data_dir: Directory containing CSV result files.
        """
        self.data_dir = Path(data_dir)
        self._data: Optional[pd.DataFrame] = None

    def load_data(self) -> pd.DataFrame:
        """
        Load all CSV files into a single DataFrame.

        Returns:
            DataFrame with all simulation results.

        Raises:
            FileNotFoundError: If no CSV files are found.
        """
        csv_files = list(self.data_dir.glob("*.csv"))

        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {self.data_dir}")

        dataframes = []

        for csv_file in csv_files:
            # Parse filename: <app>_<icw>_<ack>_<lf>.csv
            parts = csv_file.stem.split("_")
            if len(parts) >= 4:
                app_type = parts[0]
                # Handle app types with underscores
                if parts[0] in ["video", "file", "conference"]:
                    app_type = f"{parts[0]}_{parts[1]}"
                    initial_cw = int(parts[2])
                    max_ack_delay = float(parts[3])
                    loss_factor = float(parts[4])
                else:
                    initial_cw = int(parts[1])
                    max_ack_delay = float(parts[2])
                    loss_factor = float(parts[3])

                df = pd.read_csv(csv_file)

                # Add parameter columns
                df["app_type"] = app_type
                df["initial_cw"] = initial_cw
                df["max_ack_delay"] = max_ack_delay
                df["loss_factor"] = loss_factor
                df["source_file"] = csv_file.name

                dataframes.append(df)

        if not dataframes:
            raise FileNotFoundError("No valid CSV files could be parsed")

        self._data = pd.concat(dataframes, ignore_index=True)
        return self._data

    @property
    def data(self) -> pd.DataFrame:
        """Get the loaded data, loading if necessary."""
        if self._data is None:
            self.load_data()
        return self._data

    def get_summary_statistics(self) -> pd.DataFrame:
        """
        Get summary statistics for each parameter combination.

        Returns:
            DataFrame with mean metrics for each combination.
        """
        group_cols = ["app_type", "initial_cw", "max_ack_delay", "loss_factor"]
        # Use actual column names from CSV exporter
        metric_cols = ["throughput", "rtt", "jitter", "packet_loss_rate", "connection_establishment_time"]

        # Filter to only existing columns
        available_metrics = [c for c in metric_cols if c in self.data.columns]

        return self.data.groupby(group_cols)[available_metrics].mean().reset_index()

    def find_optimal_parameters(self, app_type: str) -> OptimalParameters:
        """
        Find optimal parameters for a specific application type.

        Args:
            app_type: Application type to optimize for.

        Returns:
            OptimalParameters with the best configuration.

        Raises:
            ValueError: If app_type is not recognized.
        """
        if app_type not in self.OPTIMIZATION_TARGETS:
            raise ValueError(
                f"Unknown app_type: {app_type}. "
                f"Valid types: {list(self.OPTIMIZATION_TARGETS.keys())}"
            )

        target_metric, direction = self.OPTIMIZATION_TARGETS[app_type]

        # Filter data for this app type
        app_data = self.data[self.data["app_type"] == app_type]

        if app_data.empty:
            raise ValueError(f"No data found for app_type: {app_type}")

        # Get summary by parameter combination
        # Use actual column names from CSV exporter
        agg_dict = {"throughput": "mean", "rtt": "mean", "jitter": "mean"}
        if "packet_loss_rate" in app_data.columns:
            agg_dict["packet_loss_rate"] = "mean"
        if "connection_establishment_time" in app_data.columns:
            agg_dict["connection_establishment_time"] = "mean"

        summary = app_data.groupby(
            ["initial_cw", "max_ack_delay", "loss_factor"]
        ).agg(agg_dict).reset_index()

        # Find optimal row
        if direction == "min":
            optimal_idx = summary[target_metric].idxmin()
        else:
            optimal_idx = summary[target_metric].idxmax()

        optimal_row = summary.loc[optimal_idx]

        return OptimalParameters(
            app_type=app_type,
            initial_cw=int(optimal_row["initial_cw"]),
            max_ack_delay=float(optimal_row["max_ack_delay"]),
            loss_factor=float(optimal_row["loss_factor"]),
            primary_metric=target_metric,
            primary_metric_value=float(optimal_row[target_metric]),
            all_metrics={
                "throughput": float(optimal_row.get("throughput", 0)),
                "rtt": float(optimal_row.get("rtt", 0)),
                "jitter": float(optimal_row.get("jitter", 0)),
                "packet_loss_rate": float(optimal_row.get("packet_loss_rate", 0)),
                "connection_establishment_time": float(optimal_row.get("connection_establishment_time", 0)),
            },
        )

    def find_all_optimal_parameters(self) -> Dict[str, OptimalParameters]:
        """
        Find optimal parameters for all application types.

        Returns:
            Dictionary mapping app_type to OptimalParameters.
        """
        results = {}

        for app_type in self.OPTIMIZATION_TARGETS:
            try:
                results[app_type] = self.find_optimal_parameters(app_type)
            except ValueError:
                # Skip app types with no data
                continue

        return results

    def analyze_parameter_impact(
        self,
        parameter: str,
        metric: str,
        app_type: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Analyze how a parameter affects a specific metric.

        Args:
            parameter: Parameter to analyze (initial_cw, max_ack_delay, loss_factor).
            metric: Metric to measure (throughput, rtt, jitter, packet_loss_rate).
            app_type: Optional app type filter.

        Returns:
            DataFrame showing metric values for each parameter value.
        """
        data = self.data

        if app_type:
            data = data[data["app_type"] == app_type]

        if metric not in data.columns:
            return pd.DataFrame()

        return data.groupby(parameter)[metric].agg(["mean", "std", "min", "max"])

    def get_parameter_correlations(
        self,
        app_type: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get correlations between parameters and metrics.

        Args:
            app_type: Optional app type filter.

        Returns:
            Correlation matrix DataFrame.
        """
        data = self.data

        if app_type:
            data = data[data["app_type"] == app_type]

        param_cols = ["initial_cw", "max_ack_delay", "loss_factor"]
        metric_cols = ["throughput", "rtt", "jitter", "packet_loss_rate"]

        available_cols = [c for c in param_cols + metric_cols if c in data.columns]

        return data[available_cols].corr()

    def get_top_configurations(
        self,
        app_type: str,
        n: int = 5,
    ) -> pd.DataFrame:
        """
        Get the top N configurations for an application type.

        Args:
            app_type: Application type to analyze.
            n: Number of top configurations to return.

        Returns:
            DataFrame with top configurations.
        """
        if app_type not in self.OPTIMIZATION_TARGETS:
            raise ValueError(f"Unknown app_type: {app_type}")

        target_metric, direction = self.OPTIMIZATION_TARGETS[app_type]

        app_data = self.data[self.data["app_type"] == app_type]

        # Use actual column names from CSV exporter
        agg_dict = {"throughput": "mean", "rtt": "mean", "jitter": "mean"}
        if "packet_loss_rate" in app_data.columns:
            agg_dict["packet_loss_rate"] = "mean"

        summary = app_data.groupby(
            ["initial_cw", "max_ack_delay", "loss_factor"]
        ).agg(agg_dict).reset_index()

        ascending = direction == "min"
        return summary.sort_values(target_metric, ascending=ascending).head(n)

    def compare_app_types(self) -> pd.DataFrame:
        """
        Compare metrics across application types.

        Returns:
            DataFrame with mean metrics for each app type.
        """
        agg_dict = {
            "throughput": ["mean", "std"],
            "rtt": ["mean", "std"],
            "jitter": ["mean", "std"],
        }
        if "packet_loss_rate" in self.data.columns:
            agg_dict["packet_loss_rate"] = ["mean", "std"]

        return self.data.groupby("app_type").agg(agg_dict)
