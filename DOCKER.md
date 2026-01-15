# Docker and Development Container Guide

This guide covers running the OpenEVSE Emulator using Docker and VSCode Devcontainers.

## Docker Deployment

### Quick Start

Build and run with a single command:

```bash
docker build -t openevse-emulator .
docker run -p 8080:8080 -p 8023:8023 openevse-emulator
```

Access the emulator at http://localhost:8080

### Using Docker Compose

The easiest way to run the emulator:

```bash
# Start the emulator
docker-compose up

# Start in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the emulator
docker-compose down
```

### Custom Configuration

Mount a custom configuration file:

```bash
docker run -p 8080:8080 -p 8023:8023 \
  -v $(pwd)/my-config.json:/app/config.json:ro \
  openevse-emulator
```

### Environment Variables

You can override configuration using environment variables:

```bash
docker run -p 8080:8080 -p 8023:8023 \
  -e PYTHONUNBUFFERED=1 \
  openevse-emulator
```

### Networking

The emulator exposes two ports:

- **8080**: Web UI and REST API
- **8023**: TCP serial port (for RAPI protocol when using TCP mode)

To use the TCP serial port, ensure your `config.json` has:

```json
{
  "serial": {
    "mode": "tcp",
    "tcp_port": 8023
  }
}
```

Note: PTY mode will not work in Docker; use TCP mode instead.

### Health Checks

The Docker Compose configuration includes a health check that polls the `/api/status` endpoint every 30 seconds.

## VSCode Devcontainer

### Prerequisites

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop)
2. Install [Visual Studio Code](https://code.visualstudio.com/)
3. Install the [Remote - Containers][remote-containers] extension

[remote-containers]: https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers

### Getting Started

1. Open the OpenEVSE_Emulator folder in VSCode
2. Press `F1` and select "Remote-Containers: Reopen in Container"
3. Wait for the container to build (first time only)
4. The development environment is ready!

### What's Included

The devcontainer provides:

- **Python 3.11** with all dependencies pre-installed
- **VSCode Extensions**:
  - Python language support
  - Pylance for type checking
  - Black formatter
  - Flake8 linter
  - YAML support
  - OpenAPI tools
- **Port Forwarding**: Automatic forwarding of ports 8080 and 8023
- **Development Tools**: pytest, pytest-cov, black, flake8

### Running the Emulator

Inside the devcontainer terminal:

```bash
# Run the emulator
python src/main.py

# Run tests
pytest

# Format code
black src/ tests/

# Lint code
flake8 src/ tests/
```

### Customization

Edit `.devcontainer/devcontainer.json` to:

- Add more VSCode extensions
- Change Python settings
- Add additional port forwards
- Modify the post-create commands

### Debugging

The devcontainer is configured for Python debugging:

1. Set breakpoints in your code
2. Press `F5` to start debugging
3. Use the debug console to inspect variables

## Docker Best Practices

### Multi-Stage Builds

For production, consider using a multi-stage build to reduce image size:

```dockerfile
FROM python:3.11-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY src/ ./src/
COPY config.json .
COPY openapi.yaml .
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
EXPOSE 8080 8023
CMD ["python", "src/main.py"]
```

### Security

- The container runs as root by default. For production, create a non-root user:

  ```dockerfile
  RUN useradd -m -u 1000 emulator
  USER emulator
  ```

- Keep the base image updated: `docker pull python:3.11-slim`
- Scan for vulnerabilities: `docker scan openevse-emulator`

### Resource Limits

Limit container resources using Docker Compose:

```yaml
services:
  openevse-emulator:
    # ... other config
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 256M
```

## Troubleshooting

### Container Won't Start

Check logs:

```bash
docker logs openevse-emulator
```

### Port Already in Use

Change the host port:

```bash
docker run -p 8081:8080 -p 8024:8023 openevse-emulator
```

### Permission Denied (PTY Mode)

PTY mode requires host access. Use TCP mode in Docker:

```json
{
  "serial": {
    "mode": "tcp"
  }
}
```

### Can't Connect to Serial Port

Ensure port 8023 is exposed and TCP mode is configured in `config.json`.

## CI/CD Integration

### GitHub Actions

Example workflow:

```yaml
name: Docker Build

on: [push]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Build Docker image
        run: docker build -t openevse-emulator .
      - name: Test container
        run: |
          docker run -d -p 8080:8080 --name test openevse-emulator
          sleep 5
          curl http://localhost:8080/api/status
          docker stop test
```

### Docker Hub

Push to Docker Hub:

```bash
docker tag openevse-emulator username/openevse-emulator:latest
docker push username/openevse-emulator:latest
```

## Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [VSCode Remote Containers](https://code.visualstudio.com/docs/remote/containers)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
