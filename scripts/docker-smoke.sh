#!/usr/bin/env bash
# Prove engine mode works in a built image: both firmware binaries are present,
# and the emulator started with ENGINE_ENABLED serves the firmware's own
# version over the web API rather than the Python model's.
#
#   scripts/docker-smoke.sh [image]
set -euo pipefail

image="${1:-openevse-emulator:latest}"
name="oe-smoke-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT

for board in oev6 nxt; do
    docker run --rm --entrypoint test "$image" -x "/opt/openevse/native_$board" \
        || { echo "FAIL: /opt/openevse/native_$board missing from $image" >&2; exit 1; }
done

for board in oev6 nxt; do
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --name "$name" -p 18080:8080 \
        -e ENGINE_ENABLED=true -e ENGINE_BOARD="$board" -e SERIAL_MODE=tcp \
        "$image" >/dev/null

    version=""
    for _ in $(seq 1 30); do
        version="$(curl -fsS http://localhost:18080/api/evse/version 2>/dev/null || true)"
        [ -n "$version" ] && break
        sleep 1
    done

    # The firmware's version carries a ".native" suffix; the Python model's
    # default is 8.2.3.
    case "$version" in
        *'.native'*) echo "ok ($board): $version" ;;
        *)
            echo "FAIL ($board): engine mode did not come up; version='$version'" >&2
            docker logs "$name" >&2
            exit 1
            ;;
    esac
done
