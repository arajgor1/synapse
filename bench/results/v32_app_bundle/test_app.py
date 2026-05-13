import pytest
from your_flask_app import app  # Replace 'your_flask_app' with the actual name of your Flask app module

def test_todos_endpoint():
    client = app.test_client()
    resp = client.get('/todos')
    assert resp.status_code == 200