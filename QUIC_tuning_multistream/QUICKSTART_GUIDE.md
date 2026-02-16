# Step-by-Step Guide: Running QUIC Simulations with Wireless Bottleneck

This guide shows you exactly how to run QUIC simulations through wireless bottleneck scenarios on macOS.

## 🚀 Quick Start (Recommended Path)

```bash
# 1. Navigate to project
cd ~/Documents/GitHub/QUIC_research/QUIC_tuning_multistream

# 2. Start Docker container
./run-bottleneck.sh

# 3. Inside container: Run diagnostics (checks everything)
python3 diagnose.py

# 4. Inside container: Test bottleneck module (no QUIC needed)
python3 test_bottleneck_only.py

# 5. Inside container: List wireless scenarios
python3 -m wireless_bottleneck list

# 6. Inside container: (Optional) Run full QUIC example if dependencies available
python3 examples/quickstart.py
```

**What each step does:**
- ✅ Step 3: Diagnoses setup (checks Python, tc, permissions, modules)
- ✅ Step 4: Tests Linux tc (Traffic Control) integration  
- ✅ Step 5: Shows 5 wireless scenarios (stable, congested, lossy, varying, asymmetric)  
- ✅ Step 6: Runs QUIC simulation if you have aioquic and dependencies installed

---

## Prerequisites

✅ Docker Desktop installed and running  
✅ Project cloned to your local machine  
✅ Terminal open in the project root directory

---

## Method 1: Using the Helper Script (Easiest)

### Step 1: Navigate to project directory
```bash
cd ~/Documents/GitHub/QUIC_research/QUIC_tuning_multistream
```

### Step 2: Make the helper script executable (if not already)
```bash
chmod +x run-bottleneck.sh
```

### Step 3: Start interactive Docker shell
```bash
./run-bottleneck.sh
```

This will:
- Pull/build the Ubuntu container
- Install required packages (iproute2, python3)
- Mount your code directory
- Give you a shell with network privileges

### Step 4: Inside the container, verify the setup first

**FIRST: Test if the bottleneck module works (recommended)**
```bash
python3 test_bottleneck_only.py
```

This runs standalone tests without QUIC simulation to verify:
- tc (Traffic Control) is working
- Bottleneck can be set up and torn down
- Scenarios load correctly
- Metrics collection works

**If that works, then try the examples:**

**Option A: List available scenarios**
```bash
python3 -m wireless_bottleneck list
```

**Option B: Show scenario details**
```bash
python3 -m wireless_bottleneck show --scenario congested_low
```

**Option C: Validate the wireless bottleneck setup**
```bash
python3 -m wireless_bottleneck validate
```

**Option D: Run the quick start (if you have QUIC simulation dependencies)**
```bash
cd examples
python3 quickstart.py
```

**Option E: Run the full experiment suite**
```bash
cd examples
python3 wireless_experiment.py
```

### Step 5: Exit the container when done
```bash
exit
```

---

## Method 2: Manual Docker Commands

### Step 1: Build a Docker image (one-time setup)
```bash
cd ~/Documents/GitHub/QUIC_research/QUIC_tuning_multistream

docker build -t quic-bottleneck -f- . <<'EOF'
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    iproute2 \
    python3.12 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY code /app/code
WORKDIR /app/code

CMD ["/bin/bash"]
EOF
```

### Step 2: Run the container
```bash
docker run --rm -it --privileged \
    -v "$(pwd)/code:/app/code" \
    -w /app/code \
    quic-bottleneck
```

### Step 3: Inside container, run examples
```bash
# Quick start
python3 examples/quickstart.py

# Or full experiment suite
python3 examples/wireless_experiment.py
```

---

## Method 3: Direct Commands via Helper Script

You can run specific commands without entering the shell:

### List available wireless scenarios
```bash
./run-bottleneck.sh list
```

### Validate the setup
```bash
./run-bottleneck.sh validate
```

### Test a specific scenario
```bash
./run-bottleneck.sh test lossy
```

### Run the quick start example
```bash
./run-bottleneck.sh shell -c "cd examples && python3 quickstart.py"
```

---

## Understanding the Examples

### `examples/quickstart.py` - Minimal Example (5 steps)

This is the simplest way to get started:

