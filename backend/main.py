"""
Q-PORT Backend Entry Point
Run with: uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
import logging

import uvicorn

from app.api import app  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
