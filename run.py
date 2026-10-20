"""Local run: python run.py  (production: gunicorn, see Dockerfile)."""
import os

from app.web import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False, threaded=True)