```python
# 1. Choose a wireless scenario
scenario = get_scenario("congested_low")

# 2. Set up bottleneck (auto-cleanup with context manager)
with WirelessBottleneck(scenario.config, interface="lo") as bottleneck:
    
    # 3. Create and run QUIC simulation
    runner = SimulationRunner(
        application_type="file_transfer",
        initial_cw=12000,
        max_ack_delay=0.025,
        loss_reduction_factor=0.5,
    )
    result = await runner.run()
    
    # 4. View results
    print(f"Throughput: {result.metrics.throughput / 1_000_000:.2f} Mbps")
    
    # 5. Check bottleneck metrics
    metrics = bottleneck.get_metrics()
    print(f"Queue drops: {metrics.summary()['total_packets']['dropped']}")
```

**What it does:**
- Sets up a congested 5 Mbps wireless link with 30ms RTT and 2% loss
- Runs a single file transfer over QUIC through this link
- Shows throughput, RTT, and loss statistics
- Shows how many packets were dropped at the bottleneck

### `examples/wireless_experiment.py` - Complete Examples

This includes three comprehensive examples:

1. **Single Flow Experiment**: One QUIC connection through bottleneck
2. **Multi-Flow Experiment**: Three concurrent flows competing for bandwidth
3. **Scenario Comparison**: Test same QUIC parameters across different wireless conditions

**What it demonstrates:**
- How to collect detailed metrics from both QUIC and the bottleneck
- How to test fairness when multiple flows compete
- How to compare performance across scenarios

---

## Available Wireless Scenarios

Run `./run-bottleneck.sh list` to see all scenarios, or here's a quick reference:

| Scenario | Capacity | RTT | Loss | Use Case |
|----------|----------|-----|------|----------|
| `stable_high` | 100 Mbps | 10ms | 0.1% | Baseline testing |
| `congested_low` | 5 Mbps | 30ms | 2% | Congested WiFi |
| `varying` | 20 Mbps (±40%) | 20ms | 1% | Mobility/fading |
| `lossy` | 10 Mbps | 40ms | 5% | Poor conditions |
| `asymmetric` | 50↓/10↑ Mbps | 25ms | 0.5% | Mobile network |

---

## Typical Workflow

```bash
# 1. Start the Docker container
./run-bottleneck.sh

# 2. Inside container: List scenarios to see what's available
python3 -m wireless_bottleneck list

# 3. Show details of a specific scenario
python3 -m wireless_bottleneck show --scenario congested_low

# 4. Run the quick start to verify everything works
cd examples
python3 quickstart.py

# 5. Run the full experiment suite
python3 wireless_experiment.py

# 6. (Optional) Run validation tests
cd ..
python3 -m wireless_bottleneck validate

# 7. Exit when done
exit
```

---

## Modifying the Examples

### Change the wireless scenario:
```python
# In quickstart.py or wireless_experiment.py
scenario = get_scenario("lossy")  # Instead of "congested_low"
```

### Change QUIC parameters:
```python
runner = SimulationRunner(
    application_type="video_streaming",  # or "conference_call"
    initial_cw=20000,      # Increase initial congestion window
    max_ack_delay=0.010,   # Reduce ACK delay
    loss_reduction_factor=0.7,  # Change loss handling
)
```

### Test multiple scenarios in a loop:
```python
for scenario_name in ["stable_high", "congested_low", "lossy"]:
    scenario = get_scenario(scenario_name)
    with WirelessBottleneck(scenario.config) as bottleneck:
        runner = SimulationRunner("file_transfer", 12000, 0.025, 0.5)
        result = await runner.run()
        print(f"{scenario_name}: {result.metrics.throughput / 1_000_000:.2f} Mbps")
```

---

## Expected Output

When you run `python3 examples/quickstart.py`, you should see:

```
Setting up: Congested 5 Mbps link with moderate latency and loss
Setting up wireless bottleneck on lo...
Bottleneck active: 5.0 Mbps, 15.0ms delay, 2.0% loss
Wireless bottleneck active!

✓ Throughput: 4.23 Mbps
✓ RTT: 32.45 ms
✓ Loss: 2.15%

Bottleneck dropped 87 packets
Average queue: 23.4 packets
Bottleneck removed from lo
```

When you run `python3 examples/wireless_experiment.py`, you'll see three separate experiments with detailed output for each.

---

## Troubleshooting

### "Docker is not running"
**Solution:** Start Docker Desktop application

