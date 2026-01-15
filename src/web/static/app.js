// OpenEVSE Emulator Web UI JavaScript

// WebSocket connection
const socket = io();

// State tracking
let currentState = {
    evse: {},
    ev: {}
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeControls();
    initializeWebSocket();
    fetchStatus();
    
    // Refresh status every 2 seconds
    setInterval(fetchStatus, 2000);
});

// Initialize control event listeners
function initializeControls() {
    // EVSE controls
    document.getElementById('btn-enable').addEventListener('click', () => apiCall('/api/evse/enable', 'POST'));
    document.getElementById('btn-disable').addEventListener('click', () => apiCall('/api/evse/disable', 'POST'));
    document.getElementById('btn-reset').addEventListener('click', () => apiCall('/api/evse/reset', 'POST'));
    
    document.getElementById('current-capacity').addEventListener('input', function(e) {
        document.getElementById('current-capacity-value').textContent = e.target.value;
    });
    
    document.getElementById('current-capacity').addEventListener('change', function(e) {
        apiCall('/api/evse/current', 'POST', { amps: parseInt(e.target.value) });
    });
    
    document.getElementById('service-level').addEventListener('change', function(e) {
        apiCall('/api/evse/service_level', 'POST', { level: e.target.value });
    });
    
    // EV controls
    document.getElementById('btn-connect').addEventListener('click', () => apiCall('/api/ev/connect', 'POST'));
    document.getElementById('btn-disconnect').addEventListener('click', () => apiCall('/api/ev/disconnect', 'POST'));
    document.getElementById('btn-request-charge').addEventListener('click', () => apiCall('/api/ev/request_charge', 'POST'));
    document.getElementById('btn-stop-charge').addEventListener('click', () => apiCall('/api/ev/stop_charge', 'POST'));
    
    document.getElementById('battery-soc').addEventListener('input', function(e) {
        document.getElementById('battery-soc-value').textContent = e.target.value;
    });
    
    document.getElementById('battery-soc').addEventListener('change', function(e) {
        apiCall('/api/ev/soc', 'POST', { soc: parseFloat(e.target.value) });
    });
    
    // Error simulation
    document.querySelectorAll('.btn-danger[data-error]').forEach(btn => {
        btn.addEventListener('click', function() {
            const errorType = this.getAttribute('data-error');
            apiCall('/api/errors/trigger', 'POST', { error: errorType });
        });
    });
    
    document.getElementById('btn-clear-errors').addEventListener('click', () => {
        apiCall('/api/errors/clear', 'POST');
    });
    
    // Serial monitor
    document.getElementById('btn-send-command').addEventListener('click', sendSerialCommand);
    document.getElementById('serial-input').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendSerialCommand();
        }
    });
}

// Initialize WebSocket event listeners
function initializeWebSocket() {
    socket.on('connect', function() {
        addSerialLine('WebSocket connected', 'info');
    });
    
    socket.on('disconnect', function() {
        addSerialLine('WebSocket disconnected', 'error');
    });
    
    socket.on('state_change', function(data) {
        addSerialLine(`State changed to: ${data.state_name}`, 'info');
        updateStatus();
    });
    
    socket.on('status_update', function(data) {
        currentState.evse = data.evse;
        currentState.ev = data.ev;
        updateDisplay();
    });
    
    socket.on('error', function(data) {
        addSerialLine(`Error: ${data.message}`, 'error');
        updateStatus();
    });
}

// Fetch current status from API
async function fetchStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        currentState.evse = data.evse;
        currentState.ev = data.ev;
        updateDisplay();
    } catch (error) {
        console.error('Failed to fetch status:', error);
    }
}

// Update status from server
async function updateStatus() {
    await fetchStatus();
    
    // Also fetch error counts
    try {
        const response = await fetch('/api/errors/status');
        const data = await response.json();
        document.getElementById('error-count-gfci').textContent = data.error_counts.gfci;
        document.getElementById('error-count-no-ground').textContent = data.error_counts.no_ground;
        document.getElementById('error-count-stuck-relay').textContent = data.error_counts.stuck_relay;
    } catch (error) {
        console.error('Failed to fetch error status:', error);
    }
}

