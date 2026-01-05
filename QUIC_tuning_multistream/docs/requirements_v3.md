# QUIC Multi-Stream Research Project - Technical Requirements & Implementation Plan

## Project Overview
This research project aims to investigate how QUIC protocol parameters affect performance metrics for different data transmission types using the aioquic library in Python.

## Technical Requirements

### Core Functionality
1. **QUIC Connection Management**
   - Establish QUIC client-server connection using aioquic library
   - Open 3 concurrent streams per connection
   - Send synthesized data through one stream per simulation run
   - Configure QUIC parameters via source code modification and configuration API

2. **Configurable QUIC Parameters** (Selected for Research)

   | Parameter | Location | Default | Impact |
   |-----------|----------|---------|--------|
   | **Initial Congestion Window** | `recovery.py` | 12,000 bytes | Startup speed |
   | **Max ACK Delay** | `configuration.py` | 25ms | Latency & jitter |
   | **Loss Reduction Factor** | `recovery.py` | 0.5 | Throughput recovery |

3. **Data Transmission Types (Application Types)**
   - **Video Streaming**: Continuous data flow with emphasis on low latency
   - **File Transfer**: Bulk data transfer prioritizing throughput
   - **Conference Calls**: Bidirectional real-time communication requiring minimal jitter

4. **Performance Metrics**
   - **Throughput**: Data transfer rate (bytes/second)
   - **Round-Trip Time (RTT)**: Latency measurement (accessible via `QuicConnection._loss._rtt`)
   - **Jitter**: Variation in packet delay
   - **Packet Loss Rate**: Percentage of lost packets
   - **Connection Establishment Time**: Initial handshake duration

### System Architecture

```
┌─────────────┐         ┌─────────────┐
│   Client    │         │   Server    │
├─────────────┤         ├─────────────┤
│ Stream 1    │◄───────►│ Stream 1    │ (Video)
│ Stream 2    │◄───────►│ Stream 2    │ (File)
│ Stream 3    │◄───────►│ Stream 3    │ (Conference)
└─────────────┘         └─────────────┘

Note: Each simulation run uses 3 streams but sends
synthesized data through only ONE stream at a time.
```

### Dependencies
- Python 3.8+
- aioquic (forked for parameter modification)
- cryptography (required by aioquic for TLS)
- pandas (for results analysis)
- TLS certificates (self-signed acceptable for research)

---

## Project Source Code Directory Layout

All source code is organized inside the `code/` directory:

```
code/
├── main.py                     # Main entry point
├── aioquic/                    # Forked aioquic library source
│   └── src/
│       └── aioquic/
│           └── quic/
│               ├── recovery.py      # K_INITIAL_WINDOW, K_LOSS_REDUCTION_FACTOR
│               └── configuration.py # max_ack_delay
│
├── synthesizers/               # Data-synthesizing code
│   ├── __init__.py
│   ├── base.py                 # Base synthesizer class
│   ├── video_streaming.py      # Video stream data generator
│   ├── file_transfer.py        # File transfer data generator
│   └── conference_call.py      # Conference call data generator
│
├── simulation/                 # Simulation code
│   ├── __init__.py
│   ├── runner.py               # Simulation runner
│   ├── client.py               # QUIC client implementation
│   └── server.py               # QUIC server implementation
│
├── metrics/                    # Metric measurement code
│   ├── __init__.py
│   ├── collector.py            # Metrics collection during simulation
│   ├── calculator.py           # Metric calculations
│   └── exporter.py             # CSV export functionality
│
├── grid_search/                # Grid search code
│   ├── __init__.py
│   ├── executor.py             # Grid search execution
│   ├── parameter_space.py      # Parameter value definitions
│   └── scheduler.py            # Resumability (crash recovery)
│
├── results/                    # Results report code
│   ├── __init__.py
│   ├── analyzer.py             # Results analysis
│   ├── report_generator.py     # Report generation
│   └── visualizer.py           # Data visualization (optional)
│
├── config/                     # Configuration files
│   ├── parameters.py           # Parameter presets
│   └── settings.py             # Global settings
│
├── output/                     # Output directory
│   ├── measurements/           # CSV measurement files
│   └── reports/                # Generated reports
│
└── certs/                      # TLS certificates
    ├── cert.pem
    └── key.pem
```

