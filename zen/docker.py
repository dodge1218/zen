from __future__ import annotations

import time
import uuid


MANAGED_LABEL = "io.github.dodge1218.zen.managed"
LEASE_LABEL = "io.github.dodge1218.zen.lease_id"
CREATED_LABEL = "io.github.dodge1218.zen.created_at"
EXPIRES_LABEL = "io.github.dodge1218.zen.expires_at"


def build_docker_run_command(
    image: str,
    command: list[str],
    ttl_seconds: int,
    name: str | None = None,
    now: float | None = None,
) -> tuple[list[str], dict[str, str]]:
    if ttl_seconds <= 0:
        raise ValueError("--ttl must be greater than zero for docker-run")
    created_at = int(now if now is not None else time.time())
    labels = {
        MANAGED_LABEL: "true",
        LEASE_LABEL: str(uuid.uuid4()),
        CREATED_LABEL: str(created_at),
        EXPIRES_LABEL: str(created_at + ttl_seconds),
    }
    args = ["docker", "run", "-d"]
    if name:
        args.extend(["--name", name])
    for key, value in labels.items():
        args.extend(["--label", f"{key}={value}"])
    args.append(image)
    args.extend(command)
    return args, labels


def docker_container_expired(labels: dict[str, str], now: float | None = None) -> bool:
    try:
        expires_at = float(labels[EXPIRES_LABEL])
    except (KeyError, TypeError, ValueError):
        return False
    return expires_at <= (now if now is not None else time.time())


def docker_container_has_expiry(labels: dict[str, str]) -> bool:
    try:
        float(labels[EXPIRES_LABEL])
    except (KeyError, TypeError, ValueError):
        return False
    return True
