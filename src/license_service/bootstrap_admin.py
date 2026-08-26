# src/license_service/bootstrap_admin.py
"""
Run once, on the central server machine only, to create the first admin account:

    python -m src.license_service.bootstrap_admin

Never exposed as an HTTP endpoint — this is the one deliberately manual step
that prevents any client-reachable path from ever self-granting admin.
"""

import getpass
from src.license_service.db_schema import initialize_license_schema
from src.license_service.auth_manager import AuthManager

def main():
    initialize_license_schema()
    mgr = AuthManager()

    print("=== VRTelemetry Central Server: Create First Admin ===")
    email = input("Admin email: ").strip()
    org_name = input("Organization name (e.g. your company/lab): ").strip()
    display_name = input("Display name: ").strip()
    password = getpass.getpass("Password (min 8 chars): ")

    result = mgr.register(email, password, org_name, display_name, role="admin")
    if result["ok"]:
        print(f"\n✅ Admin account created: {email}")
    else:
        print(f"\n❌ Failed: {result['reason']}")

if __name__ == "__main__":
    main()