// Update display with current state
function updateDisplay() {
    const evse = currentState.evse;
    const ev = currentState.ev;
    
    // EVSE State
    const stateElement = document.getElementById('evse-state');
    const stateName = evse.state_name || 'UNKNOWN';
    stateElement.textContent = stateName.replace('STATE_', '').replace(/_/g, ' ');
    
    // Set state color
    stateElement.className = 'status-value state-indicator';
    if (stateName.includes('NOT_CONNECTED')) {
        stateElement.classList.add('state-ready');
    } else if (stateName.includes('CONNECTED')) {
        stateElement.classList.add('state-connected');
    } else if (stateName.includes('CHARGING')) {
        stateElement.classList.add('state-charging');
    } else if (stateName.includes('ERROR')) {
        stateElement.classList.add('state-error');
    } else if (stateName.includes('SLEEP')) {
        stateElement.classList.add('state-sleep');
    }
    
    // Current and Voltage
    document.getElementById('current').textContent = `${evse.actual_current.toFixed(1)} A`;
    const voltageV = evse.voltage / 1000;
    document.getElementById('voltage').textContent = `${voltageV} V`;
    
    // Power
    const power = (evse.actual_current * voltageV) / 1000;
    document.getElementById('power').textContent = `${power.toFixed(2)} kW`;
    
    // Battery SoC
    document.getElementById('soc').textContent = `${ev.soc}%`;
    
    // Energy
    const energyKwh = evse.session_energy_wh / 1000;
    document.getElementById('energy').textContent = `${energyKwh.toFixed(2)} kWh`;
    
    // Session Time
    const sessionTime = formatTime(evse.session_time);
    document.getElementById('session-time').textContent = sessionTime;
    
    // Temperature
    document.getElementById('temperature').textContent = `${evse.temperature_ds.toFixed(1)}°C`;
    
    // Update controls to match state
    document.getElementById('current-capacity').value = evse.current_capacity;
    document.getElementById('current-capacity-value').textContent = evse.current_capacity;
    
    document.getElementById('battery-soc').value = ev.soc;
    document.getElementById('battery-soc-value').textContent = ev.soc;
}

// Format time in HH:MM:SS
function formatTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

function pad(num) {
    return num.toString().padStart(2, '0');
}

// Make API call
async function apiCall(endpoint, method = 'GET', body = null) {
    try {
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            }
        };
        
        if (body) {
            options.body = JSON.stringify(body);
        }
        
        const response = await fetch(endpoint, options);
        const data = await response.json();
        
        if (!response.ok) {
            addSerialLine(`API Error: ${data.error || 'Unknown error'}`, 'error');
        } else {
            updateStatus();
        }
    } catch (error) {
        console.error('API call failed:', error);
        addSerialLine(`API call failed: ${error.message}`, 'error');
    }
}

// Send serial command
function sendSerialCommand() {
    const input = document.getElementById('serial-input');
    const command = input.value.trim();
    
    if (!command) return;
    
    // Add command to display
    addSerialLine(command, 'command');
    
    // Note: In a real implementation, this would send to the serial port
    // For now, we'll just show it was sent
    addSerialLine('(Command would be sent to virtual serial port)', 'info');
    
    input.value = '';
}

// Add line to serial monitor
function addSerialLine(text, type = 'info') {
    const output = document.getElementById('serial-output');
    const line = document.createElement('div');
    line.className = `serial-line ${type}`;
    line.textContent = `[${new Date().toLocaleTimeString()}] ${text}`;
    output.appendChild(line);
    
    // Auto-scroll to bottom
    output.scrollTop = output.scrollHeight;
    
    // Limit to 100 lines
    while (output.children.length > 100) {
        output.removeChild(output.firstChild);
    }
}
