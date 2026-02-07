"""
Virtual serial port implementation.

Provides PTY (pseudo-terminal) or TCP socket for serial communication.
"""

import os
import pty
import socket
import threading
import sys
import termios
import time
from typing import Optional, Callable


class VirtualSerialPort:
    """Virtual serial port using PTY or TCP socket."""

    def __init__(
        self,
        mode: str = "pty",
        tcp_port: int = 8023,
        pty_path: Optional[str] = None,
        reconnect_timeout_sec: int = 60,
        reconnect_backoff_ms: int = 1000,
    ):
        """
        Initialize virtual serial port.

        Args:
            mode: "pty" for pseudo-terminal or "tcp" for TCP socket
            tcp_port: Port number for TCP mode
            pty_path: Optional explicit PTY path (e.g. /tmp/rapi_pty_0).
                     If None, path is auto-generated. A symlink is created.
            reconnect_timeout_sec: Max seconds to retry connections (0=infinite)
            reconnect_backoff_ms: Initial backoff between retries in milliseconds

        Raises:
            ValueError: If reconnect_timeout_sec or reconnect_backoff_ms is negative
        """
        if reconnect_timeout_sec < 0:
            raise ValueError(
                f"reconnect_timeout_sec must be >= 0, got {reconnect_timeout_sec}"
            )
        if reconnect_backoff_ms < 0:
            raise ValueError(
                f"reconnect_backoff_ms must be >= 0, got {reconnect_backoff_ms}"
            )

        self.mode = mode
        self.tcp_port = tcp_port
        self.pty_path = pty_path
        self.reconnect_timeout_sec = reconnect_timeout_sec
        self.reconnect_backoff_ms = reconnect_backoff_ms

        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None
        self.slave_name: Optional[str] = None
        self.pty_symlink: Optional[str] = None  # Track symlink we created
        self.tcp_socket: Optional[socket.socket] = None
        self.client_socket: Optional[socket.socket] = None

        self.running = False
        self.read_thread: Optional[threading.Thread] = None
        self.data_callback: Optional[Callable[[str], str]] = None

    def start(self, data_callback: Callable[[str], str]) -> bool:
        """
        Start the virtual serial port.

        Args:
            data_callback: Function to call with received data, should return response

        Returns:
            True if started successfully, False otherwise
        """
        self.data_callback = data_callback

        if self.mode == "pty":
            return self._start_pty()
        elif self.mode == "tcp":
            return self._start_tcp()
        else:
            print(f"Unknown mode: {self.mode}")
            return False

    def _start_pty(self) -> bool:
        """Start PTY mode."""
        if sys.platform == "win32":
            print("PTY mode not supported on Windows. Use TCP mode instead.")
            return False

        try:
            self.master_fd, self.slave_fd = pty.openpty()
            self.slave_name = os.ttyname(self.slave_fd)

            # If explicit path requested, create a symlink
            if self.pty_path:
                # Remove existing symlink if present. Do not remove non-symlink files.
                if os.path.islink(self.pty_path):
                    try:
                        os.unlink(self.pty_path)
                    except Exception as e:
                        print(
                            f"Warning: Could not remove existing symlink "
                            f"{self.pty_path}: {e}"
                        )
                elif os.path.exists(self.pty_path):
                    # Existing non-symlink at requested path; refuse to overwrite.
                    print(
                        "Warning: Requested PTY path exists and is not a symlink, "
                        f"refusing to overwrite: {self.pty_path}"
                    )
                    print(f"Using auto-generated path instead: {self.slave_name}")
                    self.pty_path = None
                    self.pty_symlink = None

                if self.pty_path:
                    try:
                        os.symlink(self.slave_name, self.pty_path)
                        self.pty_symlink = self.pty_path
                        print(f"Created symlink: {self.pty_path} -> {self.slave_name}")
                    except Exception as e:
                        print(f"Warning: Could not create symlink {self.pty_path}: {e}")
                        print(f"Using auto-generated path instead: {self.slave_name}")
            # Configure PTY to raw mode to prevent \r -> \n translation
            # This ensures RAPI protocol line endings (\r) are preserved
            try:
                attrs = termios.tcgetattr(self.slave_fd)
                attrs[0] &= ~(
                    termios.ICRNL | termios.INLCR
                )  # No CR/NL translation on input
                attrs[1] &= ~(
                    termios.OCRNL | termios.ONLCR
                )  # No CR/NL translation on output
                attrs[3] &= ~(
                    termios.ECHO | termios.ICANON
                )  # No echo, no canonical mode
                termios.tcsetattr(self.slave_fd, termios.TCSANOW, attrs)
            except Exception as e:
                print(f"Warning: Could not set PTY to raw mode: {e}")

            display_path = self.pty_symlink if self.pty_symlink else self.slave_name
            print(f"Virtual serial port created: {display_path}")
            print(f"Connect using: screen {display_path} 115200")

            self.running = True
            self.read_thread = threading.Thread(target=self._pty_read_loop, daemon=True)
            self.read_thread.start()

            return True
        except Exception as e:
            print(f"Failed to create PTY: {e}")
            return False

    def _start_tcp(self) -> bool:
        """Start TCP socket mode."""
        try:
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_socket.bind(("0.0.0.0", self.tcp_port))
            self.tcp_socket.listen(1)

            print(f"Virtual serial port listening on TCP port {self.tcp_port}")
            print(f"Connect using: telnet localhost {self.tcp_port}")

            self.running = True
            self.read_thread = threading.Thread(
                target=self._tcp_accept_loop, daemon=True
            )
            self.read_thread.start()

            return True
        except Exception as e:
            print(f"Failed to create TCP socket: {e}")
            return False

    def _pty_read_loop(self):
        """Read loop for PTY mode."""
        buffer = ""

        while self.running and self.master_fd is not None:
            try:
                data = os.read(self.master_fd, 1024)
                if not data:
                    break

                # Decode and add to buffer
                # Use latin-1 to preserve all byte values 0-255 (including 0xFE for LCD spaces)
                text = data.decode("latin-1")
                buffer += text

                # Process complete commands (ending with \r or \n)
                while "\r" in buffer or "\n" in buffer:
                    # Find the first line ending
                    cr_pos = buffer.find("\r")
                    lf_pos = buffer.find("\n")

                    if cr_pos == -1:
                        end_pos = lf_pos
                    elif lf_pos == -1:
                        end_pos = cr_pos
                    else:
                        end_pos = min(cr_pos, lf_pos)

                    command = buffer[: end_pos + 1]
                    buffer = buffer[end_pos + 1 :]

                    # Process command
                    if self.data_callback and command.strip():
                        response = self.data_callback(command)
                        if response:
                            os.write(self.master_fd, response.encode("latin-1"))

            except Exception as e:
                if self.running:
                    print(f"PTY read error: {e}")
                break

    def _tcp_accept_loop(self):
        """Accept loop for TCP mode with reconnection support."""
        backoff = self.reconnect_backoff_ms / 1000.0
        max_backoff = 30.0  # Cap backoff at 30 seconds
        start_time = time.time()

        while self.running and self.tcp_socket:
            try:
                print("Waiting for client connection...")
                self.client_socket, addr = self.tcp_socket.accept()
                print(f"Client connected from {addr}")

                # Reset backoff on successful connection
                backoff = self.reconnect_backoff_ms / 1000.0
                start_time = time.time()

                self._tcp_client_loop()

                # Client disconnected, check if we should reconnect
                if self.running:
                    elapsed = time.time() - start_time
                    if (
                        self.reconnect_timeout_sec > 0
                        and elapsed > self.reconnect_timeout_sec
                    ):
                        print(f"Reconnection timeout after {elapsed:.1f}s, stopping")
                        break

                    print(f"Waiting {backoff:.1f}s before accepting new connection...")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)  # Exponential backoff

            except Exception as e:
                if self.running:
                    print(f"TCP accept error: {e}")
                    if self.reconnect_timeout_sec > 0:
                        elapsed = time.time() - start_time
                        if elapsed > self.reconnect_timeout_sec:
                            print(
                                f"Reconnection timeout after {elapsed:.1f}s, stopping"
                            )
                            break
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                else:
                    break

    def _tcp_client_loop(self):
        """Handle TCP client connection."""
        buffer = ""

        while self.running and self.client_socket:
            try:
                data = self.client_socket.recv(1024)
                if not data:
                    print("Client disconnected")
                    break

                # Decode and add to buffer
                # Use latin-1 to preserve all byte values 0-255 (including 0xFE for LCD spaces)
                text = data.decode("latin-1")
                buffer += text

                # Process complete commands (ending with \r or \n)
                while "\r" in buffer or "\n" in buffer:
                    # Find the first line ending
                    cr_pos = buffer.find("\r")
                    lf_pos = buffer.find("\n")

                    if cr_pos == -1:
                        end_pos = lf_pos
                    elif lf_pos == -1:
                        end_pos = cr_pos
                    else:
                        end_pos = min(cr_pos, lf_pos)

                    command = buffer[: end_pos + 1]
                    buffer = buffer[end_pos + 1 :]

                    # Process command
                    if self.data_callback and command.strip():
                        response = self.data_callback(command)
                        if response:
                            self.client_socket.send(response.encode("latin-1"))

            except Exception as e:
                if self.running:
                    print(f"TCP client error: {e}")
                break

        if self.client_socket:
            self.client_socket.close()
            self.client_socket = None

    def stop(self):
        """Stop the virtual serial port."""
        self.running = False

        if self.client_socket:
            self.client_socket.close()
            self.client_socket = None

        if self.tcp_socket:
            self.tcp_socket.close()
            self.tcp_socket = None

        if self.master_fd is not None:
            os.close(self.master_fd)
            self.master_fd = None

        if self.slave_fd is not None:
            os.close(self.slave_fd)
            self.slave_fd = None

        # Clean up symlink if we created one
        if self.pty_symlink and os.path.islink(self.pty_symlink):
            try:
                os.unlink(self.pty_symlink)
                print(f"Removed symlink: {self.pty_symlink}")
            except Exception as e:
                print(f"Warning: Could not remove symlink {self.pty_symlink}: {e}")
            self.pty_symlink = None

        if self.read_thread:
            self.read_thread.join(timeout=1.0)

    def get_port_info(self) -> str:
        """Get information about the serial port."""
        if self.mode == "pty" and self.slave_name:
            return f"PTY: {self.slave_name}"
        elif self.mode == "tcp":
            return f"TCP: localhost:{self.tcp_port}"
        return "Not started"

    def write(self, data: str):
        """
        Write data to the serial port (for async messages).

        Args:
            data: Data string to write
        """
        if not self.running:
            return

        try:
            data_bytes = data.encode("latin-1")

            if self.mode == "pty" and self.master_fd is not None:
                os.write(self.master_fd, data_bytes)
            elif self.mode == "tcp" and self.client_socket:
                self.client_socket.send(data_bytes)
        except Exception as e:
            print(f"Error writing to serial port: {e}")
