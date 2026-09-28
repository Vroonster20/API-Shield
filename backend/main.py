"""Private Shield management listener ASGI entry point."""

from shield_api.admin_api import create_management

app = create_management()
