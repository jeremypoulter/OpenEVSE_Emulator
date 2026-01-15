# OpenEVSE Emulator Specification

## Overview

The OpenEVSE Emulator is a Python-based software emulator that simulates both
the OpenEVSE charging station firmware and a connected Electric Vehicle (EV).
It enables WiFi firmware developers to test and develop against a virtual
charging station without requiring physical hardware.

## Architecture

### Components

1. **RAPI Protocol Handler**: Implements the OpenEVSE RAPI (Remote API) protocol for serial communication
2. **EVSE State Machine**: Manages the charging station states according to SAE J1772 standard
3. **EV Simulator**: Simulates an electric vehicle with configurable behaviors
4. **Web API**: REST API and WebSocket interface for controlling the emulator
5. **Web UI**: Browser-based control panel for interacting with the emulator

### System Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                        Web UI (HTML/CSS/JS)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP/WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                     Web API (Flask)                          │
│  - REST endpoints for control                                │
│  - WebSocket for real-time updates                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   Emulator Core                              │
│  ┌────────────────────┐  ┌────────────────────┐             │
│  │  EVSE State        │  │  EV Simulator      │             │
│  │  Machine           │◄─┤  - Connection      │             │
│  │  - State A,B,C,D   │  │  - Battery SoC     │             │
│  │  - Current limit   │  │  - Charge rate     │             │
│  │  - Temperature     │  │  - Error modes     │             │
│  └─────────┬──────────┘  └────────────────────┘             │
│            │                                                  │
│  ┌─────────▼──────────┐                                      │
│  │  RAPI Protocol     │                                      │
│  │  Handler           │                                      │
│  │  - Command parser  │                                      │
│  │  - Response gen    │                                      │
│  └─────────┬──────────┘                                      │
└────────────┼─────────────────────────────────────────────────┘
             │
┌────────────▼──────────────┐
│  Virtual Serial Port      │
│  (pty or TCP socket)      │
└───────────────────────────┘
```text

## RAPI Protocol Implementation

### Protocol Specification

The RAPI protocol uses ASCII commands with the following format:

- Commands start with `$`
- Followed by a two-letter command code
- Optional parameters separated by spaces
- End with carriage return `\r` (and optionally `\n`)
- Responses: `$OK [data]\r` for success, `$NK\r` for failure

### Supported Commands

#### Query Commands (Gx)

| Command | Description | Response Format |
| --------- | ------------- | ----------------- |
| `$GS` | Get EVSE state | `$OK <state> <elapsed_time>` |
| `$GG` | Get real-time current and voltage | `$OK <milliamps> <millivolts> <state> <flags>` |
| `$GP` | Get temperature | `$OK <temp_ds> <temp_mcp> <temp_ds_err> <temp_mcp_err>` |
| `$GV` | Get version | `$OK <firmware_version> <protocol_version>` |
| `$GU` | Get energy usage | `$OK <wh> <watt_sec>` |
| `$GC` | Get current capacity | `$OK <capacity_amps>` |
| `$GE` | Get settings | `$OK <current_capacity> <flags>` |
| `$GA` | Get ammeter settings | `$OK <current_scale> <offset>` |
| `$GT` | Get time limit | `$OK <time_limit>` |
| `$GF` | Get fault counters | `$OK <gfci_count> <no_gnd_count> <stuck_relay_count>` |
| `$GH` | Get kWh limit | `$OK <kwh_limit>` |

#### Control Commands (Sx/Fx)

| Command | Description | Response |
| --------- | ------------- | ---------- |
| `$SC <amps>` | Set current capacity (6-80A) | `$OK` or `$NK` |
| `$SL <level>` | Set service level (1=L1, 2=L2, A=Auto) | `$OK` or `$NK` |
| `$SE <0\ | 1>` | Set echo mode | `$OK` |
| `$ST <minutes>` | Set time limit | `$OK` or `$NK` |
| `$SH <kwh>` | Set kWh limit | `$OK` or `$NK` |
| `$FE` | Enable charging (sleep → active) | `$OK` or `$NK` |
| `$FD` | Disable charging (sleep mode) | `$OK` |
| `$FR` | Reset (restart EVSE) | `$OK` |
| `$F1` | Enable GFCI self-test | `$OK` |
| `$F0` | Disable GFCI self-test | `$OK` |

### EVSE States

The emulator implements the SAE J1772 charging states:

| State | Code | Description | Pilot Voltage | LED Color |
| ------- | ------ | ------------- | --------------- | ----------- |
| A | 0x01 | Ready (Not Connected) | +12V | Green |
| B | 0x02 | Connected (Not Charging) | +9V | Yellow |
| C | 0x03 | Charging | +6V | Blue |
| D | 0x04 | Ventilation Required | +3V | Red |
| Error | 0xFE | EVSE Error | N/A | Red (flashing) |
| Sleep | 0xFD | Sleep Mode | N/A | Off |

State transitions are triggered by:

- EV connection/disconnection
- Vehicle requesting charge
- Command to enable/disable charging
- Error conditions

## EV Simulator

### Configurable Parameters

- **Connection State**: Connected, Disconnected
- **Charge Request**: Idle, Requesting Charge
- **Battery State of Charge (SoC)**: 0-100%
- **Maximum Charge Rate**: User configurable (amps)
- **Charge Acceptance Rate**: Simulated battery acceptance (kW)
- **Error Modes**:
  - Diode check failure
  - Invalid pilot signal
  - Communication timeout

### Charging Simulation

When charging is active (State C):

- Battery SoC increases over time based on charge rate
- Charging automatically stops at 100% SoC
- Energy consumption is tracked (Wh)
- Temperature simulation (increases during charging)

## Error Conditions

The emulator can simulate various error conditions:

| Error | Code | Description | Trigger |
| ------- | ------ | ------------- | --------- |
| GFCI Trip | 0x01 | Ground Fault Circuit Interrupter | API/UI control |
| Stuck Relay | 0x02 | Relay failed to open/close | API/UI control |
| No Ground | 0x04 | Ground connection lost | API/UI control |
| Diode Check Failed | 0x08 | J1772 diode check failure | API/UI control |
| Over Temperature | 0x10 | Temperature threshold exceeded | Temperature > 65°C |
| GFI Self-Test Failed | 0x20 | GFCI self-test failure | API/UI control |

## Web API Specification

### REST Endpoints

#### EVSE Control

```text
POST /api/evse/enable
POST /api/evse/disable
POST /api/evse/reset
POST /api/evse/current
  Body: {"amps": 16}
