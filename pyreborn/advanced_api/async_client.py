#!/usr/bin/env python3
"""
Async/Await Support for PyReborn
=================================

Provides async/await wrappers around the synchronous PyReborn client for use
in modern Python applications using asyncio.

This wrapper runs the synchronous client operations in a thread pool to avoid
blocking the asyncio event loop while maintaining compatibility with the
existing codebase.
"""

import asyncio
import logging
import functools
from typing import Optional, Dict, Any, List, Callable, Awaitable
from concurrent.futures import ThreadPoolExecutor
import threading

from ..client import Client as SyncClient
from ..models import Player, Level
from ..protocol.enums import Direction, PlayerProp

logger = logging.getLogger(__name__)


class AsyncClient:
    """
    Async wrapper around the synchronous PyReborn client.
    
    Provides async/await interface for all client operations while running
    the synchronous client in a background thread to avoid blocking the
    asyncio event loop.
    
    Usage:
        async def main():
            client = AsyncClient("localhost", 14900)
            await client.connect()
            await client.login("username", "password")
            
            player = await client.get_player()
            print(f"Player: {player.account}")
            
            await client.move(1, 0)
            await client.say("Hello async world!")
            
            await client.disconnect()
    """
    
    def __init__(self, host: str = "localhost", port: int = 14900, version: str = "6.037", 
                 max_workers: int = 4):
        """
        Initialize async client.
        
        Args:
            host: Server hostname or IP address
            port: Server port number
            version: Protocol version to use
            max_workers: Maximum number of worker threads for async operations
        """
        self.host = host
        self.port = port
        self.version = version
        
        # Create synchronous client
        self._sync_client = SyncClient(host, port, version)
        
        # Thread pool for running sync operations
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pyreborn-async")
        
        # Connection state
        self._connected = False
        self._logged_in = False
        
        # Event loop for callbacks
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        logger.info(f"AsyncClient initialized for {host}:{port}")
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with automatic disconnection"""
        await self.disconnect()
        return False  # Don't suppress exceptions
    
    def _run_in_thread(self, func: Callable, *args, **kwargs) -> Awaitable:
        """
        Run a synchronous function in the thread pool.
        
        Args:
            func: Function to run
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Awaitable that resolves to the function result
        """
        if not self._loop:
            self._loop = asyncio.get_event_loop()
        
        return self._loop.run_in_executor(
            self._executor,
            functools.partial(func, *args, **kwargs)
        )
    
    async def connect(self) -> bool:
        """
        Connect to the server asynchronously.
        
        Returns:
            True if connected successfully, False otherwise
        """
        result = await self._run_in_thread(self._sync_client.connect)
        self._connected = result
        if result:
            logger.info(f"Async connected to {self.host}:{self.port}")
        return result
    
    async def login(self, username: str, password: str) -> bool:
        """
        Login to the server asynchronously.
        
        Args:
            username: Account username
            password: Account password
            
        Returns:
            True if logged in successfully, False otherwise
        """
        result = await self._run_in_thread(self._sync_client.login, username, password)
        self._logged_in = result
        if result:
            logger.info(f"Async logged in as {username}")
        return result
    
    async def disconnect(self) -> None:
        """Disconnect from the server asynchronously."""
        await self._run_in_thread(self._sync_client.disconnect)
        self._connected = False
        self._logged_in = False
        logger.info("Async disconnected from server")
    
    async def get_player(self) -> Optional[Player]:
        """
        Get the local player object asynchronously.
        
        Returns:
            Player object if logged in, None otherwise
        """
        return await self._run_in_thread(self._sync_client.get_player)
    
    @property
    def connected(self) -> bool:
        """Check if client is connected"""
        return self._connected
    
    @property 
    def logged_in(self) -> bool:
        """Check if client is logged in"""
        return self._logged_in
    
    async def move(self, dx: int, dy: int) -> bool:
        """
        Move the player asynchronously.
        
        Args:
            dx: Change in X direction (-1, 0, or 1)
            dy: Change in Y direction (-1, 0, or 1)
            
        Returns:
            True if move was sent successfully
        """
        return await self._run_in_thread(self._sync_client.move, dx, dy)
    
    async def say(self, message: str) -> bool:
        """
        Send a chat message asynchronously.
        
        Args:
            message: Message to send
            
        Returns:
            True if message was sent successfully
        """
        if hasattr(self._sync_client, 'say'):
            return await self._run_in_thread(self._sync_client.say, message)
        return False
    
    async def drop_bomb(self, power: int = 1, timer: int = 55) -> bool:
        """
        Drop a bomb asynchronously.
        
        Args:
            power: Bomb power (1-3)
            timer: Bomb timer in ticks
            
        Returns:
            True if bomb was dropped successfully
        """
        if hasattr(self._sync_client, 'drop_bomb'):
            return await self._run_in_thread(self._sync_client.drop_bomb, power, timer)
        return False
    
    async def take_item(self, x: int, y: int) -> bool:
        """
        Take an item asynchronously.
        
        Args:
            x: X coordinate of item
            y: Y coordinate of item
            
        Returns:
            True if item take was sent successfully
        """
        if hasattr(self._sync_client, 'take_item'):
            return await self._run_in_thread(self._sync_client.take_item, x, y)
        return False
    
    async def request_file(self, filename: str) -> bool:
        """
        Request a file from the server asynchronously.
        
        Args:
            filename: Name of file to request
            
        Returns:
            True if file request was sent successfully
        """
        if hasattr(self._sync_client, 'request_file'):
            return await self._run_in_thread(self._sync_client.request_file, filename)
        return False
    
    # Property access for managers (if needed)
    @property
    def session_manager(self):
        """Get session manager"""
        return self._sync_client.session_manager if hasattr(self._sync_client, 'session_manager') else None
    
    @property
    def level_manager(self):
        """Get level manager"""
        return self._sync_client.level_manager if hasattr(self._sync_client, 'level_manager') else None
    
    @property
    def gmap_manager(self):
        """Get GMAP manager"""
        return self._sync_client.gmap_manager if hasattr(self._sync_client, 'gmap_manager') else None
    
    def close(self):
        """Close the async client and cleanup resources"""
        if hasattr(self._sync_client, 'disconnect'):
            self._sync_client.disconnect()
        self._executor.shutdown(wait=True)
        logger.info("AsyncClient closed")
    
    @classmethod
    async def connect_and_login(cls, host: str, port: int, username: str, password: str, 
                               version: str = "6.037") -> 'AsyncClient':
        """
        Create, connect, and login in one async operation.
        
        Args:
            host: Server hostname or IP address
            port: Server port number
            username: Account username
            password: Account password
            version: Protocol version to use
            
        Returns:
            Connected and logged-in AsyncClient instance
            
        Raises:
            ConnectionError: If connection or login fails
        """
        client = cls(host, port, version)
        
        if not await client.connect():
            raise ConnectionError(f"Failed to connect to {host}:{port}")
        
        if not await client.login(username, password):
            raise ConnectionError(f"Failed to login as {username}")
        
        return client
    
    @classmethod
    def from_builder(cls, builder: 'ClientBuilder') -> 'AsyncClient':
        """
        Create async client from a fluent builder.
        
        Args:
            builder: Configured ClientBuilder instance
            
        Returns:
            AsyncClient with builder configuration applied
        """
        # Build the sync client first
        sync_client = builder.build()
        
        # Create async wrapper
        async_client = cls(sync_client.host, sync_client.port, sync_client.version)
        async_client._sync_client = sync_client
        
        return async_client


# Convenience function for quick async connections
async def async_quick_connect(host: str = "localhost", port: int = 14900, 
                             username: str = "", password: str = "",
                             version: str = "6.037") -> Optional[AsyncClient]:
    """
    Quick async connection helper.
    
    Args:
        host: Server hostname (default: localhost)
        port: Server port (default: 14900)
        username: Account username (optional)
        password: Account password (optional)
        version: Protocol version (default: 6.037)
        
    Returns:
        Connected AsyncClient or None if failed
    """
    try:
        if username and password:
            return await AsyncClient.connect_and_login(host, port, username, password, version)
        else:
            client = AsyncClient(host, port, version)
            if await client.connect():
                return client
    except Exception as e:
        logger.error(f"Async quick connect failed: {e}")
    
    return None


__all__ = [
    'AsyncClient',
    'async_quick_connect'
]