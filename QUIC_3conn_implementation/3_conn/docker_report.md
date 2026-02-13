# Docker Report: Why Docker is Required for Network Simulation

## Overview

This document explains why Docker is necessary for running the QUIC 3-connection system with realistic network conditions on macOS or Windows.

## The Problem: `tc` is Linux-Only

The wireless bottleneck simulation uses **Linux Traffic Control (`tc`)**, a kernel-level tool for network emulation. This tool is **only available on Linux** and cannot run natively on macOS or Windows.

```
┌─────────────────────────────────────────────────────────────────┐
│                     PLATFORM COMPATIBILITY                       │
└─────────────────────────────────────────────────────────────────┘

  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │    Linux     │     │    macOS     │     │   Windows    │
  │              │     │              │     │              │
  │  ✅ Has tc   │     │  ❌ No tc    │     │  ❌ No tc    │
  │  ✅ Native   │     │  Need Docker │     │  Need Docker │
  └──────────────┘     └──────────────┘     └──────────────┘
```

## Why Network Simulation Matters

### Without Network Simulation (localhost)

When running on localhost without `tc`:

| Metric | Value | Problem |
|--------|-------|---------|
| Bandwidth | Unlimited (~10+ Gbps) | No congestion occurs |
| Latency | ~0.1ms | Unrealistically fast |
| Packet Loss | 0% | Loss recovery never triggers |
| Jitter | 0ms | No variation in delays |

**Result:** All congestion control parameter combinations perform identically because there's no actual network stress.

### With Network Simulation (via tc)

When running with `tc` applying network conditions:

| Metric | Value | Benefit |
|--------|-------|---------|
| Bandwidth | 5-50 Mbps (shared) | Connections must compete |
| Latency | 10-100ms | Realistic network delay |
| Packet Loss | 0.1-5% | CC algorithms must react |
| Jitter | ±5-30ms | Variable delays like real networks |

**Result:** Different CC parameters produce measurably different results, enabling meaningful research.

## What Docker Provides

Docker creates a lightweight Linux container on your macOS/Windows machine, providing:

```
┌─────────────────────────────────────────────────────────────────┐
│                     DOCKER ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────┘

  macOS / Windows Host
  ┌─────────────────────────────────────────────────────────────┐
  │                                                             │
  │   Docker Desktop                                            │
  │   ┌─────────────────────────────────────────────────────┐   │
  │   │                                                     │   │
  │   │   Linux Container                                   │   │
  │   │   ┌─────────────────────────────────────────────┐   │   │
  │   │   │                                             │   │   │
  │   │   │  • tc command (network emulation)           │   │   │
  │   │   │  • Python 3.12                              │   │   │
  │   │   │  • aioquic (QUIC library)                   │   │   │
  │   │   │  • Your 3-connection code                   │   │   │
  │   │   │  • TLS certificates                         │   │   │
  │   │   │                                             │   │   │
  │   │   │  Network conditions applied here:           │   │   │
  │   │   │  ┌───────────────────────────────────────┐  │   │   │
  │   │   │  │ Bandwidth: 5 Mbps                     │  │   │   │
  │   │   │  │ Latency: 30ms RTT                     │  │   │   │
  │   │   │  │ Loss: 2%                              │  │   │   │
  │   │   │  └───────────────────────────────────────┘  │   │   │
  │   │   │                                             │   │   │
  │   │   └─────────────────────────────────────────────┘   │   │
  │   │                                                     │   │
  │   └─────────────────────────────────────────────────────┘   │
  │                                                             │
  └─────────────────────────────────────────────────────────────┘
```

## What the Dockerfile Installs

| Package | Purpose |
|---------|---------|
| `iproute2` | Provides the `tc` command for traffic control |
| `python3.12` | Python runtime for your code |
| `aioquic` | QUIC protocol implementation |
| `fastapi` | Web framework for browser UI |
| `uvicorn` | ASGI server for FastAPI |
| `openssl` | Generates TLS certificates required by QUIC |
| `iputils-ping`, `net-tools` | Debugging utilities |

## The `--privileged` Flag

