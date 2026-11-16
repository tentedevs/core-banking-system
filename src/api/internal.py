"""Private listener. Bind to loopback/trusted network; never reverse-proxy publicly."""

from api.main import create_app

app = create_app(internal=True)
