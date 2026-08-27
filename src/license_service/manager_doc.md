### Purpose
This module acts as the server-side authority for issuing, validating, activating, and revoking software licenses and machine seats. It runs exclusively on secure server infrastructure to handle client desktop authentication requests, track active device heartbeats, and manage expiration enforcement via SQLite.

### Key Components / Key Classes / Key Exports
- **`LicenseManager`**: Core class responsible for handling the full lifecycle of licenses, including creation, validation, machine fingerprint binding, heartbeats, seat limit checking, and revocation.

### Integration Points
Interacts directly with a SQLite database (specified via `db_path`) containing tables for organizations, users, licenses, machine activations, and audit event logs. It is intended to be called by an HTTPS server handling API requests from desktop client applications.
