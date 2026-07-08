activityDiagram
    start
    :Trigger Teardown 
    (KeyboardInterrupt or GDPR Violation);
    
    :is_running = False;
    
    note right
        Breaks the main hardware
        polling loop safely.
    end note
    
    :BiometricSynchronizer.stop();
    
    if (Async Loop is running?) then (Yes)
        :async_loop.call_soon_threadsafe(stop);
    else (No)
    endif
    
    if (Async Thread exists?) then (Yes)
        :async_thread.join(timeout=3.0);
        note right
            Waits up to 3 seconds for remaining 
            Parquet buffers to flush to disk.
        end note
    else (No)
    endif
    
    :HardwareMonitor.stop();
    :AsyncParquetWriter.stop();
    
    :OpenXRHeadlessBackend.shutdown();
    note right
        Releases API handles,
        Destroys XrSpace and Session.
    end note
    
    :Log Finalization (Frames recorded);
    stop