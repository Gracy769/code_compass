"""server.py — Python-native launcher for Code Compass web server.

Reads PORT from environment variables natively to prevent shell-expansion
failures across container platforms like Railway, Render, and Docker.
"""

import os
import sys

import uvicorn


def main() -> None:
    port_str = os.environ.get("PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        print(f"[code-compass] WARNING: Invalid PORT='{port_str}', defaulting to 8000", file=sys.stderr)
        port = 8000

    host = os.environ.get("HOST", "0.0.0.0")
    print(f"[code-compass] Launching server on {host}:{port}")
    uvicorn.run("code_compass.web.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
