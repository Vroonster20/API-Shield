import os

# Set before any test imports the app, because config.py reads settings at import time.
os.environ["ADMIN_PASSWORD"] = "test-admin-password-123"