# Running the Browser UI with Docker

This guide explains how to run the real-time browser UI dashboard while using Docker for the TC bottleneck.

---

## Overview

The UI can run inside the Docker container and be accessed from your Mac by exposing port 8000.

---

## docker-compose.yml Changes

The `clients` service was updated with:

1. **Port mapping** - `"8000:8000"` exposes the UI to your host machine
2. **`--ui` flag** - enables the FastAPI browser dashboard
3. **`--with-ml` flag** - enables Q-learning optimization
4. **`${DURATION:-30}`** - makes duration configurable via environment variable

```yaml
clients:
  image: quic-wireless
  container_name: quic-clients
  cap_add:
    - NET_ADMIN
  depends_on:
    - server
  ports:
    - "8000:8000"  # Expose UI port to host
  networks:
    quic-net:
      ipv4_address: 192.168.200.20
  volumes:
    - ./results:/app/3_conn_code/output
    - ./results:/app/3_conn_code/reports
  environment:
    - RUN_MODE=clients
    - SKIP_VETH=1
    - ENABLE_NETWORK_RTT_PROBE=0
    - SCENARIO=${SCENARIO:-congested_low}
    - TZ=America/Los_Angeles
  command: python -m main clients --server 192.168.200.10 --duration ${DURATION:-30} --scenario ${SCENARIO:-congested_low} --output-dir output --with-ml --ui
```

---

## How to Run

```bash
cd /Users/steph/dev/research_folder/GIT_QUIC_3conn/QUIC_3conn_implementation

# Build the Docker image with changes
docker-compose build

# Run with default settings (congested_low, 30 seconds)
docker-compose up

# Run with varying scenario and longer duration
SCENARIO=varying DURATION=120 docker-compose up

# Run with other scenarios
SCENARIO=lossy DURATION=60 docker-compose up
SCENARIO=stable_high DURATION=90 docker-compose up
```

---

## Access the UI

Once the containers are running, open your browser to:

**http://localhost:8000**

---

## What the UI Shows

The browser dashboard displays real-time metrics:

| Panel | Description |
|-------|-------------|
| **Throughput Graph** | Per-connection throughput over time |
| **Latency Graph** | RTT and latency measurements |
| **Jitter Graph** | Jitter measurements per connection |
| **Parameters** | Current QUIC CUBIC parameters |
| **Q-Learning** | Agent state, actions, and rewards |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Your Mac (Host)                                            │
│                                                             │
│   Browser ──────► http://localhost:8000                     │
│                         │                                   │
│                         │ port 8000 mapped                  │
│                         ▼                                   │
│   ┌─────────────────────────────────────────────────────┐  │
│   │  Docker: quic-clients container                      │  │
│   │                                                      │  │
│   │   FastAPI UI Server ◄── real-time metrics            │  │
│   │         │                      │                     │  │
│   │         │              ProcessOrchestrator           │  │
│   │         │                      │                     │  │
│   │         │              3 Worker Processes            │  │
│   │         │                      │                     │  │
│   │         │              Q-Learning Agent              │  │
│   └─────────┼──────────────────────┼─────────────────────┘  │
│             │                      │                        │
│             │           Docker Network (192.168.200.0/24)   │
│             │                      │                        │
│   ┌─────────┼──────────────────────┼─────────────────────┐  │
│   │  Docker: quic-server container │                     │  │
│   │                                ▼                     │  │
│   │              TC Bottleneck (varies by scenario)      │  │
│   │                                │                     │  │
│   │              QUIC Server ◄─────┘                     │  │
│   └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Why This Works

- **TC Bottleneck works** because traffic flows through the Docker network to the server container where Linux TC is applied
- **UI is accessible** because port 8000 is mapped from container to host
- **Real-time metrics** flow from worker processes → ProcessOrchestrator → FastAPI → Browser via WebSocket

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENARIO` | `congested_low` | Network scenario to use |
| `DURATION` | `30` | Simulation duration in seconds |

### Available Scenarios

| Scenario | Bandwidth | RTT | Loss |
|----------|-----------|-----|------|
| `stable_high` | 100 Mbps | 10ms | 0.1% |
| `congested_low` | 5 Mbps | 30ms | 2% |
| `varying` | 20 Mbps ±40% | 20ms | 1% |
| `lossy` | 10 Mbps | 40ms | 5% |
| `asymmetric` | 50↓/10↑ Mbps | 25ms | 0.5% |

---

## Stopping the Simulation

```bash
# Stop all containers
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

---

## Troubleshooting

### UI Not Loading

1. Check containers are running: `docker-compose ps`
2. Check logs: `docker-compose logs clients`
3. Ensure port 8000 isn't already in use: `lsof -i :8000`

### Port Already in Use

```bash
# Find what's using port 8000
lsof -i :8000

# Kill the process or use a different port
# Edit docker-compose.yml: ports: - "8001:8000"
# Then access http://localhost:8001
```

### UI Shows No Data

- Wait a few seconds for connections to establish
- Check Q-learning logs in terminal for activity
- Verify server container is running: `docker-compose logs server`
