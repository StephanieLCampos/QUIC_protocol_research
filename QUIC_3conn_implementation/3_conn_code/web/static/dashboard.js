/**
 * QUIC 3-Connection Dashboard - real-time WebSocket client.
 *
 * Front-end for the live dashboard. Opens a WebSocket to the FastAPI server,
 * renders incoming metrics for all three connections, and sends parameter and
 * network-condition changes back.
 *
 * Responsibilities:
 *   - maintain the WebSocket connection and reconnect if it drops
 *   - render per-connection throughput, RTT, jitter and loss as they arrive
 *   - display Q-learning actions and their outcomes as the agent runs
 *   - translate the single "quality" slider into concrete network parameters
 *   - debounce slider input so dragging does not flood the server with
 *     bottleneck reconfigurations
 *
 * Throughput is displayed from the per-epoch delta rather than a cumulative
 * average, so the graph responds visibly when a parameter or the link changes.
 *
 * Connections:
 *   Served by  : web/server.py, alongside index.html and styles.css
 *   Talks to   : WebSocket /ws for metrics; POST routes for parameter and
 *                network updates
 *   Mirrors    : the quality-to-parameter mapping in wireless_bottleneck's
 *                bottleneck.py, which must be kept in step with
 *                qualityToParams() below
 */

let ws = null;
let startTime = Date.now();
let currentConnId = 1;

// Q-Learning history tracking
let lastHistoryLength = 0;

// Network slider state
let sliderOverrideActive = false;
let sliderDebounceTimer = null;

// Connection names mapping
const CONN_NAMES = {
    1: "Video Streaming",
    2: "File Transfer",
    3: "Conference Call"
};

// Quality → parameter mapping (mirrors Python CQV mappings in bottleneck.py)
// quality is 0–100; matches: 100=stable_high-like, 0=congested_low-like
function qualityToParams(quality) {
    const q = quality / 100;  // normalise to [0,1]
    return {
        bandwidth_mbps: parseFloat((1 + (50 - 1) * Math.pow(q, 0.8)).toFixed(1)),
        delay_ms:       Math.round(80 - (80 - 5) * q),
        jitter_ms:      Math.max(1, Math.round(25 - (25 - 1) * q)),
        loss_pct:       parseFloat((0.1 + (15 - 0.1) * Math.pow(1 - q, 1.5)).toFixed(2)),
    };
}

function onMasterSlider(value) {
    const quality = parseInt(value);
    document.getElementById('master-quality-val').textContent = quality;
    const p = qualityToParams(quality);
    // Push derived values into individual sliders
    document.getElementById('sl-bandwidth').value = p.bandwidth_mbps;
    document.getElementById('sl-bandwidth-val').textContent = p.bandwidth_mbps.toFixed(1);
    document.getElementById('sl-delay').value = p.delay_ms;
    document.getElementById('sl-delay-val').textContent = p.delay_ms;
    document.getElementById('sl-jitter').value = p.jitter_ms;
    document.getElementById('sl-jitter-val').textContent = p.jitter_ms;
    document.getElementById('sl-loss').value = p.loss_pct;
    document.getElementById('sl-loss-val').textContent = p.loss_pct.toFixed(1);
    scheduleNetworkUpdate();
}

function onIndividualSlider() {
    // Update display values
    const bw  = parseFloat(document.getElementById('sl-bandwidth').value);
    const dl  = parseInt(document.getElementById('sl-delay').value);
    const jit = parseInt(document.getElementById('sl-jitter').value);
    const ls  = parseFloat(document.getElementById('sl-loss').value);
    document.getElementById('sl-bandwidth-val').textContent = bw.toFixed(1);
    document.getElementById('sl-delay-val').textContent = dl;
    document.getElementById('sl-jitter-val').textContent = jit;
    document.getElementById('sl-loss-val').textContent = ls.toFixed(1);
    scheduleNetworkUpdate();
}

function scheduleNetworkUpdate() {
    // Debounce: send at most one request per 200ms while dragging
    clearTimeout(sliderDebounceTimer);
    sliderDebounceTimer = setTimeout(sendNetworkOverride, 200);
}

async function sendNetworkOverride() {
    const payload = {
        bandwidth_mbps: parseFloat(document.getElementById('sl-bandwidth').value),
        delay_ms:       parseInt(document.getElementById('sl-delay').value),
        jitter_ms:      parseInt(document.getElementById('sl-jitter').value),
        loss_pct:       parseFloat(document.getElementById('sl-loss').value),
        release:        false,
    };
    try {
        const res = await fetch('/api/network', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.success) {
            sliderOverrideActive = true;
            document.getElementById('override-badge').classList.remove('hidden');
            document.getElementById('release-override-btn').classList.remove('hidden');
        }
    } catch (e) {
        console.warn('Network override request failed (simulation may not be running):', e);
    }
}

