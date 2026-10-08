import os
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class RotationItem:
    value: str
    last_error: Optional[str] = None


class RotationPool:
    def __init__(self, items: List[str], blacklist_ttl: int = 300, name: str = ""):
        self.items = [RotationItem(value=item) for item in items if item]
        self.blacklist_ttl = max(0, int(blacklist_ttl))
        self.name = name or "rotation"
        self._blacklist: Dict[str, float] = {}

    def _cleanup_blacklist(self) -> None:
        now = time.time()
        expired = [key for key, ts in self._blacklist.items() if ts <= now]
        for key in expired:
            self._blacklist.pop(key, None)

    def available_items(self) -> List[RotationItem]:
        self._cleanup_blacklist()
        return [item for item in self.items if item.value not in self._blacklist]

    def pick_random(self) -> Optional[RotationItem]:
        candidates = self.available_items()
        if not candidates:
            return None
        return random.choice(candidates)

    def mark_bad(self, item: Optional[RotationItem], reason: str = "") -> None:
        if not item:
            return
        item.last_error = reason
        if self.blacklist_ttl <= 0:
            return
        self._blacklist[item.value] = time.time() + self.blacklist_ttl


def parse_proxy_pool(value: Optional[str]) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [entry.strip() for entry in str(value).split(",") if entry.strip()]


def _is_credential_or_backup_file(name: str) -> bool:
    """排除账号密码凭据文件（acc_credentials.json）与备份文件（*.bak 等）。

    这些文件混在 state 目录里会被 auto 账号策略误当成登录态 cookie 文件，
    导致任务用空 cookie 启动、被闲鱼重定向到登录页（显示"登录失效"）。"""
    lowered = name.lower()
    if "credential" in lowered or "cred_" in lowered or lowered.endswith("_cred.json"):
        return True
    if lowered.endswith(".bak") or lowered.endswith(".tmp") or lowered.endswith("~"):
        return True
    return False


def load_state_files(state_dir: str) -> List[str]:
    if not state_dir:
        return []
    if not os.path.isdir(state_dir):
        return []
    files = []
    for name in os.listdir(state_dir):
        if name.endswith(".json") and not _is_credential_or_backup_file(name):
            files.append(os.path.join(state_dir, name))
    return sorted(files)
