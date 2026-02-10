#!/usr/bin/env python3
"""
Generate GitHub Wiki documentation from OpenAPI specification.

This script converts the openapi.yaml file into Markdown format
suitable for GitHub Wiki pages.
"""

import yaml
import sys
from pathlib import Path
from typing import Dict, Any


def load_openapi_spec(spec_path: Path) -> Dict[str, Any]:
    """Load the OpenAPI specification from YAML file."""
    with open(spec_path, "r") as f:
        return yaml.safe_load(f)


def generate_home_page(spec: Dict[str, Any]) -> str:
    """Generate the Home.md wiki page."""
    info = spec.get("info", {})
    title = info.get("title", "API Documentation")
    description = info.get("description", "")
    version = info.get("version", "1.0.0")

    content = f"""# {title}

{description}

**Version:** {version}

## Quick Links

- [[API Reference]]
- [[Getting Started]]
- [[Authentication]]
- [[Examples]]

## Overview

This documentation describes the REST API for the OpenEVSE Emulator. The API
allows you to control and monitor the emulator programmatically.

## Base URL

```
{spec.get('servers', [{}])[0].get('url', 'http://localhost:8080')}
```

## API Endpoints

"""

    # Add endpoint summary by tag
    tags = spec.get("tags", [])
    for tag in tags:
        content += f"### {tag['name']}\n\n"
        content += f"{tag.get('description', '')}\n\n"

    return content


def generate_api_reference(spec: Dict[str, Any]) -> str:
    """Generate the API-Reference.md wiki page."""
    content = """# API Reference

Complete reference for all API endpoints.

## Table of Contents

"""

    # Build table of contents
    paths = spec.get("paths", {})
    for path in sorted(paths.keys()):
        path_item = paths[path]
        for method in ["get", "post", "put", "delete", "patch"]:
            if method in path_item:
                operation = path_item[method]
                summary = operation.get("summary", "")
                clean_path = path.replace("/", "-").replace("{", "").replace("}", "")
                anchor = f"{method.upper()}-{clean_path}"
                content += f"- [{method.upper()} {path}](#{anchor}) - {summary}\n"

    content += "\n---\n\n"

    # Generate detailed endpoint documentation
    for path in sorted(paths.keys()):
        path_item = paths[path]
        for method in ["get", "post", "put", "delete", "patch"]:
            if method in path_item:
                operation = path_item[method]
                content += generate_endpoint_doc(path, method, operation, spec)

    return content


def generate_endpoint_doc(
    path: str, method: str, operation: Dict[str, Any], spec: Dict[str, Any]
) -> str:
    """Generate documentation for a single endpoint."""
    summary = operation.get("summary", "")
    description = operation.get("description", "")
    tags = operation.get("tags", [])

    content = f"""## {method.upper()} {path}

**Summary:** {summary}

**Tags:** {', '.join(tags)}

"""

    if description:
        content += f"{description}\n\n"

    # Request body
    request_body = operation.get("requestBody")
    if request_body:
        content += "### Request Body\n\n"
        content += (
            f"**Required:** {'Yes' if request_body.get('required') else 'No'}\n\n"
        )

        content_types = request_body.get("content", {})
        for content_type, media_type in content_types.items():
            content += f"**Content-Type:** `{content_type}`\n\n"
            schema = media_type.get("schema", {})
            content += generate_schema_doc(schema, spec)

    # Responses
    responses = operation.get("responses", {})
    if responses:
        content += "### Responses\n\n"
        for status_code, response in responses.items():
            content += f"#### {status_code} - {response.get('description', '')}\n\n"
            response_content = response.get("content", {})
            for content_type, media_type in response_content.items():
                content += f"**Content-Type:** `{content_type}`\n\n"
                schema = media_type.get("schema", {})
                content += generate_schema_doc(schema, spec)

    content += "---\n\n"
    return content


