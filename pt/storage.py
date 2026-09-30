"""账户持久化: 每个账户一个 JSON 文件, 原子写入。"""
from __future__ import annotations

import json
import os
import time

from .config import ACCOUNTS_DIR, DATA_DIR
from .models import DEFAULT_ACCOUNT_NAME, Account
from .i18n import _tr


def _ensure_dirs() -> None:
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)


def account_path(account_id: str) -> str:
    return os.path.join(ACCOUNTS_DIR, "{}.json".format(account_id))


AUTO_BACKUP_SECONDS = 20 * 60     # 每个账户最多 20 分钟自动存一份快照
_last_auto: dict = {}             # account_id -> 上次自动备份的时间
LOAD_FAILURES: list = []          # 读坏了的文件, 启动时要告诉用户, 不能闷声吞掉


def save_account(acc: Account) -> None:
    _ensure_dirs()
    path = account_path(acc.id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(acc.to_dict(), f, ensure_ascii=False, indent=1)
        # 光 close 不够: os.replace 的**改名**是原子的, 但 tmp 的**内容**可能
        # 还在系统缓存里。硬重启/断电会让你拿到一个改好名的空文件, 然后
        # 解析失败 -> 以前的代码会当成"没有账户"再建一个新的, 神不知鬼不觉。
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _auto_backup(acc)


def _auto_backup(acc: Account) -> None:
    """定期留快照。以前只有「重置/删除」前才备份, 平时一次都不存。"""
    now = time.time()
    if now - _last_auto.get(acc.id, 0.0) < AUTO_BACKUP_SECONDS:
        return
    _last_auto[acc.id] = now
    try:
        backup_account(acc, "auto")
    except OSError:
        pass                      # 备份失败不能拖累正常保存


def load_account(account_id: str) -> Account | None:
    path = account_path(account_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return Account.from_dict(json.load(f))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
        # 文件坏了。把它挪到一边(别直接覆盖掉, 万一还能人工抢救),
        # 并记下来 —— 启动时必须明确告诉用户, 而不是默默开个新账户。
        keep = "{}.corrupt-{}".format(path, time.strftime("%Y%m%d-%H%M%S"))
        try:
            os.replace(path, keep)
        except OSError:
            keep = path
        LOAD_FAILURES.append((account_id, keep, "{}: {}".format(type(e).__name__, e)))
        return None


def list_accounts() -> list[Account]:
    _ensure_dirs()
    out = []
    for fn in sorted(os.listdir(ACCOUNTS_DIR)):
        if not fn.endswith(".json"):
            continue
        acc = load_account(fn[:-5])
        if acc:
            out.append(acc)
    out.sort(key=lambda a: a.created_at)
    return out


def delete_account(account_id: str) -> bool:
    path = account_path(account_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def active_account_id() -> str | None:
    p = os.path.join(DATA_DIR, "active.txt")
    if os.path.exists(p):
        try:
            return open(p, encoding="utf-8").read().strip() or None
        except OSError:
            return None
    return None


def set_active_account_id(account_id: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "active.txt"), "w", encoding="utf-8") as f:
        f.write(account_id)


RECOVERED_FROM: str = ""          # 这次启动是不是从备份救回来的, UI 要提示


def bootstrap(initial_cash: float) -> Account:
    """返回当前账户; 没有任何账户时先试着从备份恢复, 实在没有才新建。"""
    global RECOVERED_FROM
    accounts = list_accounts()
    if not accounts:
        # 账户文件没了或者读坏了 —— 先翻备份。直接建新账户等于把数据丢掉
        # 还不吭声, 那是最坏的做法。
        for path, name, aid, mtime, summary in list_backups():
            acc = load_backup(path)
            if acc is None:
                continue
            RECOVERED_FROM = "{}  ({})".format(
                os.path.basename(path), time.strftime("%Y-%m-%d %H:%M",
                                                      time.localtime(mtime)))
            save_account(acc)
            set_active_account_id(acc.id)
            return acc
        acc = Account(name=DEFAULT_ACCOUNT_NAME, initial_cash=initial_cash, cash=initial_cash)
        acc.equity_curve.append([time.time(), initial_cash])
        save_account(acc)
        set_active_account_id(acc.id)
        return acc
    aid = active_account_id()
    for a in accounts:
        if a.id == aid:
            return a
    set_active_account_id(accounts[0].id)
    return accounts[0]


# ======================================================================
# 备份 —— 重置/删除前自动存一份, 手滑了还能救回来
# ======================================================================
BACKUP_DIR = os.path.join(DATA_DIR, "backups")


def backup_account(acc: Account, tag: str = "") -> str:
    """把账户另存一份带时间戳的快照, 返回文件路径。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    # 文件名里的可读部分用显示名 (默认账户名跟着界面语言走)。恢复时读的是
    # 文件内容里的 id/name, 不解析文件名, 所以这里怎么起名都不影响恢复。
    safe = "".join(ch for ch in acc.display_name if ch.isalnum() or ch in "-_ ")[:24]
    safe = safe.strip().replace(" ", "_") or acc.id
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = "{}_{}_{}{}.json".format(safe, acc.id, stamp, "_" + tag if tag else "")
    path = os.path.join(BACKUP_DIR, name)
    # 文件名只精确到秒 —— 同一秒内两次备份 (比如"重置前"撞上自动备份) 会互相
    # 覆盖, 白存一份。撞了就加序号。
    n = 1
    while os.path.exists(path):
        path = os.path.join(BACKUP_DIR, name[:-5] + "-{}.json".format(n))
        n += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(acc.to_dict(), f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    _prune_backups()
    return path


def _prune_backups(cap: int = 400) -> None:
    """分层保留: 48 小时内的全留, 更早的每天只留最新一份, 总数封顶。

    以前是一刀切留 60 份。自动备份 20 分钟一次的话, 60 份只覆盖 20 小时 ——
    等你发现数据不对的时候, 出问题之前的快照早被挤掉了。
    """
    if not os.path.isdir(BACKUP_DIR):
        return
    files = sorted(
        (os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith(".json")),
        key=os.path.getmtime, reverse=True)
    now = time.time()
    keep, seen_days = [], set()
    for p in files:
        mt = os.path.getmtime(p)
        if now - mt < 48 * 3600:
            keep.append(p)
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(mt))
        if day not in seen_days:
            seen_days.add(day)
            keep.append(p)
    keep = set(keep[:cap])
    for p in files:
        if p not in keep:
            try:
                os.remove(p)
            except OSError:
                pass


def list_backups() -> list:
    """返回 [(路径, 账户名, 账户id, 修改时间, 摘要)]，按时间倒序。"""
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for fn in os.listdir(BACKUP_DIR):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(BACKUP_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        out.append((path, d.get("name", "?"), d.get("id", "?"),
                    os.path.getmtime(path),
                    _tr("现金 ${:,.0f} · 持仓 {} · 成交 {}").format(
                        float(d.get("cash", 0)),
                        len([p for p in (d.get("positions") or {}).values() if p.get("qty")]),
                        len(d.get("trades") or []))))
    out.sort(key=lambda r: -r[3])
    return out


def load_backup(path: str) -> Account | None:
    try:
        with open(path, encoding="utf-8") as f:
            return Account.from_dict(json.load(f))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def export_account(acc: Account, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(acc.to_dict(), f, ensure_ascii=False, indent=1)