async function releaseOverride() {
    try {
        await fetch('/api/network', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bandwidth_mbps: 0, delay_ms: 0, jitter_ms: 0, loss_pct: 0, release: true }),
        });
    } catch (e) { /* ignore */ }
    sliderOverrideActive = false;
    document.getElementById('override-badge').classList.add('hidden');
    document.getElementById('release-override-btn').classList.add('hidden');
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    connectWebSocket();
    setupFormHandler();
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
            updateDashboard(data);
            updateQLearningSection(data);
            updateNetworkConfig(data);
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

function updateDashboard(data) {
    const elapsed = (Date.now() - startTime) / 1000;
    document.getElementById('duration').textContent = `Duration: ${elapsed.toFixed(1)}s`;

    let totalTx = 0;

    for (let connId = 1; connId <= 3; connId++) {
        const metrics = data.metrics[connId] || {};
        const params = data.params[connId] || {};

        // Use per-epoch delta throughput (throughput_acked_delta) for responsive display
        // Fall back to cumulative throughput_acked if delta not available
        // Do NOT fall back to 'throughput' - that's offered/send rate, not actual throughput
        let throughputBps = metrics.throughput_acked_delta || metrics.throughput_acked || 0;
        const throughputMbps = throughputBps / 1_000_000;  // Convert B/s to MB/s (displayed as Mbps)

        const rtt = (metrics.rtt || 0) * 1000;  // Convert to ms
        const latency = (metrics.latency || 0) * 1000;  // Convert to ms (one-way delay)
        const jitter = (metrics.jitter || 0) * 1000;  // Convert to ms
        const loss = (metrics.packet_loss_rate || 0) * 100;
        const bytesSent = metrics.bytes_sent || 0;

        document.getElementById(`tp-${connId}`).textContent = throughputMbps.toFixed(2);
        document.getElementById(`rtt-${connId}`).textContent = rtt.toFixed(1);
        document.getElementById(`latency-${connId}`).textContent = latency.toFixed(1);
        document.getElementById(`jitter-${connId}`).textContent = jitter.toFixed(2);
        document.getElementById(`loss-${connId}`).textContent = loss.toFixed(1);
        document.getElementById(`bytes-${connId}`).textContent = formatBytes(bytesSent);

        totalTx += bytesSent;

        // Update parameters display
        updateParamsDisplay(connId, params);
    }

    // Update total throughput (sum of all 3 connections)
    const totalThroughput = data.total_throughput || {};
    const totalThroughputMbps = totalThroughput.total_throughput_mbps || 0;
    document.getElementById('total-throughput').textContent = `Total Throughput: ${totalThroughputMbps.toFixed(2)} Mbps`;

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

function updateQLearningSection(data) {
    // Update Q-learning summary
    const summary = data.qlearning_summary || {};
    document.getElementById('ql-steps').textContent = `Steps: ${summary.steps || 0}`;
    document.getElementById('ql-epsilon').textContent = `Exploration: ${((summary.epsilon || 0) * 100).toFixed(1)}%`;
    document.getElementById('ql-states').textContent = `Q-States: ${summary.states_visited || 0}`;
    document.getElementById('ql-avg-reward').textContent = `Avg Reward: ${(summary.avg_reward_last_100 || 0).toFixed(3)}`;

    // Update Q-learning history
    const history = data.qlearning_history || [];

    // Only re-render if history has changed
    if (history.length !== lastHistoryLength) {
        lastHistoryLength = history.length;
        renderQLearningHistory(history);
    }
}

function updateNetworkConfig(data) {
    const config = data.scenario_config || {};

    // Update scenario name
    const scenarioName = config.scenario_name || 'none';
    document.getElementById('scenario-name').textContent = scenarioName;

    // Update primary network parameters
    const bandwidth = config.capacity_mbps || 0;
    document.getElementById('config-bandwidth').textContent = bandwidth.toFixed(1);

    const rtt = config.rtt_ms || 0;
    document.getElementById('config-rtt').textContent = rtt.toFixed(0);

    const loss = config.loss_percent || 0;
    document.getElementById('config-loss').textContent = loss.toFixed(1);

    const queueSize = config.queue_size || 0;
    document.getElementById('config-queue').textContent = queueSize;

    const discipline = config.queue_discipline || 'unknown';
    document.getElementById('config-discipline').textContent = discipline.toUpperCase();

    const timeVarying = config.time_varying || false;
    let varyingText = timeVarying ? 'Yes' : 'No';
    if (timeVarying && config.variation_info) {
        const amp = config.variation_info.amplitude_percent || 0;
        const period = config.variation_info.period_sec || 0;
        varyingText = `Yes (±${amp.toFixed(0)}%, ${period}s)`;
    }
    document.getElementById('config-varying').textContent = varyingText;
}

function renderQLearningHistory(history) {
    const container = document.getElementById('qlearning-history');

    if (history.length === 0) {
        container.innerHTML = '<p class="no-actions">Waiting for Q-learning actions...</p>';
        return;
    }

    // Show most recent actions first (reverse order)
    const reversedHistory = [...history].reverse();

    container.innerHTML = reversedHistory.map((action, idx) => {
        const actionNum = history.length - idx;
        const connName = CONN_NAMES[action.connection_id] || `Conn ${action.connection_id}`;
        const timestamp = ((action.timestamp - (startTime / 1000)) + (Date.now() - startTime) / 1000).toFixed(1);

        // Get metrics for the affected connection
        const metricsBefore = action.metrics_before[action.connection_id] || {};
        const metricsAfter = action.metrics_after[action.connection_id] || {};

        return `
            <div class="ql-action ${action.direction}">
                <div class="ql-action-header">
                    <span class="ql-action-target">
                        Action #${actionNum}: <span class="conn-name">${connName}</span>
                    </span>
                    <span class="ql-action-time">@ ${formatActionTime(action.timestamp)}s</span>
                </div>

                <div class="ql-param-change">
                    <span class="ql-param-name">${action.param_name}</span>
                    <span class="ql-param-value old">${formatParamValue(action.old_value)}</span>
                    <span class="ql-arrow">→</span>
                    <span class="ql-param-value new">${formatParamValue(action.new_value)}</span>
                </div>

                <div class="ql-metrics-comparison">
                    <div class="ql-metrics-box before">
                        <h4>Before</h4>
                        ${renderMetricsBox(metricsBefore)}
                    </div>
                    <div class="ql-metrics-box after">
                        <h4>After (settled)</h4>
                        ${renderMetricsBox(metricsAfter, metricsBefore)}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderMetricsBox(metrics, compareTo = null) {
    // Use delta throughput for display (don't fall back to offered 'throughput')
    const throughputBps = metrics.throughput_acked_delta || metrics.throughput_acked || 0;
    const throughputMbps = throughputBps / 1_000_000;
    const rtt = (metrics.rtt || 0) * 1000;
    const jitter = (metrics.jitter || 0) * 1000;
    const loss = (metrics.packet_loss_rate || 0) * 100;

    // Determine if metrics improved or degraded (for coloring)
    let tpClass = '', rttClass = '', jitterClass = '', lossClass = '';
    if (compareTo) {
        const prevTp = (compareTo.throughput_acked_delta || compareTo.throughput_acked || 0) / 1_000_000;
        const prevRtt = (compareTo.rtt || 0) * 1000;
        const prevJitter = (compareTo.jitter || 0) * 1000;
        const prevLoss = (compareTo.packet_loss_rate || 0) * 100;

        // Higher throughput is better
        if (throughputMbps > prevTp * 1.05) tpClass = 'improved';
        else if (throughputMbps < prevTp * 0.95) tpClass = 'degraded';

        // Lower RTT is better
        if (rtt < prevRtt * 0.95) rttClass = 'improved';
        else if (rtt > prevRtt * 1.05) rttClass = 'degraded';

        // Lower jitter is better
        if (jitter < prevJitter * 0.95) jitterClass = 'improved';
        else if (jitter > prevJitter * 1.05) jitterClass = 'degraded';

        // Lower loss is better
        if (loss < prevLoss * 0.95) lossClass = 'improved';
        else if (loss > prevLoss * 1.05) lossClass = 'degraded';
    }

    return `
        <div class="ql-metric-row">
            <span class="label">Throughput:</span>
            <span class="value ${tpClass}">${throughputMbps.toFixed(2)} Mbps</span>
        </div>
        <div class="ql-metric-row">
            <span class="label">RTT:</span>
            <span class="value ${rttClass}">${rtt.toFixed(1)} ms</span>
        </div>
        <div class="ql-metric-row">
            <span class="label">Jitter:</span>
            <span class="value ${jitterClass}">${jitter.toFixed(1)} ms</span>
        </div>
        <div class="ql-metric-row">
            <span class="label">Loss:</span>
            <span class="value ${lossClass}">${loss.toFixed(2)}%</span>
        </div>
    `;
}

function formatActionTime(unixTimestamp) {
    // Convert to relative time from page load
    const relativeSeconds = unixTimestamp - (startTime / 1000);
    return relativeSeconds.toFixed(1);
}

function formatParamValue(value) {
    if (typeof value === 'number') {
        return Number.isInteger(value) ? value.toString() : value.toFixed(2);
    }
    return value;
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