---

## Module Specifications

### 1. Data-Synthesizing Code (`synthesizers/`)

Generates synthesized data for each application type. The actual content of the data is irrelevant to QUIC behavior—only the size and timing patterns matter.

#### Video Streaming Synthesizer
```python
# synthesizers/video_streaming.py
class VideoStreamingSynthesizer:
    """
    Generates H.264-like video frame patterns.

    Characteristics:
    - 30 fps (33.33ms intervals)
    - I-frames every 60 frames (~50KB each)
    - P-frames between I-frames (~5KB each)
    """

    def __init__(self, fps: int = 30, i_frame_interval: int = 60):
        self.fps = fps
        self.i_frame_size = 50000   # ~50KB
        self.p_frame_size = 5000    # ~5KB
        self.i_frame_interval = i_frame_interval

    async def generate(self, duration_seconds: float) -> AsyncIterator[bytes]:
        """Generate video frames for specified duration."""
        pass
```

#### File Transfer Synthesizer
```python
# synthesizers/file_transfer.py
class FileTransferSynthesizer:
    """
    Generates bulk file transfer data.

    Characteristics:
    - 64KB chunks
    - No timing delay (send as fast as possible)
    - Configurable total size
    """

    def __init__(self, chunk_size: int = 65536, total_size: int = 10_000_000):
        self.chunk_size = chunk_size
        self.total_size = total_size

    async def generate(self) -> AsyncIterator[bytes]:
        """Generate file chunks."""
        pass
```

#### Conference Call Synthesizer
```python
# synthesizers/conference_call.py
class ConferenceCallSynthesizer:
    """
    Generates bidirectional audio-like packets.

    Characteristics:
    - 20ms packet intervals
    - ~320 bytes per packet (128kbps audio)
    - Bidirectional (requires both send and receive)
    """

    def __init__(self, packet_interval_ms: int = 20, bitrate_kbps: int = 128):
        self.packet_interval = packet_interval_ms / 1000.0
        self.packet_size = int(bitrate_kbps * 1000 * self.packet_interval / 8)

    async def generate(self, duration_seconds: float) -> AsyncIterator[bytes]:
        """Generate audio packets for specified duration."""
        pass
```

---

### 2. Simulation Code (`simulation/`)

Executes a single simulation run with specified parameters and application type.

#### Simulation Flow
```
1. Receive parameters and application type
2. Set QUIC parameters to selected values
3. Get appropriate data synthesizer for application type
4. Open QUIC connection with 3 streams
5. Send synthesized data through ONE stream
6. Metrics collector records measurements during execution
7. Export metrics to CSV file
```

#### Simulation Runner
```python
# simulation/runner.py
class SimulationRunner:
    """Executes a single simulation with given parameters."""

    def __init__(
        self,
        application_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_reduction_factor: float
    ):
        self.application_type = application_type
        self.initial_cw = initial_cw
        self.max_ack_delay = max_ack_delay
        self.loss_reduction_factor = loss_reduction_factor

    async def run(self) -> SimulationResult:
        """
        Execute simulation:
        1. Configure aioquic parameters
        2. Start server
        3. Connect client with 3 streams
        4. Send data through designated stream
        5. Collect metrics
        6. Return results
        """
        pass
```

---

### 3. Metric Measurement Code (`metrics/`)

Collects and exports the 5 performance metrics during simulation execution.

