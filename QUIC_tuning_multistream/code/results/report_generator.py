"""
Report generator for grid search results.

Generates human-readable reports summarizing the research
findings and optimal parameter configurations.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from .analyzer import ResultsAnalyzer, OptimalParameters


class ReportGenerator:
    """
    Generates research reports from grid search results.

    Reports include:
    - Executive summary with optimal parameters
    - Detailed analysis for each application type
    - Parameter impact analysis
    - Recommendations
    """

    def __init__(self, analyzer: Optional[ResultsAnalyzer] = None):
        """
        Initialize the report generator.

        Args:
            analyzer: ResultsAnalyzer instance. If None, creates a new one.
        """
        self.analyzer = analyzer or ResultsAnalyzer()

    def generate_summary_report(self, output_path: Optional[str] = None) -> str:
        """
        Generate a summary report of the research findings.

        Args:
            output_path: Optional path to save the report.

        Returns:
            The report as a string.
        """
        # Load data
        self.analyzer.load_data()

        # Get optimal parameters for each app type
        optimal = self.analyzer.find_all_optimal_parameters()

        # Build report
        lines = []
        lines.append("=" * 70)
        lines.append("QUIC Multi-Stream Research: Grid Search Results Summary")
        lines.append("=" * 70)
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # Data overview
        lines.append("-" * 70)
        lines.append("DATA OVERVIEW")
        lines.append("-" * 70)
        lines.append(f"Total records: {len(self.analyzer.data)}")
        lines.append(f"Application types: {self.analyzer.data['app_type'].nunique()}")
        lines.append(f"Unique configurations: {len(self.analyzer.get_summary_statistics())}")
        lines.append("")

        # Optimal parameters for each app type
        lines.append("-" * 70)
        lines.append("OPTIMAL PARAMETERS BY APPLICATION TYPE")
        lines.append("-" * 70)

        for app_type, params in optimal.items():
            lines.append("")
            lines.append(f"  {app_type.upper().replace('_', ' ')}")
            lines.append(f"  {'~' * len(app_type)}")
            lines.append(f"  Optimization target: {params.primary_metric} "
                        f"({'minimize' if params.primary_metric in ['rtt', 'jitter', 'loss_rate'] else 'maximize'})")
            lines.append(f"  Best {params.primary_metric}: {self._format_metric(params.primary_metric, params.primary_metric_value)}")
            lines.append("")
            lines.append("  Optimal configuration:")
            lines.append(f"    - Initial Congestion Window: {params.initial_cw} bytes")
            lines.append(f"    - Max ACK Delay: {params.max_ack_delay * 1000:.1f} ms")
            lines.append(f"    - Loss Reduction Factor: {params.loss_factor}")
            lines.append("")
            lines.append("  All metrics at optimal:")
            for metric, value in params.all_metrics.items():
                lines.append(f"    - {metric}: {self._format_metric(metric, value)}")

        lines.append("")

        # Parameter impact summary
        lines.append("-" * 70)
        lines.append("PARAMETER IMPACT ANALYSIS")
        lines.append("-" * 70)

        for param in ["initial_cw", "max_ack_delay", "loss_factor"]:
            lines.append("")
            lines.append(f"  {param.upper().replace('_', ' ')}")
            lines.append(f"  Impact on throughput:")
            impact = self.analyzer.analyze_parameter_impact(param, "throughput")
            for idx, row in impact.iterrows():
                lines.append(f"    {idx}: mean={row['mean']:.0f} B/s, std={row['std']:.0f}")

        lines.append("")

        # Recommendations
        lines.append("-" * 70)
        lines.append("RECOMMENDATIONS")
        lines.append("-" * 70)
        lines.append("")

        for app_type, params in optimal.items():
            lines.append(f"  For {app_type.replace('_', ' ')}:")
            lines.append(f"    Use ICW={params.initial_cw}, "
                        f"ACK={params.max_ack_delay*1000:.0f}ms, "
                        f"LF={params.loss_factor}")
            lines.append("")

        lines.append("=" * 70)
        lines.append("END OF REPORT")
        lines.append("=" * 70)

        report = "\n".join(lines)

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                f.write(report)

        return report

    def generate_detailed_report(
        self,
        app_type: str,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Generate a detailed report for a specific application type.

        Args:
            app_type: Application type to analyze.
            output_path: Optional path to save the report.

        Returns:
            The report as a string.
        """
        # Load data
        self.analyzer.load_data()

        lines = []
        lines.append("=" * 70)
        lines.append(f"Detailed Analysis: {app_type.replace('_', ' ').title()}")
        lines.append("=" * 70)
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # Optimal parameters
        optimal = self.analyzer.find_optimal_parameters(app_type)

        lines.append("-" * 70)
        lines.append("OPTIMAL CONFIGURATION")
        lines.append("-" * 70)
        lines.append(f"Primary metric: {optimal.primary_metric}")
        lines.append(f"Best value: {self._format_metric(optimal.primary_metric, optimal.primary_metric_value)}")
        lines.append("")
        lines.append("Parameters:")
        lines.append(f"  Initial Congestion Window: {optimal.initial_cw} bytes")
        lines.append(f"  Max ACK Delay: {optimal.max_ack_delay * 1000:.1f} ms")
        lines.append(f"  Loss Reduction Factor: {optimal.loss_factor}")
        lines.append("")

        # Top 5 configurations
        lines.append("-" * 70)
        lines.append("TOP 5 CONFIGURATIONS")
        lines.append("-" * 70)

        top5 = self.analyzer.get_top_configurations(app_type, n=5)
        for i, (_, row) in enumerate(top5.iterrows(), 1):
            lines.append(f"\n  #{i}:")
            lines.append(f"    ICW={int(row['initial_cw'])}, "
                        f"ACK={row['max_ack_delay']*1000:.0f}ms, "
                        f"LF={row['loss_factor']}")
            lines.append(f"    Throughput: {row['throughput']:.0f} B/s")
            lines.append(f"    RTT: {row['rtt']*1000:.2f} ms")
            latency = row.get('latency', row['rtt'] / 2)
            lines.append(f"    Latency: {latency*1000:.2f} ms")
            lines.append(f"    Jitter: {row['jitter']*1000:.2f} ms")

        lines.append("")

        # Correlation analysis
        lines.append("-" * 70)
        lines.append("PARAMETER-METRIC CORRELATIONS")
        lines.append("-" * 70)

        corr = self.analyzer.get_parameter_correlations(app_type)

        lines.append("\n  Parameter correlations with metrics:")
        for param in ["initial_cw", "max_ack_delay", "loss_factor"]:
            if param in corr.columns:
                lines.append(f"\n  {param}:")
                for metric in ["throughput", "rtt", "latency", "jitter"]:
                    if metric in corr.index:
                        val = corr.loc[metric, param]
                        lines.append(f"    vs {metric}: {val:+.3f}")

        lines.append("")
        lines.append("=" * 70)
        lines.append("END OF REPORT")
        lines.append("=" * 70)

        report = "\n".join(lines)

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                f.write(report)

        return report

    def generate_csv_summary(self, output_path: str) -> None:
        """
        Generate a CSV summary of all results.

        Args:
            output_path: Path to save the CSV file.
        """
        summary = self.analyzer.get_summary_statistics()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(output_path, index=False)

    def _format_metric(self, metric: str, value: float) -> str:
        """Format a metric value for display."""
        if metric == "throughput":
            if value >= 1_000_000:
                return f"{value/1_000_000:.2f} MB/s"
            elif value >= 1_000:
                return f"{value/1_000:.2f} KB/s"
            else:
                return f"{value:.0f} B/s"
        elif metric == "rtt":
            return f"{value * 1000:.2f} ms"
        elif metric == "latency":
            return f"{value * 1000:.2f} ms"
        elif metric == "jitter":
            return f"{value * 1000:.3f} ms"
        elif metric == "packet_loss_rate":
            return f"{value * 100:.2f}%"
        elif metric == "connection_establishment_time":
            return f"{value * 1000:.2f} ms"
        else:
            return f"{value:.4f}"
