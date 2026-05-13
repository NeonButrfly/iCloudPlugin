"""Thin MCP proxy for the iCloud index service."""

from .service_client import ICloudIndexServiceClient, build_search_params

__all__ = ["ICloudIndexServiceClient", "build_search_params"]
