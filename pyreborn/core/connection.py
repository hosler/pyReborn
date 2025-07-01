"""
TCP connection management for PyReborn.
Handles low-level socket operations.
"""

import socket
import threading
import struct
from typing import Optional, Callable, Tuple
from queue import Queue, Empty
import time

class Connection:
    """Manages TCP socket connection"""
    
    def __init__(self):
        self.socket: Optional[socket.socket] = None
        self.host: str = ""
        self.port: int = 0
        self.connected: bool = False
        self.running: bool = False
        
        # Callbacks
        self.on_connected: Optional[Callable[[], None]] = None
        self.on_disconnected: Optional[Callable[[], None]] = None
        self.on_data_received: Optional[Callable[[bytes], None]] = None
        
        # Threading
        self._recv_thread: Optional[threading.Thread] = None
        self._recv_buffer = bytearray()
        
    def connect(self, host: str, port: int, timeout: float = 10.0) -> bool:
        """Connect to server"""
        self.host = host
        self.port = port
        
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(timeout)
            self.socket.connect((host, port))
            self.socket.settimeout(None)  # Set to blocking mode
            self.connected = True
            self.running = True
            
            # Start receive thread
            self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self._recv_thread.start()
            
            if self.on_connected:
                self.on_connected()
                
            return True
            
        except (socket.timeout, socket.error) as e:
            print(f"Connection failed: {e}")
            return False
            
    def disconnect(self):
        """Disconnect from server"""
        self.running = False
        
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except:
                pass
            
        self.socket = None
        self.connected = False
        
        if self.on_disconnected:
            self.on_disconnected()
            
    def send(self, data: bytes) -> bool:
        """Send raw data"""
        if not self.connected or not self.socket:
            return False
            
        try:
            self.socket.sendall(data)
            return True
        except socket.error as e:
            print(f"Send error: {e}")
            self.disconnect()
            return False
            
    def _receive_loop(self):
        """Receive data from socket"""
        while self.running and self.connected:
            try:
                data = self.socket.recv(65536)
                if not data:
                    print("Connection closed by server")
                    break
                    
                if self.on_data_received:
                    self.on_data_received(data)
                    
            except socket.timeout:
                continue
            except socket.error as e:
                print(f"Receive error: {e}")
                break
                
        self.disconnect()