def generate_schema_doc(
    schema: Dict[str, Any], spec: Dict[str, Any], indent: int = 0
) -> str:
    """Generate documentation for a schema."""
    content = ""
    indent_str = "  " * indent

    # Handle $ref
    if "$ref" in schema:
        ref_path = schema["$ref"].split("/")
        if ref_path[0] == "#" and len(ref_path) > 1:
            # Look up the reference in components/schemas
            components = spec.get("components", {})
            schemas = components.get("schemas", {})
            schema_name = ref_path[-1]
            if schema_name in schemas:
                content += f"{indent_str}**Schema:** `{schema_name}`\n\n"
                ref_schema = schemas[schema_name]
                return content + generate_schema_doc(ref_schema, spec, indent)

    schema_type = schema.get("type", "object")

    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        if properties:
            content += f"{indent_str}**Properties:**\n\n"
            for prop_name, prop_schema in properties.items():
                is_required = prop_name in required
                prop_type = prop_schema.get("type", "any")
                prop_format = prop_schema.get("format", "")
                prop_desc = prop_schema.get("description", "")
                prop_example = prop_schema.get("example", "")
                prop_enum = prop_schema.get("enum", [])

                req_marker = "**required**" if is_required else "optional"

                type_str = f"`{prop_type}`"
                if prop_format:
                    type_str = f"`{prop_type}` (format: `{prop_format}`)"

                content += f"{indent_str}- `{prop_name}` ({type_str}) - {req_marker}"
                if prop_desc:
                    content += f" - {prop_desc}"
                if prop_enum:
                    content += (
                        f" - Allowed values: {', '.join(f'`{v}`' for v in prop_enum)}"
                    )
                if prop_example:
                    content += f" - Example: `{prop_example}`"
                content += "\n"

        content += "\n"

    elif schema_type == "array":
        items = schema.get("items", {})
        content += f"{indent_str}**Type:** Array\n\n"
        content += f"{indent_str}**Items:**\n\n"
        content += generate_schema_doc(items, spec, indent + 1)

    return content


def generate_getting_started(spec: Dict[str, Any]) -> str:
    """Generate the Getting-Started.md wiki page."""
    base_url = spec.get("servers", [{}])[0].get("url", "http://localhost:8080")

    content = f"""# Getting Started

This guide will help you get started with the OpenEVSE Emulator API.

## Prerequisites

- OpenEVSE Emulator running (see main [README](https://github.com/jeremypoulter/OpenEVSE_Emulator))
- HTTP client (curl, Postman, or your preferred tool)

## Base URL

All API requests should be made to:

```
{base_url}
```

## Quick Example

Here's a simple example to get the current status:

```bash
curl {base_url}/api/status
```

## Common Workflows

### Starting a Charging Session

1. **Connect the EV:**
   ```bash
   curl -X POST {base_url}/api/ev/connect
   ```

2. **Request charging:**
   ```bash
   curl -X POST {base_url}/api/ev/request_charge
   ```

3. **Set charging current:**
   ```bash
   curl -X POST {base_url}/api/evse/current \\
     -H "Content-Type: application/json" \\
     -d '{{"amps": 16}}'
   ```

4. **Monitor status:**
   ```bash
   curl {base_url}/api/status
   ```

### Simulating an Error

```bash
curl -X POST {base_url}/api/errors/trigger \\
  -H "Content-Type: application/json" \\
  -d '{{"error": "gfci"}}'
```

### Clearing Errors

```bash
curl -X POST {base_url}/api/errors/clear
```

## WebSocket for Real-time Updates

Connect to `ws://{base_url.replace('http://', '')}/ws` for real-time status updates.

### JavaScript Example

```javascript
const ws = new WebSocket('ws://{base_url.replace('http://', '')}/ws');

ws.onmessage = (event) => {{
    const msg = JSON.parse(event.data);
    console.log('Message type:', msg.type);
    console.log('Data:', msg.data);
}};
```

## Next Steps

- Explore the [[API Reference]] for all available endpoints
- Check out more [[Examples]]
- View the [OpenAPI Specification]({base_url}/api/openapi.yaml)
"""

    return content