#### Metrics Collected
| Metric | Description | How to Measure |
|--------|-------------|----------------|
| Throughput | Bytes/second | Total bytes / duration |
| RTT | Round-trip time | `conn._loss._rtt_smoothed` |
| Jitter | Delay variation | Std dev of inter-packet delays |
| Packet Loss Rate | % packets lost | Lost packets / total packets |
| Connection Establishment Time | Handshake duration | Time from connect() to ready |

#### CSV Output Format

**File Naming Convention**:
```
<application_type>_<Initial_CW>_<Max_ACK_Delay>_<Loss_Factor>.csv
```

**Examples**:
```
video_streaming_12000_0.025_0.5.csv
file_transfer_60000_0.010_0.7.csv
conference_call_120000_0.002_0.6.csv
```

**CSV Fields**:
```csv
initial_congestion_window,max_ack_delay,loss_reduction_factor,throughput,rtt,jitter,packet_loss_rate,connection_establishment_time
12000,0.025,0.5,5242880,0.045,0.003,0.001,0.082
```

#### Metrics Collector
```python
# metrics/collector.py
class MetricsCollector:
    """Collects metrics during simulation execution."""

    def __init__(self, connection):
        self.connection = connection
        self.start_time = None
        self.bytes_sent = 0
        self.packet_timestamps = []

    def record_packet_sent(self, size: int):
        """Record a sent packet."""
        pass

    def record_packet_received(self, timestamp: float):
        """Record packet receive time for jitter calculation."""
        pass

    def calculate_metrics(self) -> dict:
        """Calculate all 5 metrics."""
        return {
            "throughput": self._calc_throughput(),
            "rtt": self._calc_rtt(),
            "jitter": self._calc_jitter(),
            "packet_loss_rate": self._calc_loss_rate(),
            "connection_establishment_time": self._calc_connection_time(),
        }
```

#### Metrics Exporter
```python
# metrics/exporter.py
class MetricsExporter:
    """Exports metrics to CSV files."""

    def __init__(self, output_dir: str = "output/measurements"):
        self.output_dir = output_dir

    def export(
        self,
        application_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_factor: float,
        metrics: dict
    ):
        """Export metrics to CSV file with standardized naming."""
        filename = f"{application_type}_{initial_cw}_{max_ack_delay}_{loss_factor}.csv"
        # Write CSV with headers and data
        pass
```

---

### 4. Grid Search Code (`grid_search/`)

Orchestrates the complete parameter sweep across all application types.

#### Parameter Values (4 values each)

| Parameter | Value 1 | Value 2 | Value 3 | Value 4 |
|-----------|---------|---------|---------|---------|
| **Initial CW** | 12,000 (10 pkts) | 36,000 (30 pkts) | 72,000 (60 pkts) | 120,000 (100 pkts) |
| **Max ACK Delay** | 0.002 (2ms) | 0.010 (10ms) | 0.025 (25ms) | 0.050 (50ms) |
| **Loss Reduction Factor** | 0.4 | 0.5 | 0.6 | 0.7 |

#### Total Test Combinations
- 4 × 4 × 4 = **64 combinations per application type**
- 3 application types × 64 = **192 total simulations**

#### Resumable Scheduler

Enables crash recovery by tracking completed simulations via existing CSV files. When restarted, skips already-completed combinations.

```python
# grid_search/scheduler.py
from pathlib import Path

class ResumableScheduler:
    """Enables resuming grid search after crash/interruption."""

    def __init__(self, output_dir: str = "output/measurements"):
        self.output_dir = Path(output_dir)

    def is_completed(
        self,
        app_type: str,
        initial_cw: int,
        max_ack_delay: float,
        loss_factor: float
    ) -> bool:
        """Check if this combination has already been completed."""
        filename = f"{app_type}_{initial_cw}_{max_ack_delay}_{loss_factor}.csv"
        return (self.output_dir / filename).exists()

    def get_pending_combinations(
        self,
        app_types: list,
        icw_values: list,
        ack_delay_values: list,
        loss_factor_values: list
    ) -> list:
        """Return only combinations that haven't been completed."""
        pending = []

        for app_type in app_types:
            for icw in icw_values:
                for ack_delay in ack_delay_values:
                    for loss_factor in loss_factor_values:
                        if not self.is_completed(app_type, icw, ack_delay, loss_factor):
                            pending.append({
                                "app_type": app_type,
                                "initial_cw": icw,
                                "max_ack_delay": ack_delay,
                                "loss_factor": loss_factor,
                            })

        return pending

    def get_progress(self, total: int) -> tuple:
        """Return (completed, total) count."""
        completed = len(list(self.output_dir.glob("*.csv")))
        return completed, total
```

