"""英文翻译表。key 是中文原文, 按来源模块拆成几个文件, 在这里合并。

必须显式 import 每个子模块 —— 用 pkgutil 动态扫描的话, PyInstaller 打包时
看不见它们, exe 里就全是中文。

新加界面文字时: 代码里写 _tr("中文"), 然后在对应的 en_*.py 里加一条译文。
tools/check_lang.py 会检查漏翻、占位符不一致、残留中文。
"""
from . import (en_core, en_library, en_main, en_main2, en_options, en_options_ui,
               en_research_ui, en_strategy, en_strategy_ui)

EN: dict = {}
for _m in (en_core, en_strategy, en_library, en_options, en_main, en_main2,
           en_strategy_ui, en_research_ui, en_options_ui):
    EN.update(_m.EN)
