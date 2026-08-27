### Purpose
This module provides a command-line script intended to be run once on the central server to bootstrap the very first administrator account. It initializes the database schema and utilizes the authentication manager to securely create a user with the admin role without exposing any HTTP endpoints.

### Key Components / Key Exports
- **`main`**: The primary executable function that prompts the operator for admin credentials (email, organization, display name, and password) and invokes the registration process.

### Integration Points
Interacts directly with `db_schema` to initialize the database tables and `auth_manager.AuthManager` to handle password hashing, organization creation, and database insertion of the admin user.
