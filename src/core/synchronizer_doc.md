### Purpose
BiometricSynchronizer provides a lock-free ring buffer architecture designed to support 144Hz zero-loss telemetry transport. It decouples high-frequency OpenXR rendering and hardware threads from disk-writing I/O tasks to prevent tracking stalls and ensure consistent performance.

### Key Components / Key Classes / Key Exports
- **`BiometricSynchronizer`**: Core class managing a thread-safe `deque` buffer, asynchronous consumer loops, and graceful frame flushing during shutdown.
- **`push_frame`**: Non-blocking method invoked by the hardware thread to instantly capture and buffer telemetry frames.
- **`_consume_loop`**: Asynchronous background worker that batches buffered frame data and forwards it to disk storage components.

### Integration Points
Interfaces directly with `AsyncParquetWriter` for disk persistence, `HardwareMonitor` for telemetry tracking, and an `asyncio` event loop to manage background flushing operations.
