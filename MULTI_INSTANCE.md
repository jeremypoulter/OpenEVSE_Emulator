# Multi-Instance Support

This guide explains how to run multiple paired instances of the OpenEVSE
emulator and native firmware for testing purposes.

## Overview

The emulator and native firmware now support explicit configuration of serial
port paths, allowing multiple instances to run simultaneously without conflicts.
This is useful for:

- Testing multiple charging stations in parallel
- Load sharing development and testing
- Integration testing with different configurations
- Docker/container deployments

## Configuration Priority

Settings are applied in this order (later overrides earlier):

1. **config.json** - Default configuration file
2. **Environment variables** - Override config.json
3. **Command-line arguments** - Override everything

## Emulator Configuration

### New Configuration Options

```json
{
  "serial": {
    "mode": "pty",
    "tcp_port": 8023,
    "pty_path": null,
    "reconnect_timeout_sec": 60,
    "reconnect_backoff_ms": 1000
  }
}
```

- **pty_path**: Explicit PTY path (e.g., `/tmp/rapi_pty_0`). If `null`, a path is auto-generated.
- **reconnect_timeout_sec**: Maximum seconds to retry connections (0 = infinite retry)
- **reconnect_backoff_ms**: Initial backoff between connection retries in milliseconds (doubles on each retry)

### Emulator Command-Line Arguments

```bash
# Specify explicit PTY path
python src/main.py --serial-pty-path /tmp/rapi_pty_0

# Override ports
python src/main.py --serial-tcp-port 8024 --web-port 8081

# Configure reconnection behavior
python src/main.py --serial-reconnect-timeout 120 --serial-reconnect-backoff 2000
```

### Emulator Environment Variables

```bash
# Serial configuration
export SERIAL_MODE=pty
export SERIAL_PTY_PATH=/tmp/rapi_pty_0
export SERIAL_TCP_PORT=8023
export SERIAL_RECONNECT_TIMEOUT=60
export SERIAL_RECONNECT_BACKOFF=1000

# Web UI configuration
export WEB_HOST=0.0.0.0
export WEB_PORT=8080

python src/main.py
```

## Native Firmware Configuration

### Firmware Environment Variable

The native (EPOXY_DUINO) build now checks the `RAPI_SERIAL_PORT` environment variable:

```bash
# Use custom PTY path
export RAPI_SERIAL_PORT=/tmp/rapi_pty_0
.pio/build/native/program
```

### Firmware Command-Line Arguments

```bash
# Override RAPI serial path via CLI (takes precedence over environment variable)
.pio/build/native/program --rapi-serial /tmp/rapi_pty_0

# Set HTTP port for web interface (default: 8000)
.pio/build/native/program --set-config www_http_port=8000

# Combine multiple options for multi-instance setup
.pio/build/native/program --rapi-serial /tmp/rapi_pty_0 --set-config www_http_port=8001
```

**Note:** The `--set-config` option allows you to override any configuration value at runtime. This is essential for
running multiple native instances, as each needs a unique HTTP port.

### Default Behavior

If neither environment variable nor CLI argument is provided:

- RAPI serial path defaults to `/tmp/rapi_pty`
- HTTP port defaults to `8000`

## Multi-Instance Examples

### Example 1: Two Paired Instances (PTY Mode)

**Terminal 1 - First Emulator:**

```bash
cd OpenEVSE_Emulator
python src/main.py --serial-pty-path /tmp/rapi_pty_0 --web-port 8080
```

**Terminal 2 - First Native:**

```bash
cd ESP32_WiFi_V3.x
RAPI_SERIAL_PORT=/tmp/rapi_pty_0 .pio/build/native/program --set-config www_http_port=8000
```

**Terminal 3 - Second Emulator:**

```bash
cd OpenEVSE_Emulator
python src/main.py --serial-pty-path /tmp/rapi_pty_1 --web-port 8081
```

**Terminal 4 - Second Native:**

```bash
cd ESP32_WiFi_V3.x
RAPI_SERIAL_PORT=/tmp/rapi_pty_1 .pio/build/native/program --set-config www_http_port=8001
```

### Example 2: Using Environment Variables

**Terminal 1 - Instance 0 Emulator:**

```bash
cd OpenEVSE_Emulator
export SERIAL_PTY_PATH=/tmp/rapi_pty_0
export WEB_PORT=8080
python src/main.py
```

**Terminal 2 - Instance 0 Native:**

```bash
cd ESP32_WiFi_V3.x
export RAPI_SERIAL_PORT=/tmp/rapi_pty_0
.pio/build/native/program --set-config www_http_port=8000
```

**Terminal 3 - Instance 1 Emulator:**

```bash
cd OpenEVSE_Emulator
export SERIAL_PTY_PATH=/tmp/rapi_pty_1
export WEB_PORT=8081
python src/main.py
```

**Terminal 4 - Instance 1 Native:**

