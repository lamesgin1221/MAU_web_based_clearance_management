#!/usr/bin/env python
"""
Database initialization and management script for MAU Clearance System
"""
import sys
import os
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from app import app, db, User
from werkzeug.security import generate_password_hash


def init_db():
    """Initialize the database with tables and default data"""
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("✓ Database tables created")

        # Create default admin if it doesn't exist
        admin = User.query.filter_by(email='admin@mau.edu.ng').first()
        if not admin:
            print("Creating default admin user...")
            admin = User(
                full_name='System Administrator',
                email='admin@mau.edu.ng',
                password_hash=generate_password_hash('Admin@123'),
                role='admin',
                student_id='ADM001',
                department='Administration',
                phone='07000000000',
            )
            db.session.add(admin)
            db.session.commit()
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
