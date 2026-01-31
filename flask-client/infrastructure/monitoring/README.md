# Server Health Monitoring System

## Overview

This module implements a robust health monitoring system for backend servers following SOLID principles.

## Architecture

### SOLID Principles Applied

1. **Single Responsibility Principle (SRP)**
   - `ServerHealthMonitor`: Monitors only ONE server's health
   - `HealthMonitoringService`: Manages collection of monitors
   - `ServerConfig`: Holds only configuration data

2. **Open/Closed Principle (OCP)**
   - System is open for extension (can add new server types)
   - Closed for modification (don't need to change core classes)
   - Achieved through `IHealthMonitor` abstract interface

3. **Liskov Substitution Principle (LSP)**
   - All monitors implement `IHealthMonitor` interface
   - Can substitute any implementation without breaking code

4. **Interface Segregation Principle (ISP)**
   - `IHealthMonitor` defines only essential methods
   - No forced implementation of unused methods

5. **Dependency Inversion Principle (DIP)**
   - High-level `HealthMonitoringService` depends on `IHealthMonitor` abstraction
   - Not dependent on concrete `ServerHealthMonitor` implementation

## Components

### ServerConfig
```python
@dataclass
class ServerConfig:
    name: str              # Server identifier
    url: str               # Base URL
    port: int              # Port number
    health_endpoint: str   # Endpoint to check
    check_interval: float  # Seconds between checks
    timeout: float         # Request timeout
```

### ServerStatus (Enum)
- `UNKNOWN`: Initial state
- `AVAILABLE`: Server is responding
- `UNAVAILABLE`: Server is not responding

### ServerHealthMonitor
Monitors a single server in its own thread:
- Periodically checks server health
- Detects status changes
- Triggers callbacks on state transitions
- Auto-manages thread lifecycle

### HealthMonitoringService
Central service managing all monitors:
- Register/unregister servers
- Start/stop all monitoring
- Query server statuses
- Add status change listeners

## Usage

### Basic Setup (already in app.py)

```python
from infrastructure.monitoring import HealthMonitoringService, ServerConfig

# Get service instance
health_service = HealthMonitoringService()

# Register servers
health_service.register_server(ServerConfig(
    name="webcam-server",
    url="http://localhost",
    port=5001,
    health_endpoint="/devices",
    check_interval=5.0,
    timeout=2.0
))

# Start monitoring
health_service.start_all()
```

### Query Server Status

```python
# Check if server is available
is_available = health_service.is_server_available("webcam-server")

# Get detailed status
status = health_service.get_server_status("webcam-server")
# Returns: ServerStatus.AVAILABLE, UNAVAILABLE, or UNKNOWN

# Get all statuses
all_statuses = health_service.get_all_statuses()
# Returns: {'webcam-server': ServerStatus.AVAILABLE, ...}
```

### Listen to Status Changes

```python
def on_status_change(server_name, old_status, new_status):
    print(f"{server_name}: {old_status.value} -> {new_status.value}")
    
    if new_status == ServerStatus.AVAILABLE:
        print(f"Server {server_name} is back online!")
    elif new_status == ServerStatus.UNAVAILABLE:
        print(f"Server {server_name} went offline!")

health_service.add_status_change_listener(on_status_change)
```

### API Endpoints (health_controller.py)

```
GET /health/servers
Returns: {"webcam-server": "available", "legacy-camera-server": "unavailable", ...}

GET /health/servers/<server_name>
Returns: {"server": "webcam-server", "status": "available", "available": true}
```

## Thread Management

### Automatic Thread Lifecycle
- Each monitor runs in its own daemon thread
- Thread name: `HealthMonitor-{server_name}`
- Threads automatically start/stop with the service
- Graceful shutdown on application exit

### Status Change Detection
When a server status changes:
1. Monitor detects change in `_check_health()`
2. Updates internal state
3. Logs the change
4. Triggers registered callbacks
5. Service propagates to all listeners

## Benefits

1. **Automatic Recovery Detection**: Knows immediately when a downed server comes back
2. **Resource Efficient**: Only checks at configured intervals (default 5s)
3. **Non-Blocking**: Runs in separate threads, doesn't block main app
4. **Observable**: Can react to status changes via callbacks
5. **Testable**: Clean interfaces make unit testing straightforward
6. **Maintainable**: SOLID principles make code easy to extend and modify

## Example Monitoring Flow

```
[16:30:00] HealthMonitor-webcam-server: Checking http://localhost:5001/devices
[16:30:00] Server webcam-server status: AVAILABLE
[16:30:05] HealthMonitor-webcam-server: Checking http://localhost:5001/devices
[16:30:05] Connection failed (server down)
[16:30:05] Server webcam-server status changed: available -> unavailable
[16:30:10] HealthMonitor-webcam-server: Checking http://localhost:5001/devices
[16:30:10] Connection failed (server down)
[16:30:15] HealthMonitor-webcam-server: Checking http://localhost:5001/devices
[16:30:15] Server webcam-server status: AVAILABLE
[16:30:15] Server webcam-server status changed: unavailable -> available
```

## Integration with Existing Code

The health monitoring integrates seamlessly:
- No changes needed to existing camera controllers
- Can query status before starting video threads
- Can disable UI elements for unavailable servers
- Logs include thread names and module context
