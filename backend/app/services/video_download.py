from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import httpx


async def download_video(
    url: str,
    *,
    target: Path,
    temporary: Path,
    max_bytes: int,
    headers: dict[str, str],
    timeout_seconds: float = 120,
    error_factory: Callable[[int, str], Exception],
) -> tuple[int, Path]:
    temporary.unlink(missing_ok=True)
    total = 0
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                declared = int(response.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise error_factory(502, "Полученное видео превышает лимит хранения.")
                with temporary.open("xb") as output:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise error_factory(502, "Полученное видео превышает лимит хранения.")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
        if total <= 16:
            raise error_factory(502, "Провайдер вернул пустой видеофайл.")
        with temporary.open("rb") as source:
            if b"ftyp" not in source.read(64):
                raise error_factory(502, "Провайдер вернул файл неизвестного видеоформата.")
        os.replace(temporary, target)
        return total, target
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