```bash
cd ESP32_WiFi_V3.x
export RAPI_SERIAL_PORT=/tmp/rapi_pty_1
.pio/build/native/program --set-config www_http_port=8001
```

### Example 3: Docker Compose

```yaml
version: '3.8'

services:
  emulator_0:
    build: ./OpenEVSE_Emulator
    environment:
      - SERIAL_PTY_PATH=/tmp/rapi_pty_0
      - WEB_PORT=8080
    ports:
      - "8080:8080"
    volumes:
      - /tmp:/tmp

  native_0:
    build: ./ESP32_WiFi_V3.x
    command: --set-config www_http_port=8000
    environment:
      - RAPI_SERIAL_PORT=/tmp/rapi_pty_0
    ports:
      - "8000:8000"
    volumes:
      - /tmp:/tmp
    depends_on:
      - emulator_0

  emulator_1:
    build: ./OpenEVSE_Emulator
    environment:
      - SERIAL_PTY_PATH=/tmp/rapi_pty_1
      - WEB_PORT=8081
    ports:
      - "8081:8081"
    volumes:
      - /tmp:/tmp

  native_1:
    build: ./ESP32_WiFi_V3.x
    command: --set-config www_http_port=8001
    environment:
      - RAPI_SERIAL_PORT=/tmp/rapi_pty_1
    ports:
      - "8001:8001"
    volumes:
      - /tmp:/tmp
    depends_on:
      - emulator_1
```

**Note:** Each native instance requires a unique HTTP port via `--set-config www_http_port=XXXX` to avoid port
conflicts.

### Example 4: TCP Mode (No PTY Required)

**Terminal 1 - Emulator on TCP:**

```bash
cd OpenEVSE_Emulator
python src/main.py --serial-mode tcp --serial-tcp-port 8023 --web-port 8080
```

**Terminal 2 - Connect via telnet (for testing):**

```bash
telnet localhost 8023
```

## Reconnection Behavior

Both the emulator and native firmware now handle disconnections gracefully:

- **Emulator**: Automatically accepts new connections after a client disconnects
- **Backoff**: Uses exponential backoff (1s → 2s → 4s → ... up to 30s max)
- **Timeout**: Stops retrying after `reconnect_timeout_sec` (0 = infinite)
- **Reboot testing**: Either side can be restarted independently; the other will wait and reconnect

### Testing Reconnection

1. Start emulator and native in any order
2. Kill the native process (Ctrl+C)
3. Observe emulator logging reconnection attempts
4. Restart native - connection resumes automatically

## Troubleshooting

### PTY Path Already in Use

**Symptom**: `Warning: Could not create symlink /tmp/rapi_pty_0: File exists`

**Solution**: The emulator automatically removes stale symlinks. If you see
this warning but the emulator starts successfully, everything is working. If it
fails, manually remove the symlink:

```bash
rm /tmp/rapi_pty_0
```

### Connection Timeout

**Symptom**: Emulator logs "Reconnection timeout after 60.0s, stopping"

**Solution**: Increase the timeout or set to 0 for infinite retries:

```bash
python src/main.py --serial-reconnect-timeout 0
```

### Port Already in Use (Web UI)

**Symptom**: `OSError: [Errno 98] Address already in use`

**Solution**: Each emulator instance needs a unique web port:

```bash
python src/main.py --web-port 8081
```

### Port Already in Use (Native HTTP)

**Symptom**: Native firmware fails to start HTTP server or shows port binding error

**Solution**: Each native instance needs a unique HTTP port (default is 8000):

```bash
.pio/build/native/program --set-config www_http_port=8001
```

### PTY Not Found (Native)

**Symptom**: Native build exits with PTY open error

**Solution**: Ensure the emulator is started first (it creates the PTY), or
increase reconnection retries in the emulator configuration.

## Backward Compatibility

All existing configurations continue to work unchanged:

- **No CLI args**: Uses auto-generated PTY device paths (no `/tmp/rapi_pty` symlink unless configured)
- **Existing config.json**: New fields are optional; defaults are applied automatically
- **Single instance**: Works exactly as before without any changes

## Technical Details

### PTY Path Handling

When you specify `--serial-pty-path /tmp/rapi_pty_0`:

1. Emulator creates a pseudo-terminal (e.g., `/dev/pts/4`)
2. Emulator creates a symlink: `/tmp/rapi_pty_0 -> /dev/pts/4`
3. Native firmware opens `/tmp/rapi_pty_0`
4. Communication flows through the PTY

The symlink is automatically removed when the emulator exits cleanly.

### TCP Mode

TCP mode provides similar functionality but uses network sockets instead of PTYs:

- Emulator listens on `tcp_port` (default 8023)
- Clients connect via TCP socket
- No PTY creation or symlinks required
- Better suited for Docker and network-based testing

## See Also

- [README.md](README.md) - General emulator documentation
- [SPEC.md](SPEC.md) - Technical specification
- [config.json](config.json) - Default configuration file
