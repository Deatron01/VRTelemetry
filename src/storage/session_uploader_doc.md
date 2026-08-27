### Purpose
The `session_uploader` module handles transmitting completed recording sessions and associated logs to a central hub server. It integrates local licensing state checks and robust failure handling, ensuring failed uploads are queued locally for automatic or on-demand retries.

### Key Components / Key Classes / Key Exports
- **`SessionUploader`**: Core class responsible for executing HTTP POST requests to upload session parquet files and log files, managing local retry queues, and verifying active licenses before transmission.
- **`upload`**: Sends session data and metadata to the central server, queuing the item locally upon network failure or invalid license states.
- **`retry_pending`**: Sweeps the local pending-uploads queue to re-attempt transmission of previously failed sessions.
- **`upload_log`**: Uploads secondary session logs to a dedicated endpoint on the central server.

### Integration Points
This module integrates directly with the `LocalLicenseCache` to fetch authorization states, manage failed upload queues, and clear records upon successful syncs. It uses the `requests` library to communicate with the central server endpoints and interacts with the filesystem via `pathlib.Path` to read local Parquet and log files.
