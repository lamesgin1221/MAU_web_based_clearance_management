#!/usr/bin/env python
"""
Database initialization and management script for MAU Clearance System
"""
import sys
import os
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.exc import SQLAlchemyError

from app import app, db, User
from werkzeug.security import generate_password_hash


def init_db():
    """Initialize the database with tables and default data"""
    with app.app_context():
        try:
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
        except SQLAlchemyError as exc:
            db.session.rollback()
            print(f"✗ Database initialization failed: {exc}", file=sys.stderr)
            raise


def reset_db():
    """Drop all tables and reinitialize"""
    with app.app_context():
        print("WARNING: This will delete all data!")
        try:
            response = input("Are you sure? (yes/no): ").strip().lower()
        except EOFError:
            print("✗ No confirmation received (non-interactive input). Cancelled.", file=sys.stderr)
            raise SystemExit(1)
        if response != 'yes':
            print("Cancelled.")
            return
        try:
            print("Dropping all tables...")
            db.drop_all()
            print("✓ Tables dropped")
        except SQLAlchemyError as exc:
            db.session.rollback()
            print(f"✗ Could not drop the tables: {exc}", file=sys.stderr)
            raise
        init_db()


def main(argv):
    command = argv[1] if len(argv) > 1 else 'init'
    commands = {'init': init_db, 'reset': reset_db}
    handler = commands.get(command)
    if handler is None:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Usage: python init_db.py [init|reset]", file=sys.stderr)
        return 2
    try:
        handler()
    except SQLAlchemyError:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
