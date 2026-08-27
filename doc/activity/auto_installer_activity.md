```mermaid
activityDiagram
    start
    :verify_and_install_dependencies;
    :Locate requirements.txt;
    if (File exists?) then (yes)
        :Run pip install via subprocess;
        if (Installation success?) then (yes)
            :Log success;
            stop
        else (no)
            :Log critical error and exit;
            stop
        endif
    else (no)
        :Log error and return;
        stop
    endif
```
