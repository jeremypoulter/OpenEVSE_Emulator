"""Remember what a RAPI client was last told.

The WiFi firmware (or any other client on the serial port) polls the EVSE
constantly -- $GS for the state, $GG for current and voltage, and so on. When
something looks wrong on the client the useful question is "what did it last
see?", which is not what the emulator's own state says: the two can differ for
as long as it takes the next poll to land, or for good if a reply was lost.

This keeps the latest request and reply for each command, decoded into named
fields for the common ones, and works the same whether the replies come from
the Python EVSE or from the real firmware in engine mode.
"""

import re
import threading
import time
from typing import Callable, Optional

# Field names for the replies clients actually poll. Anything not listed is
# still recorded, just as positional args.
_FIELDS = {
    # command: (name, base) per positional reply field; base 16 for hex fields
    "GS": [("state", 16), ("elapsed_sec", 10), ("pilot_state", 16), ("vflags", 16)],
    "GG": [("current_ma", 10), ("voltage_mv", 10)],
    "GE": [("current_amps", 10), ("flags", 16)],
    "GC": [("min_amps", 10), ("max_amps", 10), ("pilot_amps", 10), ("max_config", 10)],
    "GF": [("gfi_trips", 16), ("no_ground_trips", 16), ("stuck_relay_trips", 16)],
    "GP": [("temp_ds", 10), ("temp_mcp", 10), ("temp_tmp007", 10)],
    "GA": [("current_scale", 10), ("current_offset", 10)],
    "GV": [("firmware_version", None), ("protocol_version", None)],
    "GI": [("mcu_id", None)],
    # async notifications from the EVSE
    "AT": [
        ("state", 16),
        ("pilot_state", 16),
        ("current_capacity", 10),
        ("vflags", 16),
    ],
    "AB": [("post_code", 16), ("firmware_version", None)],
}

# Where a command sits in the protocol, by its first letter
_KINDS = {"G": "query", "S": "set", "F": "function", "A": "async", "T": "test"}

_CHECKSUM = re.compile(r"[\^*]")
_SEQUENCE_ID = re.compile(r"\s*:[0-9A-Fa-f]+$")


def _body(line: str) -> str:
    """A RAPI line without its checksum or sequence id, which may follow the
    last argument after a space or directly against it."""
    text = _CHECKSUM.split(line.strip())[0]
    return " ".join(_SEQUENCE_ID.sub("", text).split())


def _decode(command: str, args: list) -> dict:
    """Name the fields of a reply, where we know them."""
    fields = {}
    for (name, base), raw in zip(_FIELDS.get(command, []), args):
        if base is None:
            fields[name] = raw
            continue
        try:
            fields[name] = int(raw, base)
        except ValueError:
            fields[name] = raw
    return fields


class RapiMonitor:
    """The last request and reply seen for each RAPI command."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._last: dict = {}
        # Called with each recorded entry, after the lock is released, so the
        # web layer can stream traffic without this module knowing about it.
        self.on_record: Optional[Callable[[dict], None]] = None

    def record_exchange(self, request: str, response: str) -> None:
        """A client sent a command and was answered."""
        text = _body(request)
        if not text.startswith("$"):
            return
        command = text[1:3]
        status, *args = _body(response).split() or [""]
        entry = {
            "command": command,
            "kind": _KINDS.get(command[:1], "other"),
            "request": text,
            "response": response.strip(),
            "ok": status == "$OK",
            "args": args,
            "fields": _decode(command, args) if status == "$OK" else {},
        }
        self._store(command, entry)

    def record_async(self, message: str) -> None:
        """The EVSE volunteered a notification ($AT, $AB, ...)."""
        text = _body(message)
        if not text.startswith("$"):
            return
        command = text[1:3]
        args = text.split()[1:]
        self._store(
            command,
            {
                "command": command,
                "kind": "async",
                "request": None,
                "response": message.strip(),
                "ok": True,
                "args": args,
                "fields": _decode(command, args),
            },
        )

    def _store(self, command: str, entry: dict) -> None:
        now = self._clock()
        with self._lock:
            previous = self._last.get(command)
            entry["count"] = (previous["count"] if previous else 0) + 1
            entry["time"] = now
            self._last[command] = entry
        callback = self.on_record
        if callback:
            callback(dict(entry))

    def snapshot(self) -> list:
        """Everything seen so far, by command, each with how long ago it was."""
        now = self._clock()
        with self._lock:
            entries = [dict(e) for e in self._last.values()]
        for entry in entries:
            entry["age_sec"] = round(max(0.0, now - entry["time"]), 1)
        return sorted(entries, key=lambda e: (e["kind"] == "async", e["command"]))

    def clear(self) -> None:
        with self._lock:
            self._last.clear()
