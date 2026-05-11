/**
 * QUIC 3-Connection Dashboard - Real-time WebSocket client
 */

let ws = null;
let startTime = Date.now();
let currentConnId = 1;

// Snapshot tracking
let SETTLING_TIME = 2000; // Default 2 seconds in milliseconds (updated from server)
let baselineCaptured = false;
let pendingSnapshots = {}; // {connId: {timeout, params}}
let snapshots = {1: [], 2: [], 3: []}; // Stored snapshots per connection
let latestData = null; // Store latest data for snapshot capture
let previousParams = {1: null, 2: null, 3: null}; // Track param changes

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    // Fetch settling time from server
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        if (data.settling_time) {
            SETTLING_TIME = data.settling_time * 1000; // Convert to milliseconds
            console.log(`Settling time set to ${data.settling_time}s`);
            // Update the UI to show settling time
            document.querySelector('#snapshots-section h2').textContent =
                `Parameter Snapshots (captured after ${data.settling_time}s settling time)`;
        }
    } catch (e) {
        console.log('Using default settling time of 2s');
    }

    connectWebSocket();
    setupFormHandler();

    // Capture baseline after settling time
    setTimeout(() => {
        if (latestData) {
            captureBaseline();
        }
    }, SETTLING_TIME);
});

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Use localhost if host is 0.0.0.0 (server bind address, not accessible from browser)
    let host = window.location.host;
    if (host.startsWith('0.0.0.0')) {
        host = host.replace('0.0.0.0', 'localhost');
    }
    ws = new WebSocket(`${protocol}//${host}/ws`);

    ws.onopen = () => {
        console.log('WebSocket connected');
        document.getElementById('status-indicator').textContent = 'Connected';
        document.getElementById('status-indicator').className = 'status-connected';
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected, reconnecting...');
        document.getElementById('status-indicator').textContent = 'Disconnected';
        document.getElementById('status-indicator').className = 'status-disconnected';
        setTimeout(connectWebSocket, 2000);
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'update') {
            latestData = data;
            updateDashboard(data);
            checkForParamChanges(data);
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

function captureBaseline() {
    if (baselineCaptured || !latestData) return;

    for (let connId = 1; connId <= 3; connId++) {
        const metrics = latestData.metrics[connId] || {};
        const params = latestData.params[connId] || {};

        if (Object.keys(metrics).length > 0) {
            const snapshot = createSnapshot('Baseline', metrics, params);
            snapshots[connId].push(snapshot);
            previousParams[connId] = JSON.stringify(params);
        }
    }

    baselineCaptured = true;
    renderAllSnapshots();
}

function checkForParamChanges(data) {
    for (let connId = 1; connId <= 3; connId++) {
        const params = data.params[connId] || {};
        const paramsStr = JSON.stringify(params);

        // Check if params changed (and we have previous params to compare)
        if (previousParams[connId] && previousParams[connId] !== paramsStr) {
            // Cancel any pending snapshot for this connection
            if (pendingSnapshots[connId]) {
                clearTimeout(pendingSnapshots[connId].timeout);
            }

            // Schedule new snapshot after settling time
            pendingSnapshots[connId] = {
                timeout: setTimeout(() => {
                    captureParamChangeSnapshot(connId);
                }, SETTLING_TIME),
                params: {...params}
            };
        }

        previousParams[connId] = paramsStr;
    }
}

function captureParamChangeSnapshot(connId) {
    if (!latestData) return;

    const metrics = latestData.metrics[connId] || {};
    const params = latestData.params[connId] || {};

    const snapshotNum = snapshots[connId].length;
    const snapshot = createSnapshot(`Change #${snapshotNum}`, metrics, params);
    snapshots[connId].push(snapshot);

    delete pendingSnapshots[connId];
    renderSnapshots(connId);
}

function createSnapshot(label, metrics, params) {
    const elapsed = (Date.now() - startTime) / 1000;
    return {
        label: label,
        time: elapsed.toFixed(1),
        metrics: {
            throughput: ((metrics.throughput || metrics.throughput_bps || 0) / 1_000_000).toFixed(2),
            rtt: ((metrics.rtt || 0) * 1000).toFixed(1),
            loss: ((metrics.packet_loss_rate || 0) * 100).toFixed(1),
            bytes: metrics.bytes_sent || 0
        },
        params: {...params}
    };
}

function renderAllSnapshots() {
    for (let connId = 1; connId <= 3; connId++) {
        renderSnapshots(connId);
    }
}

function renderSnapshots(connId) {
    const container = document.getElementById(`snapshots-${connId}`);

    if (snapshots[connId].length === 0) {
        container.innerHTML = '<p class="no-snapshots">Baseline will be captured after settling...</p>';
        return;
    }

    container.innerHTML = snapshots[connId].map((snap, idx) => {
        const isBaseline = idx === 0;
        return `
            <div class="snapshot-item ${isBaseline ? 'baseline' : 'changed'}">
                <div class="snapshot-header">
                    <span class="snapshot-label">${snap.label}</span>
                    <span class="snapshot-time">@ ${snap.time}s</span>
                </div>
                <div class="snapshot-metrics">
                    <span>Throughput: <span class="value">${snap.metrics.throughput}</span> Mbps</span>
                    <span>RTT: <span class="value">${snap.metrics.rtt}</span> ms</span>
                    <span>Loss: <span class="value">${snap.metrics.loss}</span>%</span>
                    <span>Bytes: <span class="value">${formatBytes(snap.metrics.bytes)}</span></span>
                </div>
                <div class="snapshot-params">
                    ${Object.entries(snap.params).map(([k, v]) =>
                        `${k}: ${typeof v === 'number' ? v.toFixed(3) : v}`
                    ).join(' | ')}
                </div>
            </div>
        `;
    }).join('');
}

function updateDashboard(data) {
    const elapsed = (Date.now() - startTime) / 1000;
    document.getElementById('duration').textContent = `Duration: ${elapsed.toFixed(1)}s`;

    let totalTx = 0;

    for (let connId = 1; connId <= 3; connId++) {
        const metrics = data.metrics[connId] || {};
        const params = data.params[connId] || {};

        // Update metrics (simple text replacement - no accumulation)
        const throughput = (metrics.throughput || metrics.throughput_bps || 0) / 1_000_000;
        const rtt = (metrics.rtt || 0) * 1000;
        const loss = (metrics.packet_loss_rate || 0) * 100;
        const bytesSent = metrics.bytes_sent || 0;

        document.getElementById(`tp-${connId}`).textContent = throughput.toFixed(2);
        document.getElementById(`rtt-${connId}`).textContent = rtt.toFixed(1);
        document.getElementById(`loss-${connId}`).textContent = loss.toFixed(1);
        document.getElementById(`bytes-${connId}`).textContent = formatBytes(bytesSent);

        totalTx += bytesSent;

        // Update parameters display
        updateParamsDisplay(connId, params);
    }

    document.getElementById('total-tx').textContent = `Total TX: ${formatBytes(totalTx)}`;
}

function updateParamsDisplay(connId, params) {
    const container = document.getElementById(`params-${connId}`);
    container.innerHTML = Object.entries(params)
        .map(([key, value]) => `<div class="param-item"><span>${key}:</span> <span>${
            typeof value === 'number' ? value.toFixed(3) : value
        }</span></div>`)
        .join('');
}

function openParamEditor(connId) {
    currentConnId = connId;
    document.getElementById('modal-conn-id').textContent = connId;

    // Fetch current params
    fetch('/api/status')
        .then(res => res.json())
        .then(data => {
            const params = data.params[connId] || {};
            document.getElementById('loss_reduction_factor').value = params.loss_reduction_factor || 0.5;
            document.getElementById('cubic_c').value = params.cubic_c || 0.4;
            document.getElementById('minimum_window').value = params.minimum_window || 2;
            document.getElementById('packet_threshold').value = params.packet_threshold || 3;
            document.getElementById('time_threshold').value = params.time_threshold || 1.125;
            document.getElementById('cubic_max_idle_time').value = params.cubic_max_idle_time || 2.0;
        });

    document.getElementById('param-modal').classList.remove('hidden');
}

function closeParamEditor() {
    document.getElementById('param-modal').classList.add('hidden');
}

function setupFormHandler() {
    document.getElementById('param-form').addEventListener('submit', async (e) => {
        e.preventDefault();

        const params = [
            'loss_reduction_factor', 'cubic_c', 'minimum_window',
            'packet_threshold', 'time_threshold', 'cubic_max_idle_time'
        ];

        for (const paramName of params) {
            const value = parseFloat(document.getElementById(paramName).value);
            if (!isNaN(value)) {
                await fetch('/api/params', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        connection_id: currentConnId,
                        param_name: paramName,
                        value: value
                    })
                });
            }
        }

        closeParamEditor();
    });
}

function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
