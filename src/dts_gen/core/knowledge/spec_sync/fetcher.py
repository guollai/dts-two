from __future__ import annotations

from dataclasses import dataclass

import requests


class FetchError(Exception):
    def __init__(self, url: str, reason: str):
        super().__init__(f"failed to fetch {url}: {reason}")
        self.url = url
        self.reason = reason


@dataclass
class TrackedFile:
    filename: str
    source_url: str


def fetch(url: str) -> str:
    try:
        response = requests.get(url, timeout=10)
    except requests.RequestException as exc:
        raise FetchError(url, str(exc)) from exc
    if response.status_code != 200:
        raise FetchError(url, f"HTTP {response.status_code}")
    return response.text


def list_rst_files(api_url: str) -> list[TrackedFile]:
    try:
        response = requests.get(api_url, timeout=10)
    except requests.RequestException as exc:
        raise FetchError(api_url, str(exc)) from exc
    if response.status_code != 200:
        raise FetchError(api_url, f"HTTP {response.status_code}")

    try:
        entries = response.json()
    except ValueError as exc:
        raise FetchError(api_url, f"invalid JSON response: {exc}") from exc

    if not isinstance(entries, list):
        raise FetchError(api_url, "expected a list of directory entries, got a different JSON shape")

    return [
        TrackedFile(filename=entry["name"], source_url=entry["download_url"])
        for entry in entries
        if entry.get("type") == "file" and entry.get("name", "").endswith(".rst")
    ]
