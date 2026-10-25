"""Entry point for gunicorn on the server:  gunicorn wsgi:app"""

from thinkballot.app import create_app

app = create_app()
