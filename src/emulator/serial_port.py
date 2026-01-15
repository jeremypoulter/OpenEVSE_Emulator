"""
Virtual serial port implementation.

Provides PTY (pseudo-terminal) or TCP socket for serial communication.
"""

import os
import pty
import socket
import threading
import sys
from typing import Optional, Callable


class VirtualSerialPort:
    """Virtual serial port using PTY or TCP socket."""
    
    def __init__(self, mode: str = "pty", tcp_port: int = 8023):
        """
        Initialize virtual serial port.
        
        Args:
            mode: "pty" for pseudo-terminal or "tcp" for TCP socket
            tcp_port: Port number for TCP mode
        """
        self.mode = mode
        self.tcp_port = tcp_port
        
        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None
        self.slave_name: Optional[str] = None
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
            
            print(f"Virtual serial port created: {self.slave_name}")
            print(f"Connect using: screen {self.slave_name} 115200")
            
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
            self.tcp_socket.bind(('0.0.0.0', self.tcp_port))
            self.tcp_socket.listen(1)
            
            print(f"Virtual serial port listening on TCP port {self.tcp_port}")
            print(f"Connect using: telnet localhost {self.tcp_port}")
            
            self.running = True
            self.read_thread = threading.Thread(target=self._tcp_accept_loop, daemon=True)
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
                text = data.decode('utf-8', errors='ignore')
                buffer += text
                
                # Process complete commands (ending with \r or \n)
                while '\r' in buffer or '\n' in buffer:
                    # Find the first line ending
                    cr_pos = buffer.find('\r')
                    lf_pos = buffer.find('\n')
                    
                    if cr_pos == -1:
                        end_pos = lf_pos
                    elif lf_pos == -1:
                        end_pos = cr_pos
                    else:
                        end_pos = min(cr_pos, lf_pos)
                    
                    command = buffer[:end_pos + 1]
                    buffer = buffer[end_pos + 1:]
                    
                    # Process command
                    if self.data_callback and command.strip():
                        response = self.data_callback(command)
                        if response:
                            os.write(self.master_fd, response.encode('utf-8'))
                
            except Exception as e:
                if self.running:
                    print(f"PTY read error: {e}")
                break
    
    def _tcp_accept_loop(self):
        """Accept loop for TCP mode."""
        while self.running and self.tcp_socket:
            try:
                print("Waiting for client connection...")
                self.client_socket, addr = self.tcp_socket.accept()
                print(f"Client connected from {addr}")
                
                self._tcp_client_loop()
                
            except Exception as e:
                if self.running:
                    print(f"TCP accept error: {e}")
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
                text = data.decode('utf-8', errors='ignore')
                buffer += text
                
                # Process complete commands (ending with \r or \n)
                while '\r' in buffer or '\n' in buffer:
                    # Find the first line ending
                    cr_pos = buffer.find('\r')
                    lf_pos = buffer.find('\n')
                    
                    if cr_pos == -1:
                        end_pos = lf_pos
                    elif lf_pos == -1:
                        end_pos = cr_pos
                    else:
                        end_pos = min(cr_pos, lf_pos)
                    
                    command = buffer[:end_pos + 1]
                    buffer = buffer[end_pos + 1:]
                    
                    # Process command
                    if self.data_callback and command.strip():
                        response = self.data_callback(command)
                        if response:
                            self.client_socket.send(response.encode('utf-8'))
                
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
        
        if self.read_thread:
            self.read_thread.join(timeout=1.0)
    
    def get_port_info(self) -> str:
        """Get information about the serial port."""
        if self.mode == "pty" and self.slave_name:
            return f"PTY: {self.slave_name}"
        elif self.mode == "tcp":
            return f"TCP: localhost:{self.tcp_port}"
        return "Not started"