POST /api/evse/service_level
  Body: {"level": "L2"}
```text

#### EVSE Status

```text
GET /api/evse/status
  Response: {
    "state": "charging",
    "current_capacity": 32,
    "temperature": 25.5,
    "voltage": 240000,
    "current": 16000,
    "energy_wh": 12500,
    "session_time": 3600,
    "flags": {...}
  }

GET /api/evse/version
  Response: {
    "firmware": "8.2.1",
    "protocol": "5.0.1"
  }
```text

#### EV Control

```text
POST /api/ev/connect
POST /api/ev/disconnect
POST /api/ev/request_charge
POST /api/ev/stop_charge
POST /api/ev/soc
  Body: {"soc": 50}
POST /api/ev/max_rate
  Body: {"amps": 32}
```text

#### EV Status

```text
GET /api/ev/status
  Response: {
    "connected": true,
    "charging": true,
    "soc": 45.5,
    "max_rate": 32,
    "actual_rate": 16.2
  }
```text

#### Error Simulation

```text
POST /api/errors/trigger
  Body: {"error": "gfci"}
POST /api/errors/clear
POST /api/errors/status
  Response: {
    "active_errors": ["gfci"],
    "error_counts": {
      "gfci": 1,
      "no_ground": 0,
      "stuck_relay": 0
    }
  }
```text

### WebSocket Interface

WebSocket endpoint: `ws://localhost:8080/ws`

#### Messages (Server → Client)

```json
{
  "type": "state_change",
  "data": {
    "old_state": "connected",
    "new_state": "charging",
    "timestamp": "2024-01-15T14:30:00Z"
  }
}

{
  "type": "status_update",
  "data": {
    "current": 16200,
    "voltage": 240000,
    "temperature": 27.3,
    "soc": 46.2,
    "energy_wh": 12750
  }
}

{
  "type": "error",
  "data": {
    "error": "gfci",
    "message": "Ground fault detected",
    "timestamp": "2024-01-15T14:30:00Z"
  }
}
```text

## Web UI

### Interface Components

1. **Status Dashboard**
   - Current EVSE state (with color-coded indicator)
   - Real-time charging metrics (current, voltage, power)
   - Battery SoC gauge
   - Session energy and time

2. **EVSE Controls**
   - Enable/Disable charging
   - Set current capacity (slider: 6-80A)
   - Set service level (L1/L2/Auto)
   - Reset button

3. **EV Controls**
   - Connect/Disconnect button
   - Request/Stop charge button
   - Battery SoC slider (0-100%)
   - Maximum charge rate selector

4. **Error Simulation Panel**
   - Checkboxes for each error type
   - Error counter display
   - Clear errors button

5. **Serial Monitor**
   - Display RAPI commands and responses
   - Command history
   - Manual command input for testing

## Virtual Serial Port

The emulator provides two options for serial communication:

1. **PTY (Pseudo-Terminal)**: Creates a virtual serial port (Unix/Linux/macOS)
   - Appears as `/dev/pts/X` or similar
   - Can be accessed by WiFi firmware or serial terminal

2. **TCP Socket**: Network-based serial port emulation
   - Listen on configurable port (default: 8023)
   - Compatible with ser2net and similar tools
   - Cross-platform support

## Configuration

Configuration file: `config.json`

```json
{
  "serial": {
    "mode": "pty",
    "tcp_port": 8023,
    "baudrate": 115200
  },
  "evse": {
    "firmware_version": "8.2.1",
    "protocol_version": "5.0.1",
    "default_current": 32,
    "service_level": "L2",
    "gfci_self_test": true
  },
  "ev": {
    "battery_capacity_kwh": 75,
    "max_charge_rate_kw": 7.2
  },
  "web": {
    "host": "0.0.0.0",
    "port": 8080
  },
  "simulation": {
    "update_interval_ms": 1000,
    "temperature_simulation": true,
    "realistic_charge_curve": true
  }
}
```text

## Testing

### Unit Tests

- RAPI command parsing and response generation
- State machine transitions
- Error condition handling
- Configuration management

### Integration Tests

- End-to-end RAPI communication
- Web API functionality
- WebSocket updates
- Serial port emulation

### Manual Testing

1. Connect to virtual serial port
2. Send RAPI commands manually
3. Verify responses match specification
4. Test state transitions
5. Validate error conditions
6. Test web UI controls

## Dependencies

- Python 3.8+
- Flask (web framework)
- Flask-SocketIO (WebSocket support)
- pyserial (serial port handling)
- Additional libraries as needed

## Future Enhancements

- MQTT support for WiFi firmware testing
- Multiple vehicle profiles (different makes/models)
- Load balancing simulation (multiple EVSEs)
- Power interruption simulation
- Advanced J1772 pilot signal simulation
- Data logging and replay
- REST API authentication
- Docker container support