def generate_examples(spec: Dict[str, Any]) -> str:
    """Generate the Examples.md wiki page."""
    base_url = spec.get("servers", [{}])[0].get("url", "http://localhost:8080")

    content = f"""# API Examples

Collection of practical examples for using the OpenEVSE Emulator API.

## EVSE Control Examples

### Get EVSE Status

```bash
curl {base_url}/api/evse/status
```

### Enable/Disable Charging

```bash
# Enable charging
curl -X POST {base_url}/api/evse/enable

# Disable charging (sleep mode)
curl -X POST {base_url}/api/evse/disable
```

### Set Current Capacity

```bash
# Set to 16A
curl -X POST {base_url}/api/evse/current \\
  -H "Content-Type: application/json" \\
  -d '{{"amps": 16}}'

# Set to 32A
curl -X POST {base_url}/api/evse/current \\
  -H "Content-Type: application/json" \\
  -d '{{"amps": 32}}'
```

### Change Service Level

```bash
# Set to Level 2 (240V)
curl -X POST {base_url}/api/evse/service_level \\
  -H "Content-Type: application/json" \\
  -d '{{"level": "L2"}}'

# Set to Level 1 (120V)
curl -X POST {base_url}/api/evse/service_level \\
  -H "Content-Type: application/json" \\
  -d '{{"level": "L1"}}'
```

## EV Simulation Examples

### Connect and Disconnect EV

```bash
# Connect EV
curl -X POST {base_url}/api/ev/connect

# Disconnect EV
curl -X POST {base_url}/api/ev/disconnect
```

### Control Charging Request

```bash
# Start requesting charge
curl -X POST {base_url}/api/ev/request_charge

# Stop requesting charge
curl -X POST {base_url}/api/ev/stop_charge
```

### Set Battery State of Charge

```bash
# Set to 20%
curl -X POST {base_url}/api/ev/soc \\
  -H "Content-Type: application/json" \\
  -d '{{"soc": 20}}'

# Set to 80%
curl -X POST {base_url}/api/ev/soc \\
  -H "Content-Type: application/json" \\
  -d '{{"soc": 80}}'
```

### Set Maximum Charge Rate

```bash
# Set max rate to 32A
curl -X POST {base_url}/api/ev/max_rate \\
  -H "Content-Type: application/json" \\
  -d '{{"amps": 32}}'
```

## Error Simulation Examples

### Trigger Different Errors

```bash
# GFCI trip
curl -X POST {base_url}/api/errors/trigger \\
  -H "Content-Type: application/json" \\
  -d '{{"error": "gfci"}}'

# Stuck relay
curl -X POST {base_url}/api/errors/trigger \\
  -H "Content-Type: application/json" \\
  -d '{{"error": "stuck_relay"}}'

# No ground
curl -X POST {base_url}/api/errors/trigger \\
  -H "Content-Type: application/json" \\
  -d '{{"error": "no_ground"}}'

# Over temperature
curl -X POST {base_url}/api/errors/trigger \\
  -H "Content-Type: application/json" \\
  -d '{{"error": "over_temp"}}'
```

### Clear All Errors

```bash
curl -X POST {base_url}/api/errors/clear
```

### Get Error Status

```bash
curl {base_url}/api/errors/status
```

## Python Examples

### Using requests library

```python
import requests

base_url = "{base_url}"

# Get combined status
response = requests.get(f"{{base_url}}/api/status")
status = response.json()
print(f"EVSE State: {{status['evse']['state_name']}}")
print(f"Current Capacity: {{status['evse']['current_capacity']}}A")
print(f"EV Connected: {{status['ev']['connected']}}")
print(f"Battery SoC: {{status['ev']['soc']}}%")

# Connect EV and start charging
requests.post(f"{{base_url}}/api/ev/connect")
requests.post(f"{{base_url}}/api/ev/request_charge")
requests.post(f"{{base_url}}/api/evse/current",
              json={{"amps": 16}})

# Monitor charging
status = requests.get(f"{{base_url}}/api/status").json()
print(f"Charging at {{status['evse']['actual_current']}}A")
```

## JavaScript Examples

### Using fetch API

```javascript
const baseUrl = '{base_url}';

// Get status
async function getStatus() {{
    const response = await fetch(`${{baseUrl}}/api/status`);
    const status = await response.json();
    console.log('EVSE State:', status.evse.state_name);
    console.log('Battery SoC:', status.ev.soc);
}}

// Start charging session
async function startCharging() {{
    await fetch(`${{baseUrl}}/api/ev/connect`, {{ method: 'POST' }});
    await fetch(`${{baseUrl}}/api/ev/request_charge`, {{ method: 'POST' }});
    await fetch(`${{baseUrl}}/api/evse/current`, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ amps: 16 }})
    }});
}}

// WebSocket for real-time updates
const ws = new WebSocket('ws://{base_url.replace('http://', '')}/ws');
ws.onmessage = (event) => {{
    const msg = JSON.parse(event.data);
    if (msg.type === 'status_update') {{
        console.log('Status update:', msg.data);
    }} else if (msg.type === 'error') {{
        console.error('Error:', msg.data);
    }}
}};
```

## Complete Charging Workflow

```bash
#!/bin/bash

BASE_URL="{base_url}"

echo "1. Connecting EV..."
curl -X POST $BASE_URL/api/ev/connect

echo "2. Setting battery to 20%..."
curl -X POST $BASE_URL/api/ev/soc \\
  -H "Content-Type: application/json" \\
  -d '{{"soc": 20}}'

echo "3. Requesting charge..."
curl -X POST $BASE_URL/api/ev/request_charge

echo "4. Setting current to 16A..."
curl -X POST $BASE_URL/api/evse/current \\
  -H "Content-Type: application/json" \\
  -d '{{"amps": 16}}'

echo "5. Getting status..."
curl $BASE_URL/api/status | python -m json.tool

echo "Charging session started!"
```
"""

    return content


