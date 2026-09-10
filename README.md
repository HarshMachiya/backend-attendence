# Attendance System

This project is an Attendance System consisting of a backend API built with Django (Python) and a frontend web application built with React and Vite.

## Project Structure

- `backend-attendence/`: The Django REST Framework backend API.
- `frontend-attendence/`: The React (Vite) frontend application.

---

## 🚀 How to start the project locally

### 1. Backend Setup

Prerequisites: Python 3.10+ installed.

1. Navigate to the backend directory:
   ```bash
   cd backend-attendence
   ```
2. Create and activate a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```
3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run database migrations:
   ```bash
   python manage.py migrate
   ```
5. Start the Django development server:
   ```bash
   python manage.py runserver
   ```
   The backend API will be available at `http://127.0.0.1:8000/`.

### 2. Frontend Setup

Prerequisites: Node.js (v18+) and npm installed.

1. Navigate to the frontend directory:
   ```bash
   cd frontend-attendence
   ```
2. Install the node dependencies:
   ```bash
   npm install
   ```
3. Start the Vite development server:
   ```bash
   npm run dev
   ```
   The frontend application will be running locally (usually at `http://localhost:5173/`).

---

## 🌍 How to deploy the project to Production

### 1. Backend (Django) Production Deployment

- **Database:** Ensure you switch from SQLite (`db.sqlite3`) to a robust database like PostgreSQL or MySQL in `settings.py` for production.
- **Environment Variables:** Set `DEBUG = False` and configure `ALLOWED_HOSTS` in your environment variables (`.env` file).
- **Static Files:** Run `python manage.py collectstatic` to gather static files. The project already uses `whitenoise` which helps serve static files in production.
- **Server:** Do not use `runserver`. Instead, use a WSGI server like `gunicorn` (already in `requirements.txt`).
  ```bash
  gunicorn backend_attendence.wsgi:application --bind 0.0.0.0:8000
  ```
- **Hosting Platforms:** You can deploy this backend easily on Heroku (using the provided `Procfile` and `runtime.txt`), Render, or a VPS (using Nginx as a reverse proxy to Gunicorn).

### 2. Frontend (React) Production Deployment

- **Build the App:** Generate the optimized production build of your frontend.
  ```bash
  cd frontend-attendence
  npm run build
  ```
- **Deploying the Build:** The build output will be in the `frontend-attendence/dist/` directory. You can deploy this static directory to any static file hosting service, such as:
  - Vercel
  - Netlify
  - GitHub Pages
  - AWS S3 / CloudFront
  - Or serve it via Nginx alongside your backend on a VPS.

Ensure that your frontend makes API requests to the production URL of your backend (e.g., by setting an environment variable in Vite `.env.production` file for your Axios base URL).
