# Auth Manager Doc

### Purpose
This module handles central server account authentication, registration, session tracking, and user role management independently of machine licensing logic. It manages credentials using salted PBKDF2 hashing and handles user sessions to establish identity and access privileges across the application.

### Key Components / Key Classes / Key Exports
- **`AuthManager`**: Primary class responsible for user registration, login authentication, token-based session validation, logout revocation, admin promotion, and user listing.

### Integration Points
Interacts directly with a SQLite database containing tables for users, organizations, and sessions using standard database connections and queries.

---

# Bootstrap Admin Doc

### Purpose
This module provides a command-line script intended to be run once on the central server to bootstrap the very first administrator account. It initializes the database schema and utilizes the authentication manager to securely create a user with the admin role without exposing any HTTP endpoints.

### Key Components / Key Exports
- **`main`**: The primary executable function that prompts the operator for admin credentials (email, organization, display name, and password) and invokes the registration process.

### Integration Points
Interacts directly with `db_schema` to initialize the database tables and `auth_manager.AuthManager` to handle password hashing, organization creation, and database insertion of the admin user.

---

# Db Schema Doc

### Purpose
This module manages the SQLite database schema creation and initial setup for the license service central authority. It provides automated initialization and idempotent migrations to ensure all necessary tables, columns, and indexes exist for tracking organizations, users, sessions, licenses, and machine activations.

### Key Components / Key Classes / Key Exports
- **`initialize_license_schema`**: Sets up the database file path, executes the core SQL schema creation script, applies idempotent column migrations, and manages connection lifecycle and error logging.

### Integration Points
Interacts directly with the local file system using `pathlib` to ensure database directory structures exist, utilizes Python's built-in `sqlite3` library for relational data persistence, and integrates with the standard `logging` module to report initialization success or errors.

---

# Local Cache Doc

### Purpose
The `local_cache.py` module manages local persistence for client installations using SQLite. It is responsible for caching license status, handling offline grace periods, tracking pending uploads that failed to reach the central server, and managing active user account sessions and generic app configurations.

### Key Components / Key Classes / Key Exports
- **`LocalLicenseCache`**: Main class that encapsulates SQLite operations for local machine data storage including license state, pending data uploads, user sessions, and local app configuration values.
- **`_init_schema`**: Initializes the SQLite database and establishes required tables (`license_state`, `pending_uploads`, `account_session`, `app_config`) if they do not exist.
- **`save` / `mark_revoked` / `is_valid_offline`**: Methods managing the local license lifecycle and verifying offline grace periods.
- **`queue_pending_upload` / `list_pending_uploads`**: Methods managing offline or failed session data synchronization queues.

### Integration Points
Interacts directly with the local file system to provision and read from a SQLite database file (typically located under `AppData/license_cache.db`). It serves as a standalone caching layer supporting client licensing checks and offline synchronization routines.

---

# Manager Doc

### Purpose
This module acts as the server-side authority for issuing, validating, activating, and revoking software licenses and machine seats. It runs exclusively on secure server infrastructure to handle client desktop authentication requests, track active device heartbeats, and manage expiration enforcement via SQLite.

### Key Components / Key Classes / Key Exports
- **`LicenseManager`**: Core class responsible for handling the full lifecycle of licenses, including creation, validation, machine fingerprint binding, heartbeats, seat limit checking, and revocation.

### Integration Points
Interacts directly with a SQLite database (specified via `db_path`) containing tables for organizations, users, licenses, machine activations, and audit event logs. It is intended to be called by an HTTPS server handling API requests from desktop client applications.

---

---
