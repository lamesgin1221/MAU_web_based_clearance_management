#!/usr/bin/env python
"""
Database initialization and management script for MAU Clearance System
"""
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from app import app, db, ensure_default_admin


def init_db():
    """Initialize the database with tables and default data"""
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("✓ Database tables created")

        if ensure_default_admin():
            print("✓ Admin user created")
            print("  Email: admin@mau.edu.ng")
            print("  Password: Admin@123")
            print("  ⚠ IMPORTANT: Change this password in production!")
        else:
            print("✓ Admin user already exists")

        print("\n✓ Database initialization complete!")


def reset_db():
    """Drop all tables and reinitialize"""
    with app.app_context():
        print("WARNING: This will delete all data!")
        response = input("Are you sure? (yes/no): ").strip().lower()
        if response == 'yes':
            print("Dropping all tables...")
            db.drop_all()
            print("✓ Tables dropped")
            init_db()
        else:
            print("Cancelled.")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == 'init':
            init_db()
        elif sys.argv[1] == 'reset':
            reset_db()
        else:
            print(f"Unknown command: {sys.argv[1]}")
            print("Usage: python init_db.py [init|reset]")
    else:
        init_db()
