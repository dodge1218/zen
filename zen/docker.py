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
    mem: str | None = None,
    cpu: float | None = None,
    pids: int | None = None,
    now: float | None = None,
) -> tuple[list[str], dict[str, str]]:
    if ttl_seconds <= 0:
        raise ValueError("--ttl must be greater than zero for docker-run")
    if mem:
        _validate_memory(mem)
    if cpu is not None and cpu <= 0:
        raise ValueError("--cpu must be greater than 0")
    if pids is not None and pids <= 0:
        raise ValueError("--pids must be greater than 0")
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
    if mem:
        args.extend(["--memory", mem])
    if cpu is not None:
        args.extend(["--cpus", str(cpu)])
    if pids is not None:
        args.extend(["--pids-limit", str(pids)])
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


def _validate_memory(value: str) -> None:
    raw = value.strip()
    if not raw:
        raise ValueError("--mem cannot be empty")
    suffix = raw[-1].lower()
    number = raw[:-1] if suffix.isalpha() else raw
    try:
        parsed = float(number)
    except ValueError as exc:
        raise ValueError("--mem must be a number with optional k/m/g/t suffix") from exc
    if parsed <= 0:
        raise ValueError("--mem must be greater than 0")
    if suffix.isalpha() and suffix not in {"k", "m", "g", "t"}:
        raise ValueError("--mem suffix must be one of k, m, g, or t")
