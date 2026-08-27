### Purpose
This module handles central server account authentication, registration, session tracking, and user role management independently of machine licensing logic. It manages credentials using salted PBKDF2 hashing and handles user sessions to establish identity and access privileges across the application.

### Key Components / Key Classes / Key Exports
- **`AuthManager`**: Primary class responsible for user registration, login authentication, token-based session validation, logout revocation, admin promotion, and user listing.

### Integration Points
Interacts directly with a SQLite database containing tables for users, organizations, and sessions using standard database connections and queries.
