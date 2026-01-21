# OpenEVSE Emulator

A Python-based software emulator for the
[OpenEVSE](https://github.com/OpenEVSE/open_evse) electric vehicle charging
station firmware. This emulator simulates both the EVSE (charging station)
and a connected EV, enabling WiFi firmware developers to test and develop
without requiring physical hardware.

## Features

- **Complete RAPI Protocol Implementation**: Full support for OpenEVSE's Remote API commands
- **SAE J1772 State Machine**: Accurate simulation of charging states (A, B, C, D)
- **EV Simulator**: Configurable battery, charging behavior, and connection states
- **Error Condition Simulation**: Test GFCI trips, stuck relays, ground faults, and more
- **Web API**: RESTful API for programmatic control
- **Real-time WebSocket Updates**: Live status updates for connected clients
- **Web UI**: Browser-based control panel with real-time visualization
- **Virtual Serial Port**: PTY or TCP socket emulation for serial communication

## Quick Start

### Prerequisites

- Python 3.8 or higher (tested on 3.8, 3.9, 3.10, 3.11, 3.12, and 3.13)
- pip (Python package manager)
- Docker (optional, for containerized deployment)

### Installation

#### Option 1: Local Installation

1. Clone the repository:

```bash
git clone https://github.com/jeremypoulter/OpenEVSE_Emulator.git
cd OpenEVSE_Emulator
```

1. Install dependencies:

```bash
pip install -r requirements.txt
```

1. Run the emulator:

```bash
python src/main.py
```

#### Option 2: Docker

1. Build and run using Docker:

```bash
docker build -t openevse-emulator .
docker run -p 8080:8080 -p 8023:8023 openevse-emulator
```

1. Or use Docker Compose:

```bash
docker-compose up
```

#### Option 3: VSCode Devcontainer

1. Open the project in VSCode
2. Install the "Remote - Containers" extension
3. Click "Reopen in Container" when prompted
4. The development environment will be automatically configured

The emulator will start with:

- Web UI accessible at: http://localhost:8080
- API documentation at: http://localhost:8080/api/docs
- WebSocket endpoint at: ws://localhost:8080/ws
- Virtual serial port (location printed in console, or TCP on port 8023)

## Usage

### Web Interface

Open your browser and navigate to `http://localhost:8080` to access the control panel:

- **Dashboard**: View real-time EVSE state, current, voltage, and battery status
- **EVSE Controls**: Enable/disable charging, set current capacity, service level
- **EV Controls**: Connect/disconnect vehicle, adjust battery SoC, set max charge rate
- **Error Simulation**: Trigger various fault conditions for testing
- **Serial Monitor**: View RAPI command/response traffic

### API Documentation

Interactive API documentation is available at `http://localhost:8080/api/docs`
using Swagger UI. The OpenAPI 3.0 specification can be accessed at
`http://localhost:8080/api/openapi.yaml`.

### REST API

Control the emulator programmatically using the REST API:

```bash
# Get EVSE status
curl http://localhost:8080/api/evse/status

# Connect EV
curl -X POST http://localhost:8080/api/ev/connect

# Set charging current to 16A
curl -X POST http://localhost:8080/api/evse/current \
  -H "Content-Type: application/json" \
  -d '{"amps": 16}'

# Enable charging
curl -X POST http://localhost:8080/api/evse/enable

# Trigger GFCI error
curl -X POST http://localhost:8080/api/errors/trigger \
  -H "Content-Type: application/json" \
  -d '{"error": "gfci"}'
```

### Serial Communication

Connect to the virtual serial port using any terminal emulator or your WiFi firmware:

```bash
# Using screen (replace with actual port from console output)
screen /dev/pts/3 115200

# Send RAPI commands
$GS<Enter>          # Get state (state, elapsed, pilot, vflags)
$GC<Enter>          # Get capacity limits (min, hw max, pilot, configured)
$SC 16<Enter>       # Set current to 16A (clamps); use "V" for volatile, "M" to set max once
$GG<Enter>          # Get current/voltage
$FE<Enter>          # Enable charging
```

### WebSocket

Subscribe to real-time updates:

```javascript
const ws = new WebSocket('ws://localhost:8080/ws');

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  console.log('Update:', msg);
  // Handle state_change, status_update, or error messages
};
```

## Configuration

Edit `config.json` to customize emulator settings:

```json
{
  "serial": {
    "mode": "pty",           // "pty" or "tcp"
    "tcp_port": 8023,
    "baudrate": 115200
  },
  "evse": {
    "firmware_version": "8.2.1",
    "protocol_version": "5.0.1",
    "default_current": 32,   // Amps
    "service_level": "L2",   // "L1", "L2", or "Auto"
    "gfci_self_test": true
  },
  "ev": {
    "battery_capacity_kwh": 75,
    "max_charge_rate_kw": 7.2
  },
  "web": {
    "host": "0.0.0.0",
    "port": 8080
  }
}
```

**Note for Docker**: When running in Docker, use `"mode": "tcp"` for the
serial port to enable network-based serial communication.

## Docker Deployment

### Building the Image

```bash
docker build -t openevse-emulator .
```

### Running with Docker

Basic run:

```bash
docker run -p 8080:8080 -p 8023:8023 openevse-emulator
```

With custom configuration:

```bash
docker run -p 8080:8080 -p 8023:8023 \
  -v $(pwd)/config.json:/app/config.json:ro \
  openevse-emulator
```

### Running with Docker Compose

```bash
# Start in foreground
docker-compose up

# Start in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### VSCode Devcontainer

The devcontainer provides a fully configured development environment with:

- Python 3.13
- All dependencies pre-installed
- VSCode extensions for Python, YAML, and OpenAPI
- Automatic linting and formatting
- Port forwarding for web UI and API

To use:

1. Install the "Remote - Containers" extension in VSCode
2. Open the project folder
3. Click "Reopen in Container" in the notification
4. Wait for the container to build and start

The emulator can be run inside the container using the integrated terminal.

## RAPI Command Reference

### Query Commands

| Command | Description | Example Response |
| --------- | ------------- | ------------------ |
| `$GS` | Get EVSE state | `$OK 3 1234` (state=3, elapsed=1234s) |
| `$GG` | Get current/voltage | `$OK 16000 240000 3 0` |
| `$GP` | Get temperature | `$OK 250 260 0 0` (25.0°C, 26.0°C) |
| `$GV` | Get version | `$OK 8.2.1 5.0.1` |
| `$GU` | Get energy usage | `$OK 12500 45000000` (12.5kWh) |
| `$GC` | Get current capacity | `$OK 32` |
| `$GF` | Get fault counters | `$OK 0 0 0` |

### Control Commands

| Command | Description | Example |
| --------- | ------------- | --------- |
| `$SC <amps>` | Set current capacity | `$SC 16` (set to 16A) |
| `$SL <level>` | Set service level | `$SL 2` (L2) |
| `$FE` | Enable charging | `$FE` |
| `$FD` | Disable (sleep) | `$FD` |
| `$FR` | Reset EVSE | `$FR` |

See [SPEC.md](SPEC.md) for complete RAPI protocol documentation.

## Architecture

```text
┌─────────────────────────────────────────────────────┐
│              Web UI (HTML/CSS/JS)                    │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP/WebSocket
┌──────────────────────▼──────────────────────────────┐
│               Web API (Flask)                        │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  ┌──────────────┐  ┌──────────────┐                 │
│  │ EVSE State   │  │ EV Simulator │                 │
│  │ Machine      │◄─┤              │                 │
│  └──────┬───────┘  └──────────────┘                 │
│         │                                            │
│  ┌──────▼───────┐                                    │
│  │ RAPI Handler │                                    │
│  └──────┬───────┘                                    │
└─────────┼────────────────────────────────────────────┘
          │
┌─────────▼──────────┐
│ Virtual Serial Port│
└────────────────────┘
```

## Development

### Project Structure

```text
OpenEVSE_Emulator/
├── src/
│   ├── emulator/
│   │   ├── evse.py          # EVSE state machine
│   │   ├── ev.py            # EV simulator
│   │   ├── rapi.py          # RAPI protocol handler
│   │   └── serial_port.py   # Virtual serial port
│   ├── web/
│   │   ├── api.py           # Flask REST API
│   │   └── static/          # Web UI files
│   └── main.py              # Entry point
├── tests/                   # Unit tests
├── config.json              # Configuration
├── requirements.txt         # Python dependencies
├── README.md               # This file
└── SPEC.md                 # Detailed specification
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/

# Run specific test file
pytest tests/test_rapi.py
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add/update tests
5. Submit a pull request

## Testing with OpenEVSE WiFi Firmware

To test the emulator with actual OpenEVSE WiFi firmware:

1. Start the emulator with TCP mode:

   ```json
   "serial": {
     "mode": "tcp",
     "tcp_port": 8023
   }
   ```

2. Configure your WiFi firmware to connect to `localhost:8023`

3. The WiFi firmware will communicate with the emulator as if it were real hardware

4. Use the Web UI to simulate EV connection, charging states, and errors

## Use Cases

- **WiFi Firmware Development**: Test without physical EVSE hardware
- **Protocol Testing**: Validate RAPI command handling and responses
- **Error Handling**: Test recovery from various fault conditions
- **UI Development**: Develop monitoring dashboards with live data
- **Integration Testing**: Test complete charging workflows
- **Load Testing**: Simulate multiple rapid state changes

## Troubleshooting

### Serial Port Not Available

**PTY mode**: Requires Unix-like OS (Linux/macOS). On Windows, use TCP mode:

```json
"serial": {"mode": "tcp", "tcp_port": 8023}
```

### Web UI Not Loading

- Check that port 8080 is not in use: `lsof -i :8080`
- Try a different port in `config.json`
- Check firewall settings

### Commands Not Responding

- Verify command format ends with `\r` (carriage return)
- Enable echo mode: `$SE 1\r`
- Check serial monitor in Web UI for command history
- Verify serial port connection

## Security Considerations

- **Network Binding**: By default, the web server binds to `0.0.0.0` (all
  interfaces) for easy access from other machines on your network. For
  localhost-only access, change `web.host` to `127.0.0.1` in `config.json`.
- **No Authentication**: The emulator does not include authentication. Do not
  expose it to untrusted networks.
- **Development Use**: This emulator is intended for development and testing purposes only.

## Documentation

- [SPEC.md](SPEC.md) - Detailed technical specification
- [.github/copilot-instructions.md](.github/copilot-instructions.md) - Development guidelines
- [OpenEVSE RAPI Documentation](https://github.com/OpenEVSE/open_evse/blob/master/firmware/open_evse/rapi_proc.h)
- [SAE J1772 Standard](https://en.wikipedia.org/wiki/SAE_J1772)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [OpenEVSE Project](https://github.com/OpenEVSE/open_evse) - For the original firmware and protocol specification
- SAE J1772 Working Group - For the charging standard

## Support

- **Issues**: Report bugs or request features via
  [GitHub Issues](https://github.com/jeremypoulter/OpenEVSE_Emulator/issues)
- **Discussions**: Ask questions in
  [GitHub Discussions](https://github.com/jeremypoulter/OpenEVSE_Emulator/discussions)

## Roadmap

- [ ] MQTT support for advanced WiFi firmware testing
- [ ] Multiple vehicle profiles (Nissan Leaf, Tesla, etc.)
- [ ] Load balancing simulation
- [ ] Docker container
- [ ] Data logging and replay
- [ ] Advanced J1772 pilot signal simulation
