activityDiagram
    start
    :Engine calls _loop();
    
    repeat
        :Check GDPR Consent;
        if (Consent Revoked?) then (Yes)
            :Raise GDPRConsentError;
            stop
        else (No)
            :Call backend.poll_frame();
            
            note right
                Blocks thread on 
                xrWaitFrame (Vsync)
            end note
            
            fork
                :Extract HMD Transforms;
            fork again
                :Extract Eye Gaze Vectors;
            fork again
                :Extract Pupillometry;
            end fork
            
            :Compile TelemetryFrame (Flat Float32 Tensor);
            
            :Inject Scene ID Context (simulated logic);
            
            :BiometricSynchronizer.push_frame(frame);
            
            note right
                Non-blocking. 
                Pushes to Ring Buffer.
            end note
            
            :Increment frames_recorded counter;
        endif
    repeat while (is_running == true)
    
    :Proceed to _teardown();
    stop