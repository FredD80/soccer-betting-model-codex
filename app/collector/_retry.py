"""Shared retry policy for outbound HTTP calls in collectors.

Retries on connection errors and timeouts with exponential backoff.
Up to 3 attempts, waiting 1s -> 2s -> 4s (capped at 10s).
"""
import httpx
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

http_retry = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((
        requests.ConnectionError,
        requests.Timeout,
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.ConnectTimeout,
        httpx.RemoteProtocolError,
    )),
)
