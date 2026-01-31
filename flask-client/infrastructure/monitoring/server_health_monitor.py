"""
Server Health Monitoring System

This module implements a health monitoring system for server connections following SOLID principles:
- Single Responsibility: Each class has one clear purpose
- Open/Closed: Extensible through abstraction without modifying existing code
- Liskov Substitution: All monitors are interchangeable through the base interface
- Interface Segregation: Clean, focused interfaces
- Dependency Inversion: Depends on abstractions (ABC) not concrete implementations
"""

import threading
import time
import requests
from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, Optional, Dict, List
from dataclasses import dataclass
from infrastructure.logging.logging_provider import get_logger

logger = get_logger()


class ServerStatus(Enum):
    """Enumeration of possible server states."""
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass
class ServerConfig:
    """Configuration for a server to monitor."""
    name: str
    url: str
    port: int
    health_endpoint: str
    check_interval: float = 5.0  # seconds between health checks
    timeout: float = 2.0  # timeout for health check requests


class IHealthMonitor(ABC):
    """
    Interface for health monitoring (Interface Segregation Principle).
    Defines the contract that all health monitors must implement.
    """
    
    @abstractmethod
    def start(self) -> None:
        """Start the health monitoring."""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop the health monitoring."""
        pass
    
    @abstractmethod
    def get_status(self) -> ServerStatus:
        """Get the current server status."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if server is currently available."""
        pass


class ServerHealthMonitor(IHealthMonitor):
    """
    Monitors health of a single server (Single Responsibility Principle).
    
    This class is responsible only for monitoring one server's health status.
    It runs in its own thread and periodically checks if the server is available.
    """
    
    def __init__(
        self, 
        config: ServerConfig,
        on_status_change: Optional[Callable[[str, ServerStatus, ServerStatus], None]] = None
    ):
        """
        Initialize the health monitor.
        
        Args:
            config: Server configuration
            on_status_change: Optional callback function(server_name, old_status, new_status)
        """
        self._config = config
        self._on_status_change = on_status_change
        self._status = ServerStatus.UNKNOWN
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
    def start(self) -> None:
        """Start the health monitoring thread."""
        if self._running:
            logger.warning(f"Health monitor for {self._config.name} is already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name=f"HealthMonitor-{self._config.name}",
            daemon=True
        )
        self._thread.start()
        logger.info(f"Health monitor started for {self._config.name} (checking every {self._config.check_interval}s)")
    
    def stop(self) -> None:
        """Stop the health monitoring thread."""
        if not self._running:
            return
        
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info(f"Health monitor stopped for {self._config.name}")
    
    def get_status(self) -> ServerStatus:
        """Get the current server status."""
        with self._lock:
            return self._status
    
    def is_available(self) -> bool:
        """Check if server is currently available."""
        return self.get_status() == ServerStatus.AVAILABLE
    
    def _monitor_loop(self) -> None:
        """Main monitoring loop running in separate thread."""
        while self._running:
            try:
                # Perform health check
                new_status = self._check_health()
                
                # Update status and trigger callback if changed
                with self._lock:
                    old_status = self._status
                    if new_status != old_status:
                        self._status = new_status
                        logger.info(
                            f"Server {self._config.name} status changed: "
                            f"{old_status.value} -> {new_status.value}"
                        )
                        
                        # Trigger callback if provided
                        if self._on_status_change:
                            try:
                                self._on_status_change(self._config.name, old_status, new_status)
                            except Exception as e:
                                logger.error(f"Error in status change callback for {self._config.name}: {e}")
                
                # Wait before next check
                time.sleep(self._config.check_interval)
                
            except Exception as e:
                logger.error(f"Error in health monitor loop for {self._config.name}: {e}")
                time.sleep(self._config.check_interval)
    
    def _check_health(self) -> ServerStatus:
        """
        Perform actual health check against the server.
        
        Returns:
            ServerStatus indicating if server is available or not
        """
        try:
            full_url = f"http://localhost:{self._config.port}{self._config.health_endpoint}"
            response = requests.get(full_url, timeout=self._config.timeout)
            
            if response.status_code == 200:
                return ServerStatus.AVAILABLE
            else:
                logger.debug(
                    f"Server {self._config.name} returned status {response.status_code}"
                )
                return ServerStatus.UNAVAILABLE
                
        except requests.exceptions.ConnectionError:
            logger.debug(f"Server {self._config.name} is not reachable")
            return ServerStatus.UNAVAILABLE
        except requests.exceptions.Timeout:
            logger.debug(f"Server {self._config.name} health check timed out")
            return ServerStatus.UNAVAILABLE
        except Exception as e:
            logger.error(f"Unexpected error checking {self._config.name}: {e}")
            return ServerStatus.UNAVAILABLE


