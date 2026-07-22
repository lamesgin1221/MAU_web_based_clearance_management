# MAU Clearance System

A student clearance workflow system built with Python Flask and SQLAlchemy for a university environment.

## Features
- Student registration and login
- Secure authentication with password hashing
- Role-based access for admin, student, department, library, finance, dormitory, and registrar users
- Clearance application submission and status tracking
- Approval workflow and printable certificate

## Requirements
- Python 3.10+
- SQLite3 (included with Python)

## Setup Instructions

### 1. Clone or Download the Project
```bash
cd /path/to/mau-clearance-system_py
```

### 2. Create a Virtual Environment
```bash
python -m venv venv
```

### 3. Activate Virtual Environment

**On Windows (PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

**On Windows (Command Prompt):**
```cmd
.\venv\Scripts\activate.bat
```

**On macOS/Linux:**
```bash
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Configure Environment (Optional)
Copy `.env.example` to `.env` and update settings if needed:
```bash
cp .env.example .env
```

### 6. Run the Application
```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Default Admin Credentials
- Email: `admin@mau.edu.ng`
- Password: `Admin@123`

## Project Structure
```
app.py                      # Main Flask application
requirements.txt            # Python dependencies
.env.example               # Environment variables template
.gitignore                 # Git ignore rules
templates/                 # HTML templates (Jinja2)
  ├── base.html
  ├── login.html
  ├── register.html
  ├── student/
  ├── admin/
  ├── department/
  ├── library/
  ├── finance/
  ├── dormitary/
  └── registrar/
static/                    # CSS and JavaScript
  └── css/
assests/                   # Static assets
  ├── css/
  ├── images/
  └── js/
uploads/                   # User uploaded files
tests/                     # Test files
```

## Database
The application uses SQLite by default, which is automatically created on first run as `data.db`.

### Database Models
- **User**: Stores user information (students, staff, admin)
- **ClearanceApplication**: Stores clearance applications and approval status

## Features Overview

### Student Features
- Register and login
- Submit clearance applications
- Upload photo
- Track application status
- Update profile

### Admin Features
- Manage students
- View all applications
- Generate reports
- Create office staff accounts

### Department/Office Features
- Approve/reject clearance requests
- View applications

## Running Tests
```bash
python -m pytest tests/
```

## Development
To run in debug mode:
```bash
FLASK_ENV=development FLASK_DEBUG=1 python app.py
```

## License
[Add your license here]

## Support
For issues or questions, contact the development team.
   ```powershell
   pip install -r requirements.txt
   ```
6. Start the app:
   ```powershell
   python app.py
   ```
7. Open `http://127.0.0.1:5000` in your browser.

### Default admin login for Flask
- Email: admin@mau.edu.ng
- Password: Admin@123
