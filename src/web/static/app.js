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

    // Direct mode toggle
    document.getElementById('direct-mode-toggle').addEventListener('change', function(e) {
        const directMode = e.target.checked;
        apiCall('/api/ev/mode', 'POST', { direct_mode: directMode });
        updateModeUI(directMode);
    });

    // Direct current slider
    document.getElementById('direct-current').addEventListener('input', function(e) {
        document.getElementById('direct-current-value').textContent = parseFloat(e.target.value).toFixed(1);
    });

    document.getElementById('direct-current').addEventListener('change', function(e) {
        apiCall('/api/ev/direct_current', 'POST', { amps: parseFloat(e.target.value) });
    });

    // Current variance toggle
    document.getElementById('variance-toggle').addEventListener('change', function(e) {
        apiCall('/api/ev/current_variance', 'POST', { enabled: e.target.checked });
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

// Update UI based on current control mode
function updateModeUI(directMode) {
    const batteryControls = document.getElementById('battery-controls');
    const directControls = document.getElementById('direct-controls');
    const modeLabel = document.getElementById('mode-label');

    if (directMode) {
        batteryControls.style.display = 'none';
        directControls.style.display = 'block';
        modeLabel.textContent = 'Direct Control';
    } else {
        batteryControls.style.display = 'block';
        directControls.style.display = 'none';
        modeLabel.textContent = 'Battery Emulation';
    }
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

    // LCD Display
    const row1 = evse.lcd_row1 || "OpenEVSE      ";
    const row2 = evse.lcd_row2 || "v8.2.1        ";
    document.getElementById('lcd-row1').textContent = row1;
    document.getElementById('lcd-row2').textContent = row2;

    // LCD Backlight color - auto-update based on EVSE state if not explicitly set
    let color = evse.lcd_backlight_color !== undefined ? evse.lcd_backlight_color : 7;
    
    // Auto-update backlight based on state (like real OpenEVSE firmware)
    const stateName = evse.state_name || 'UNKNOWN';
    if (stateName.includes('NOT_CONNECTED')) {
        color = 2; // GREEN - No EV Connected (active/ready)
    } else if (stateName.includes('CONNECTED')) {
        color = 3; // YELLOW - Connected, but not charging
    } else if (stateName.includes('CHARGING')) {
        color = 6; // CYAN/TEAL - Charging
    } else if (stateName.includes('ERROR')) {
        color = 1; // RED - Fault
    } else if (stateName.includes('SLEEP')) {
        // Sleep mode: CYAN/TEAL if EV connected, PURPLE/VIOLET if disconnected
        color = ev.connected ? 6 : 5; // TEAL if connected, VIOLET if disconnected
    }
    
    // Map color codes to CSS classes
    const backlightColors = {
        0: 'Off',
        1: 'Red',
        2: 'Green',
        3: 'Yellow',
        4: 'Blue',
        5: 'Violet',
        6: 'Teal',
        7: 'White'
    };
    
    const backlightClasses = {
        0: 'lcd-backlight-off',
        1: 'lcd-backlight-red',
        2: 'lcd-backlight-green',
        3: 'lcd-backlight-yellow',
        4: 'lcd-backlight-blue',
        5: 'lcd-backlight-violet',
        6: 'lcd-backlight-teal',
        7: 'lcd-backlight-white'
    };
    
    // Apply backlight color to LCD rows
    const row1El = document.getElementById('lcd-row1');
    const row2El = document.getElementById('lcd-row2');
    
    // Remove all backlight classes
    Object.values(backlightClasses).forEach(cls => {
        row1El.classList.remove(cls);
        row2El.classList.remove(cls);
    });
    
    // Add current backlight class
    const backlightClass = backlightClasses[color] || backlightClasses[7];
    row1El.classList.add(backlightClass);
    row2El.classList.add(backlightClass);
    
    document.getElementById('lcd-backlight-color').textContent = backlightColors[color] || 'Unknown';
    
    // EVSE State
    const stateElement = document.getElementById('evse-state');
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

    // Read-only EVSE configuration
    document.getElementById('current-capacity-value').textContent = `${evse.current_capacity} A`;
    document.getElementById('service-level-value').textContent = evse.service_level || 'Unknown';
    document.getElementById('firmware-version').textContent = evse.firmware_version || '-';
    document.getElementById('protocol-version').textContent = evse.protocol_version || '-';

    // EV sliders
    document.getElementById('battery-soc').value = ev.soc;
    document.getElementById('battery-soc-value').textContent = ev.soc;

    // Sync direct mode UI
    const directModeToggle = document.getElementById('direct-mode-toggle');
    if (directModeToggle.checked !== ev.direct_mode) {
        directModeToggle.checked = ev.direct_mode;
        updateModeUI(ev.direct_mode);
    }

    // Update direct current slider max to current_capacity * 1.1
    const maxDirectCurrent = Math.ceil(evse.current_capacity * 1.1 * 10) / 10;
    const directCurrentSlider = document.getElementById('direct-current');
    directCurrentSlider.max = maxDirectCurrent;
    directCurrentSlider.value = ev.direct_current_amps;
    document.getElementById('direct-current-value').textContent = ev.direct_current_amps.toFixed(1);

    // Sync variance toggle
    const varianceToggle = document.getElementById('variance-toggle');
    if (varianceToggle.checked !== ev.current_variance_enabled) {
        varianceToggle.checked = ev.current_variance_enabled;
    }
    const varianceLabel = document.getElementById('variance-label');
    if (ev.current_variance_enabled) {
        varianceLabel.textContent = ev.direct_mode ? '±1%' : '-1%';
    } else {
        varianceLabel.textContent = 'Off';
    }
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
    
    // Note: Direct serial port communication from browser is not possible
    // In a real setup, this would be sent via the backend API to the virtual serial port
    // For demonstration purposes, we show the command would be sent
    addSerialLine('(Serial commands are sent to the virtual serial port by the backend)', 'info');
    
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
