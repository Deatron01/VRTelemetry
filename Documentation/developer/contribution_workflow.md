activityDiagram
    start
    :Fork VRTelemetry Repository;
    :Clone Local Copy;
    :Create Feature Branch (feat/new-driver);
    
    repeat
        :Write Code / Driver Integration;
        :Run Unit Tests (Mocked Data)
        `pytest tests/unit/`;
        
        if (Unit Tests Pass?) then (No)
            :Debug & Refactor Code;
        else (Yes)
            :Run Integration Tests
            `pytest tests/integration/`;
            
            if (Integration Pass?) then (No)
                :Debug & Refactor Code;
            else (Yes)
                :Run Tox (Cross-Environment)
                `tox -e py310,py311,py312`;
            endif
        endif
    repeat while (Tox Fails?)
    
    note right
        Ensure tests are run 
        with -m "not hardware" 
        if no HMD is connected.
    end note
    
    :Commit Code (Signed);
    :Open Pull Request (PR) to Main;
    
    :GitHub Actions CI Triggered;
    note right
        Automated Lints and 
        Hardware-Skipped Tests.
    end note
    
    if (CI Passes & Code Reviewed?) then (Yes)
        :Merge into Main;
    else (No)
        :Address Review Feedback;
    endif
    
    stop