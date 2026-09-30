"""界面语言。

用法: 界面上要显示的中文一律写成 `_tr("中文原文")`。中文原文本身就是 key,
英文表 (pt/lang/) 查不到时原样返回中文 —— 漏翻只会显示中文, 不会崩。

`N_("中文")` 只做标记、不翻译: 用在**要存盘或当查找键**的名字上 (比如组合
预设名存进 autotrader.json)。存盘的永远是中文原文, 显示时再 `_tr()`, 这样
切换语言不会让旧配置对不上。

语言在启动时读一次, 切换要重启 —— 整套界面热切换很容易漏掉某个控件。
为了测试可以用环境变量 PT_LANG=en / zh 覆盖设置。

**不要在 config.py 里用 `_tr`**: 那里有数据文件夹名 (模拟炒股), 翻译了就会去
另一个文件夹找账户, 等于数据丢失。config 也不能 import 本模块 (会循环导入)。
"""
from __future__ import annotations

import json
import os

from .config import SETTINGS_PATH

LANGS = (("en", "English"), ("zh", "中文"))
DEFAULT = "en"


def _load_lang() -> str:
    env = os.environ.get("PT_LANG", "").strip().lower()
    if env in dict(LANGS):
        return env
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            v = json.load(f).get("language", DEFAULT)
    except (OSError, ValueError, AttributeError):
        v = DEFAULT
    return v if v in dict(LANGS) else DEFAULT


LANG = _load_lang()

from .lang import EN as _EN  # noqa: E402  (放在 LANG 之后, 表本身不依赖语言)


def _tr(s: str) -> str:
    """把界面上的中文翻成当前语言。"""
    if LANG == "zh":
        return s
    return _EN.get(s, s)


def N_(s: str) -> str:
    """只标记给提取器, 不翻译。见模块说明。"""
    return s
