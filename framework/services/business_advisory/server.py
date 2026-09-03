from __future__ import annotations

from aimec_http import AimecHandler, serve
from capability import execute_capability


def execute(handler: AimecHandler, payload: dict) -> tuple[int, dict]:
    return execute_capability(handler, payload)


if __name__ == "__main__":
    serve("business-advisory", {("POST", "/v1/capabilities/execute"): execute})
