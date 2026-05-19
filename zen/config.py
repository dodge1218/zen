from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any


@dataclass
class Thresholds:
    yellow_swap_pct: float = 35
    red_swap_pct: float = 60
    black_swap_pct: float = 80
    yellow_load_1m: float = 6
    red_load_1m: float = 10
    yellow_available_gb: float = 4
    red_available_gb: float = 2


@dataclass
class Policy:
    protect_names: tuple[str, ...] = (
        "brave",
        "brave-browser",
        "chrome",
        "chromium",
        "gnome-terminal-",
        "gnome-terminal-server",
        "xterm",
        "konsole",
        "tilix",
        "ollama",
        "cinnamon",
        "Xorg",
    )
    protect_cmd_substrings: tuple[str, ...] = (
        "BraveSoftware/Brave-Browser",
        "google-chrome",
        "/usr/libexec/gnome-terminal-server",
        "codex --yolo",
        "codex resume",
        "claude",
    )
    ephemeral_cmd_substrings: tuple[str, ...] = (
        "kind create cluster",
        "kubeadm init --config=/kind/kubeadm.conf",
        "scripts/cron-risk-scan.ts",
        "scripts/private-mvp-review.ts",
        "pnpm worker:scan",
        "pnpm review:private-mvp",
        "pnpm smoke:desktop",
        "typescript/bin/tsc -p tsconfig.json --noEmit",
        "node (vitest",
        "tinypool",
        "pnpm -r build",
    )
    ephemeral_cwd_prefixes: tuple[str, ...] = ()
    poc_container_names: tuple[str, ...] = ()
    poc_container_images: tuple[str, ...] = (
        "kindest/node",
        "curlimages/curl",
    )
    keep_container_names: tuple[str, ...] = ()
    thresholds: Thresholds = field(default_factory=Thresholds)


def state_dir() -> Path:
    override = os.environ.get("ZEN_STATE_DIR")
    path = Path(override).expanduser() if override else Path.home() / ".local" / "state" / "zen"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    override = os.environ.get("ZEN_CONFIG_DIR")
    path = Path(override).expanduser() if override else Path.home() / ".config" / "zen"
    path.mkdir(parents=True, exist_ok=True)
    return path


def policy_path() -> Path:
    return config_dir() / "policy.json"


def default_policy() -> Policy:
    return load_policy()


def load_policy(path: Path | None = None) -> Policy:
    policy = Policy()
    path = path or policy_path()
    if not path.exists():
        return policy
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: could not read Zen policy config {path}: {exc}", file=sys.stderr)
        return policy
    if not isinstance(raw, dict):
        print(f"warning: Zen policy config {path} must be a JSON object", file=sys.stderr)
        return policy
    return apply_policy_overrides(policy, raw)


def apply_policy_overrides(policy: Policy, raw: dict[str, Any]) -> Policy:
    list_fields = {
        "protect_names",
        "protect_cmd_substrings",
        "ephemeral_cmd_substrings",
        "ephemeral_cwd_prefixes",
        "poc_container_names",
        "poc_container_images",
        "keep_container_names",
    }
    for name in list_fields:
        if name in raw:
            value = _string_tuple(raw[name], field_name=name)
            if value is not None:
                setattr(policy, name, value)
        extra_name = f"extra_{name}"
        if extra_name in raw:
            value = _string_tuple(raw[extra_name], field_name=extra_name)
            if value is not None:
                setattr(policy, name, tuple(getattr(policy, name)) + value)
    thresholds = raw.get("thresholds")
    if isinstance(thresholds, dict):
        valid_thresholds = {field.name for field in dataclass_fields(Thresholds)}
        for key, value in thresholds.items():
            if key not in valid_thresholds:
                print(f"warning: unknown Zen threshold {key}", file=sys.stderr)
                continue
            try:
                setattr(policy.thresholds, key, float(value))
            except (TypeError, ValueError):
                print(f"warning: threshold {key} must be numeric", file=sys.stderr)
    elif thresholds is not None:
        print("warning: Zen thresholds override must be a JSON object", file=sys.stderr)
    return policy


def write_default_policy(path: Path | None = None, overwrite: bool = False) -> Path:
    path = path or policy_path()
    if path.exists() and not overwrite:
        return path
    policy = Policy()
    data = {
        "extra_protect_names": [],
        "extra_protect_cmd_substrings": [],
        "extra_ephemeral_cmd_substrings": [],
        "extra_ephemeral_cwd_prefixes": [],
        "extra_poc_container_names": [],
        "extra_poc_container_images": [],
        "extra_keep_container_names": [],
        "thresholds": policy.thresholds.__dict__,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        print(f"warning: Zen policy field {field_name} must be a list of strings", file=sys.stderr)
        return None
    return tuple(value)