**Resumability Behavior**:
| Scenario | What Happens |
|----------|--------------|
| Fresh start | Runs all 192 simulations |
| Crash at simulation #50 | Restart detects 50 CSV files, runs remaining 142 |
| All complete | Prints "192/192 completed" and exits |

#### Grid Search Executor

Uses the scheduler to support resumability.

```python
# grid_search/executor.py
class GridSearchExecutor:
    """Executes grid search over all parameter combinations with resumability."""

    INITIAL_CW_VALUES = [12000, 36000, 72000, 120000]
    MAX_ACK_DELAY_VALUES = [0.002, 0.010, 0.025, 0.050]
    LOSS_FACTOR_VALUES = [0.4, 0.5, 0.6, 0.7]

    APPLICATION_TYPES = ["video_streaming", "file_transfer", "conference_call"]

    def __init__(self):
        self.scheduler = ResumableScheduler()
        self.total_combinations = len(self.APPLICATION_TYPES) * 64  # 192

    async def execute(self):
        """
        Run grid search with resumability support.

        On restart after crash:
        - Checks which CSV files already exist
        - Skips completed combinations
        - Continues from where it stopped
        """
        # Get only pending (not yet completed) combinations
        pending = self.scheduler.get_pending_combinations(
            self.APPLICATION_TYPES,
            self.INITIAL_CW_VALUES,
            self.MAX_ACK_DELAY_VALUES,
            self.LOSS_FACTOR_VALUES
        )

        completed, total = self.scheduler.get_progress(self.total_combinations)
        print(f"Progress: {completed}/{total} completed, {len(pending)} remaining")

        if not pending:
            print("All simulations complete!")
            return

        for i, combo in enumerate(pending, start=1):
            print(f"Running {completed + i}/{total}: {combo['app_type']} "
                  f"ICW={combo['initial_cw']} ACK={combo['max_ack_delay']} "
                  f"LF={combo['loss_factor']}")

            runner = SimulationRunner(
                combo["app_type"],
                combo["initial_cw"],
                combo["max_ack_delay"],
                combo["loss_factor"]
            )
            result = await runner.run()

            # Save CSV immediately after each simulation (enables resumability)
            exporter = MetricsExporter()
            exporter.export(
                combo["app_type"],
                combo["initial_cw"],
                combo["max_ack_delay"],
                combo["loss_factor"],
                result.metrics
            )

        print(f"Grid search complete! All {total} simulations finished.")
```

---

### 5. Results Report Code (`results/`)

Analyzes all CSV files and generates the final research report.

#### Analysis Goals
| Application Type | Find Best Parameters For |
|------------------|-------------------------|
| Video Streaming | Lowest latency (RTT) |
| File Transfer | Highest throughput |
| Conference Calls | Lowest jitter |

