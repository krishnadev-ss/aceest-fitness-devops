"""ACEest Fitness & Gym - application entry point (file name used in the brief).

The Flask application lives in app.py (create_app factory); the original
desktop versions are kept in legacy/. Run:  python ACEest_Fitness.py
"""
from app import APP_VERSION, create_app

application = create_app()

if __name__ == "__main__":
    print(f"ACEest Fitness v{APP_VERSION} on http://0.0.0.0:5000")
    application.run(host="0.0.0.0", port=5000)