def generate_authentication(spec: Dict[str, Any]) -> str:
    """Generate the Authentication.md wiki page."""
    content = """# Authentication

Currently, the OpenEVSE Emulator API does not require authentication. This is
because it's designed to run locally for development and testing purposes.

## Security Considerations

When deploying the emulator:

1. **Network Isolation**: Run the emulator on a private network or localhost only
2. **Firewall Rules**: Use firewall rules to restrict access to trusted IPs
3. **Reverse Proxy**: Consider using a reverse proxy (nginx, Apache) with
   authentication if you need to expose the API
4. **HTTPS**: Use HTTPS in production environments

## Future Authentication

Future versions may support:
- API key authentication
- OAuth 2.0
- JWT tokens

For now, the API is designed for local development use where authentication
is not required.
"""

    return content


def main():
    """Main entry point."""
    # Locate the openapi.yaml file
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    spec_path = repo_root / "openapi.yaml"

    if not spec_path.exists():
        print(f"Error: OpenAPI spec not found at {spec_path}", file=sys.stderr)
        sys.exit(1)

    # Load the spec
    print(f"Loading OpenAPI spec from {spec_path}")
    spec = load_openapi_spec(spec_path)

    # Create output directory
    output_dir = repo_root / "wiki"
    output_dir.mkdir(exist_ok=True)

    # Generate wiki pages
    pages = {
        "Home.md": generate_home_page(spec),
        "API-Reference.md": generate_api_reference(spec),
        "Getting-Started.md": generate_getting_started(spec),
        "Examples.md": generate_examples(spec),
        "Authentication.md": generate_authentication(spec),
    }

    for filename, content in pages.items():
        output_path = output_dir / filename
        print(f"Generating {output_path}")
        with open(output_path, "w") as f:
            f.write(content)

    print(f"\n✓ Successfully generated {len(pages)} wiki pages in {output_dir}")
    print("\nGenerated pages:")
    for filename in pages.keys():
        print(f"  - {filename}")


if __name__ == "__main__":
    main()