### "Permission denied" when running examples
**Solution:** Make sure you're inside the Docker container (not on macOS directly)

### "tc: command not found" 
**Solution:** Make sure you're using the Docker container with `--privileged` flag

### "Module not found" errors
**Solution:** 
1. Make sure you're in the `/app/code` directory: `cd /app/code`
2. Check Python path: `python3 -c "import sys; print(sys.path)"`
3. Verify files are mounted: `ls -la wireless_bottleneck/`

### "Cannot import name 'SimulationRunner'" or similar import errors
**Solution:** The example scripts assume you have the full QUIC simulation setup. Try these instead:

1. **Run diagnostics first:**
   ```bash
   python3 diagnose.py
   ```
   This will tell you exactly what's wrong!

2. **Test bottleneck module only:**
   ```bash
   python3 test_bottleneck_only.py
   ```

3. **Use CLI commands:**
   ```bash
   python3 -m wireless_bottleneck list
   python3 -m wireless_bottleneck validate
   python3 -m wireless_bottleneck show --scenario congested_low
   ```

4. **Check what's available:**
   ```bash
   ls -la simulation/
   python3 -c "from wireless_bottleneck import get_scenario; print('Bottleneck module OK')"
   ```

**Note:** The wireless bottleneck module works independently of QUIC simulations. You can test it without having a full QUIC setup using `test_bottleneck_only.py` or the CLI commands.

### "python3: command not found" inside container
**Solution:** You need to install Python and dependencies first.

**If you started the container manually** (not using `./run-bottleneck.sh`):
```bash
# Inside the container, run:
apt-get update && apt-get install -y iproute2 python3

# Then verify:
python3 --version
tc -Version

# Now you can run commands:
python3 diagnose.py
```

**Better approach:** Exit and use the helper script which installs everything automatically:
```bash
# Exit the container
exit

# Use the helper script instead
./run-bottleneck.sh
```

The helper script automatically installs Python and tc before giving you the shell.

### "Operation not permitted" errors from tc
**Solution:** Make sure Docker is running with `--privileged` flag (the script includes this)

### Commands show "command not found" inside container
**Diagnosis:**
```bash
# Inside container, check these:
which python3           # Should show: /usr/bin/python3
ls -la /app/code       # Should show your project files
pwd                    # Should show: /app/code
python3 -m wireless_bottleneck --help 2>&1  # See if module loads
```

**Solution:** If files aren't visible, exit and re-run with correct volume mount:
```bash
docker run --rm -it --privileged \
    -v "$(pwd)/code:/app/code" \
    -w /app/code \
    ubuntu:22.04 bash
```

Then inside: `apt-get update && apt-get install -y iproute2 python3`

---

## Next Steps

After running the examples:

1. **Modify parameters**: Edit the example files to test different QUIC configurations
2. **Create custom scenarios**: Add new scenarios in `wireless_bottleneck/scenarios.py`
3. **Run grid search**: Integrate with your grid search module to find optimal parameters per scenario
4. **Analyze results**: Check the `output/` directory for detailed metrics
5. **Multi-flow testing**: Test how multiple QUIC connections share bandwidth fairly

---

## Quick Reference Commands

```bash
# Start container
./run-bottleneck.sh

# List scenarios (inside container)
python3 -m wireless_bottleneck list

# Quick test (inside container)
python3 examples/quickstart.py

# Full experiments (inside container)
python3 examples/wireless_experiment.py

# Validate setup (inside container)
python3 -m wireless_bottleneck validate

# Show scenario details (inside container)
python3 -m wireless_bottleneck show --scenario lossy

# Test scenario interactively (inside container)
python3 -m wireless_bottleneck test --scenario varying
```

---

## File Locations

- Example scripts: `code/examples/quickstart.py` and `wireless_experiment.py`
- Wireless bottleneck module: `code/wireless_bottleneck/`
- Helper script: `run-bottleneck.sh` (in project root)
- Documentation: `code/wireless_bottleneck/README.md`
- Results output: `code/output/` (created after running simulations)

---

## Summary

**Simplest way to get started:**
```bash
cd ~/Documents/GitHub/QUIC_research/QUIC_tuning_multistream
./run-bottleneck.sh
# Inside container:
python3 examples/quickstart.py
```

That's it! The quickstart example will set up a wireless bottleneck, run a QUIC simulation through it, and show you the results.
