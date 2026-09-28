"""Uvicorn public gateway entry point; disable server proxy-header rewriting."""

import os

from shield_api.gateway import create_gateway

app = create_gateway(
    trusted_edge_cidrs=tuple(filter(None, os.getenv("SHIELD_TRUSTED_EDGE_CIDRS", "").split(",")))
)