#### Results Analyzer
```python
# results/analyzer.py
import pandas as pd
from pathlib import Path

class ResultsAnalyzer:
    """Analyzes grid search results to find optimal parameters."""

    def __init__(self, measurements_dir: str = "output/measurements"):
        self.measurements_dir = Path(measurements_dir)

    def load_all_results(self) -> pd.DataFrame:
        """Load all CSV files into a single DataFrame."""
        all_data = []
        for csv_file in self.measurements_dir.glob("*.csv"):
            df = pd.read_csv(csv_file)
            # Parse application type from filename
            app_type = csv_file.stem.split("_")[0] + "_" + csv_file.stem.split("_")[1]
            df["application_type"] = app_type
            all_data.append(df)
        return pd.concat(all_data, ignore_index=True)

    def find_best_video_streaming(self, df: pd.DataFrame) -> dict:
        """Find parameters with lowest RTT for video streaming."""
        video_df = df[df["application_type"] == "video_streaming"]
        best_row = video_df.loc[video_df["rtt"].idxmin()]
        return best_row.to_dict()

    def find_best_file_transfer(self, df: pd.DataFrame) -> dict:
        """Find parameters with highest throughput for file transfer."""
        file_df = df[df["application_type"] == "file_transfer"]
        best_row = file_df.loc[file_df["throughput"].idxmax()]
        return best_row.to_dict()

    def find_best_conference_call(self, df: pd.DataFrame) -> dict:
        """Find parameters with lowest jitter for conference calls."""
        conf_df = df[df["application_type"] == "conference_call"]
        best_row = conf_df.loc[conf_df["jitter"].idxmin()]
        return best_row.to_dict()

    def analyze_trends(self, df: pd.DataFrame) -> dict:
        """Identify trends in the data."""
        trends = {}

        # Trend: How does Initial CW affect throughput?
        trends["icw_vs_throughput"] = df.groupby("initial_congestion_window")["throughput"].mean()

        # Trend: How does Max ACK Delay affect RTT?
        trends["ack_delay_vs_rtt"] = df.groupby("max_ack_delay")["rtt"].mean()

        # Trend: How does Loss Factor affect jitter?
        trends["loss_factor_vs_jitter"] = df.groupby("loss_reduction_factor")["jitter"].mean()

        return trends
```

#### Report Generator
```python
# results/report_generator.py
class ReportGenerator:
    """Generates final research report."""

    def generate(self, analysis_results: dict) -> str:
        """Generate markdown research report."""
        report = """
# QUIC Parameter Tuning Research Report

## Best Parameters by Application Type

### Video Streaming (Optimized for Lowest Latency)
- Initial Congestion Window: {video[initial_congestion_window]}
- Max ACK Delay: {video[max_ack_delay]}
- Loss Reduction Factor: {video[loss_reduction_factor]}
- **Achieved RTT: {video[rtt]:.3f}s**

### File Transfer (Optimized for Highest Throughput)
- Initial Congestion Window: {file[initial_congestion_window]}
- Max ACK Delay: {file[max_ack_delay]}
- Loss Reduction Factor: {file[loss_reduction_factor]}
- **Achieved Throughput: {file[throughput]:.2f} bytes/s**

### Conference Calls (Optimized for Lowest Jitter)
- Initial Congestion Window: {conf[initial_congestion_window]}
- Max ACK Delay: {conf[max_ack_delay]}
- Loss Reduction Factor: {conf[loss_reduction_factor]}
- **Achieved Jitter: {conf[jitter]:.4f}s**

## Observed Trends

{trends_section}

## Conclusions

{conclusions}
"""
        return report.format(**analysis_results)
```

---

## Selected Parameters - Technical Details

### Parameter 1: Initial Congestion Window

**Purpose**: Controls how many bytes can be sent immediately after connection establishment, before receiving any ACKs.

| Attribute | Value |
|-----------|-------|
| Location | `code/aioquic/src/aioquic/quic/recovery.py` |
| Constant | `K_INITIAL_WINDOW` |
| Default | `10 * MAX_DATAGRAM_SIZE` (12,000 bytes) |
| Grid Search Values | 12,000 / 36,000 / 72,000 / 120,000 bytes |
| Modification | Change constant value |

### Parameter 2: Max ACK Delay

**Purpose**: Maximum time the receiver waits before sending an acknowledgment.

| Attribute | Value |
|-----------|-------|
| Location | `code/aioquic/src/aioquic/quic/configuration.py` |
| Variable | `max_ack_delay` |
| Default | 0.025 seconds (25ms) |
| Grid Search Values | 0.002 / 0.010 / 0.025 / 0.050 seconds |
| Modification | QuicConfiguration API |