Docker containers run in isolation by default. The `tc` command requires kernel-level access to modify network settings, which is blocked by default.

The `--privileged` flag grants the container the necessary permissions:

```bash
# Will NOT work (tc permission denied)
docker run quic-3conn

# WILL work (tc has permission)
docker run --privileged quic-3conn
```

**Security Note:** Only use `--privileged` for trusted containers. It gives the container elevated access to the host system.

## How tc Creates the Bottleneck

The `tc` command sets up a chain of network modifications on the loopback interface:

```
┌─────────────────────────────────────────────────────────────────┐
│                     TRAFFIC CONTROL CHAIN                        │
└─────────────────────────────────────────────────────────────────┘

  QUIC Packets from all 3 connections
                    │
                    ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  1. QUEUE DISCIPLINE (qdisc)                                 │
  │     - Holds packets in a queue (50-200 packets)              │
  │     - Drops packets if queue is full                         │
  │     - Options: FIFO, RED, CoDel, PIE                         │
  └─────────────────────────────────────────────────────────────┘
                    │
                    ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  2. NETEM (Network Emulator)                                 │
  │     - Adds delay (e.g., 15ms one-way = 30ms RTT)            │
  │     - Adds packet loss (e.g., 2% random)                     │
  │     - Adds jitter (e.g., ±5ms variation)                     │
  └─────────────────────────────────────────────────────────────┘
                    │
                    ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  3. TBF (Token Bucket Filter)                                │
  │     - Enforces bandwidth limit (e.g., 5 Mbps)               │
  │     - All 3 connections SHARE this bandwidth                 │
  └─────────────────────────────────────────────────────────────┘
                    │
                    ▼
              Packets delivered
```

## Quick Start Commands

### Build the Container

```bash
cd QUIC_3conn_implementation
docker build -t quic-3conn -f 3_conn/Dockerfile .
```

### Run with Browser UI

```bash
# Run with browser UI (open http://localhost:8000 in your browser)
docker run -it --privileged -p 8000:8000 --rm quic-3conn \
    python -m main run --ui --scenario congested_low --duration 30

# Run with lossy scenario (10 Mbps, 40ms RTT, 5% loss)
docker run -it --privileged -p 8000:8000 --rm quic-3conn \
    python -m main run --ui --scenario lossy --duration 30
```

### Run Headless (No UI)

```bash
# Run without UI (just collect metrics)
docker run -it --privileged --rm quic-3conn \
    python -m main run --scenario congested_low --duration 30
```

### Using docker-compose

```bash
# Run with browser UI (http://localhost:8000)
docker-compose up quic-3conn-ui

# Run headless
SCENARIO=congested_low DURATION=30 docker-compose up quic-3conn-headless

# Validate tc setup
docker-compose run --rm validate
```

## Available Network Scenarios

| Scenario | Bandwidth | RTT | Loss | Use Case |
|----------|-----------|-----|------|----------|
| `stable_high` | 100 Mbps | 10ms | 0.1% | Baseline testing |
| `congested_low` | 5 Mbps | 30ms | 2% | **Recommended for CC testing** |
| `varying` | 20 Mbps ±40% | 20ms | 1% | Mobility/fading simulation |
| `lossy` | 10 Mbps | 40ms | 5% | Loss recovery testing |
| `asymmetric` | 50/10 Mbps | 25ms | 0.5% | Mobile network simulation |

## Summary

| Question | Answer |
|----------|--------|
| Why Docker? | `tc` command is Linux-only; Docker provides Linux environment |
| Why `--privileged`? | `tc` needs kernel access to modify network settings |
| What does the Dockerfile install? | `tc`, Python, aioquic, textual, TLS certificates |
| What happens without Docker? | No network simulation; all CC params perform identically |
| What happens with Docker? | Realistic network conditions; meaningful research results |

## Alternatives to Docker

If you prefer not to use Docker:

1. **Linux VM** - Run VirtualBox/VMware with Ubuntu
2. **WSL2** (Windows only) - Windows Subsystem for Linux supports `tc`
3. **Remote Linux Server** - Run experiments on a cloud server
4. **Native Linux** - Install Linux on your machine or dual-boot