class HealthMonitoringService:
    """
    Service that manages all server health monitors (Dependency Inversion Principle).
    
    This class coordinates multiple health monitors and provides a unified interface
    for managing server health monitoring across the application.
    """
    
    def __init__(self):
        """Initialize the health monitoring service."""
        self._monitors: Dict[str, ServerHealthMonitor] = {}
        self._lock = threading.Lock()
        self._status_change_callbacks: List[Callable[[str, ServerStatus, ServerStatus], None]] = []
        
    def register_server(self, config: ServerConfig) -> None:
        """
        Register a server for health monitoring.
        
        Args:
            config: Server configuration
        """
        with self._lock:
            if config.name in self._monitors:
                logger.warning(f"Server {config.name} is already registered")
                return
            
            # Create monitor with internal callback
            monitor = ServerHealthMonitor(
                config=config,
                on_status_change=self._on_monitor_status_change
            )
            self._monitors[config.name] = monitor
            logger.info(f"Registered server {config.name} for health monitoring")
    
    def unregister_server(self, server_name: str) -> None:
        """
        Unregister a server from health monitoring.
        
        Args:
            server_name: Name of the server to unregister
        """
        with self._lock:
            if server_name in self._monitors:
                monitor = self._monitors[server_name]
                monitor.stop()
                del self._monitors[server_name]
                logger.info(f"Unregistered server {server_name} from health monitoring")
    
    def start_all(self) -> None:
        """Start monitoring all registered servers."""
        with self._lock:
            for name, monitor in self._monitors.items():
                monitor.start()
        logger.info(f"Started health monitoring for {len(self._monitors)} servers")
    
    def stop_all(self) -> None:
        """Stop monitoring all registered servers."""
        with self._lock:
            for name, monitor in self._monitors.items():
                monitor.stop()
        logger.info("Stopped all health monitoring")
    
    def get_server_status(self, server_name: str) -> Optional[ServerStatus]:
        """
        Get the current status of a specific server.
        
        Args:
            server_name: Name of the server
            
        Returns:
            ServerStatus or None if server is not registered
        """
        with self._lock:
            monitor = self._monitors.get(server_name)
            return monitor.get_status() if monitor else None
    
    def is_server_available(self, server_name: str) -> bool:
        """
        Check if a specific server is available.
        
        Args:
            server_name: Name of the server
            
        Returns:
            True if server is available, False otherwise
        """
        status = self.get_server_status(server_name)
        return status == ServerStatus.AVAILABLE if status else False
    
    def get_all_statuses(self) -> Dict[str, ServerStatus]:
        """
        Get status of all monitored servers.
        
        Returns:
            Dictionary mapping server names to their current status
        """
        with self._lock:
            return {
                name: monitor.get_status() 
                for name, monitor in self._monitors.items()
            }
    
    def add_status_change_listener(
        self, 
        callback: Callable[[str, ServerStatus, ServerStatus], None]
    ) -> None:
        """
        Add a callback to be notified of any server status changes.
        
        Args:
            callback: Function(server_name, old_status, new_status)
        """
        self._status_change_callbacks.append(callback)
    
    def _on_monitor_status_change(
        self, 
        server_name: str, 
        old_status: ServerStatus, 
        new_status: ServerStatus
    ) -> None:
        """
        Internal callback for when any monitor detects a status change.
        Propagates to all registered listeners.
        """
        for callback in self._status_change_callbacks:
            try:
                callback(server_name, old_status, new_status)
            except Exception as e:
                logger.error(f"Error in status change listener: {e}")


# Singleton instance for application-wide use
_health_monitoring_service: Optional[HealthMonitoringService] = None


def get_health_monitoring_service() -> HealthMonitoringService:
    """
    Get the singleton health monitoring service instance.
    
    Returns:
        The global HealthMonitoringService instance
    """
    global _health_monitoring_service
    if _health_monitoring_service is None:
        _health_monitoring_service = HealthMonitoringService()
    return _health_monitoring_service