### Parameter 3: Loss Reduction Factor

**Purpose**: Determines how aggressively the congestion window is reduced when packet loss is detected.

| Attribute | Value |
|-----------|-------|
| Location | `code/aioquic/src/aioquic/quic/recovery.py` |
| Constant | `K_LOSS_REDUCTION_FACTOR` |
| Default | 0.5 |
| Grid Search Values | 0.4 / 0.5 / 0.6 / 0.7 |
| Modification | Change constant value |

---

## Implementation Plan

### Phase 1: Foundation Setup
1. **Environment Setup**
   - Create `code/` directory structure
   - Fork aioquic repository into `code/aioquic/`
   - Install in editable mode: `pip install -e code/aioquic`
   - Generate self-signed TLS certificates in `code/certs/`

2. **Basic Client-Server Implementation**
   - Implement `simulation/server.py`
   - Implement `simulation/client.py`
   - Verify 3-stream connection works

### Phase 2: Synthesizers & Metrics
1. **Data Synthesizers**
   - Implement `synthesizers/video_streaming.py`
   - Implement `synthesizers/file_transfer.py`
   - Implement `synthesizers/conference_call.py`

2. **Metrics Collection**
   - Implement `metrics/collector.py`
   - Implement `metrics/calculator.py`
   - Implement `metrics/exporter.py`

### Phase 3: Simulation & Grid Search
1. **Simulation Runner**
   - Implement `simulation/runner.py`
   - Integrate synthesizers with simulation
   - Integrate metrics collection

2. **Grid Search**
   - Implement `grid_search/parameter_space.py`
   - Implement `grid_search/executor.py`
   - Test with subset of parameter combinations

### Phase 4: Results & Analysis
1. **Results Analysis**
   - Implement `results/analyzer.py`
   - Implement `results/report_generator.py`

2. **Full Execution**
   - Run complete grid search (192 simulations)
   - Generate final research report

---

## Test Matrix

### Parameter Values (4 each)

| Parameter | Value 1 | Value 2 | Value 3 | Value 4 |
|-----------|---------|---------|---------|---------|
| Initial CW | 12KB | 36KB | 72KB | 120KB |
| Max ACK Delay | 2ms | 10ms | 25ms | 50ms |
| Loss Factor | 0.4 | 0.5 | 0.6 | 0.7 |

### Total Combinations
- **64 combinations per application type** (4 × 4 × 4)
- **192 total simulations** (64 × 3 application types)
- **192 CSV output files**

---

## Success Criteria

| Transmission Type | Metric to Optimize | Target |
|-------------------|-------------------|--------|
| File Transfer | Highest Throughput | >90% bandwidth |
| Video Streaming | Lowest Latency (RTT) | <50ms |
| Conference Calls | Lowest Jitter | <20ms |

---

## Deliverables

1. Complete source code in `code/` directory with documentation
2. Forked aioquic with parameter modifications
3. 192 CSV measurement files in `output/measurements/`
4. Final research report in `output/reports/`
5. Parameter optimization recommendations per application type
6. Trend analysis showing parameter effects on metrics

---

## Appendix: Quick Start

### Setup Commands
```bash
# Create directory structure
mkdir -p code/{synthesizers,simulation,metrics,grid_search,results,config,output/{measurements,reports},certs}

# Clone aioquic
git clone https://github.com/aiortc/aioquic.git code/aioquic
pip install -e code/aioquic

# Generate certificates
openssl req -x509 -newkey rsa:2048 -keyout code/certs/key.pem -out code/certs/cert.pem -days 365 -nodes -subj "/CN=localhost"

# Install dependencies
pip install pandas cryptography
```

### Run Grid Search
```bash
python code/main.py --run-grid-search
```

### Generate Report
```bash
python code/main.py --generate-report
```
