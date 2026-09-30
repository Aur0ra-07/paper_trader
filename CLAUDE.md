# Paper Trader — 给 Claude Code 的项目说明

美股模拟交易终端。**真实行情（Yahoo Finance 公开接口）+ 虚拟资金**，不接任何真实券商，不涉及真实资金。

## 最常见的任务：给调仓建议

用户会在软件里点「导出简报」，然后让你读文件给建议。流程：

1. 读 `data/ai/briefing.md` —— 里面有账户状态、持仓、行情、技术指标、风控约束
2. 把建议写进 `data/ai/decisions.json`，**覆盖**原文件
3. 用户回到软件的【策略 → AI 建议】页点「读取 AI 建议」，逐条确认后执行

`decisions.json` 的格式（`briefing.md` 末尾也有一份）：

```json
{
  "generated_at": "2026-09-13T18:00:00",
  "note": "一句话总结本次调仓思路",
  "decisions": [
    {
      "symbol": "AAPL",
      "action": "BUY",
      "qty": 50,
      "order_type": "MARKET",
      "limit_price": 0,
      "confidence": 0.7,
      "reason": "引用 briefing 里的具体指标数字"
    }
  ]
}
```

写建议时注意：

- `action` 只能是 `BUY` / `SELL` / `SHORT` / `COVER`
- **只用 briefing 里的数据判断**，不要臆造行情；软件会做二次校验（持仓够不够、购买力够不够、代码存不存在），写错会被拦下
- `reason` 要引用具体数字，不写"看起来不错"这类空话
- 不需要调仓就返回空的 `decisions` 数组，在 `note` 里说明为什么按兵不动
- 这是模拟盘练习，不是真实投资建议；最终是否执行由用户决定

## 代码结构

```
main.py                    入口
pt/config.py               设置、佣金与规费模型
pt/i18n.py                 界面语言: _tr() 翻译 / N_() 只标记 (见不变量 18)
pt/lang/                   英文翻译表, key 是中文原文
pt/market.py               行情客户端（报价 / K线 / 搜索 / 榜单）
pt/universe.py             板块分组代码表
pt/models.py               订单 / 成交 / 持仓 / 账户
pt/engine.py               撮合引擎、盈亏记账、Reg T 与 PDT 风控
pt/storage.py              账户 JSON 持久化
pt/strategy/indicators.py  技术指标（纯 Python，按下标对齐）
pt/strategy/library.py     策略库，每个策略只回答"想持有什么方向"(+1/0/-1)
pt/strategy/backtest.py    事件驱动回测
pt/strategy/rotation.py    横截面动量轮动（多标的，等权买入持有为基准）
pt/strategy/portfolio.py   组合引擎：多收益来源按权重拼合、再平衡、相关性、风险平价
pt/strategy/optimizer.py   网格搜索 + 训练/验证切分
pt/strategy/autotrader.py  自动交易执行 + 风控
pt/strategy/briefing.py    本文件描述的 AI 协作桥
pt/options/pricing.py      Black-Scholes、隐含波动率反解、希腊字母、概率
pt/options/models.py       OCC 代码解析、期权合约/持仓/订单/成交
pt/options/chain.py        期权链数据源（抽象接口 + Yahoo 实现）
pt/options/engine.py       期权交易、卖方保证金、到期行权与指派
pt/ui/                     PyQt6 界面
data/                      账户、设置、AI 文件（自动生成，不要提交）
```

## 改代码时必须守住的不变量

1. **回测不许有未来函数。** 信号在第 `i` 根收盘算出，第 `i+1` 根开盘成交。`indicators.py`
   里所有函数返回与输入等长、前面补 `None` 的列表，`indicator[i]` 只能用到 `<= i` 的数据。
2. **回测和实盘必须共用同一套成本模型**（`config.Settings` 的佣金 / 规费 / 滑点），
   否则回测收益没有参考价值。
3. **实盘信号只能用已收盘的 K 线**（`autotrader.signal_index`），盘中那根还在变。
4. **风控在策略之外。** 策略只返回方向，仓位上限、持仓数、止损、回撤熔断由执行层统一管。
   批量决策时额度要在批内逐条扣减，否则多个标的会各自以为额度还在。
5. 行情接口有频率限制，新增批量请求要带缓存和节流（参考 `market.screener`、`cache.py`）。
6. **杠杆回测必须模拟强平**（`settings.maintenance_margin`）和融资利息，否则净值会算出负数这种
   现实中不存在的结果。
7. **期权价格只用市场 bid/ask，不用模型价。** 实测过：用历史波动率合成的 BS 价格
   和真实成交价中位误差 24%、虚值 51%。BS 只用来算希腊字母和概率（那里用的是市场 IV，准确）。
8. **买入期权必须全额付现**（Reg T，期权没有抵押价值）；卖出期权要占保证金。
9. Yahoo 拿不到已到期合约的历史（全部 404），所以**期权回测做不了**。要做得接付费源，
   照着 `options/chain.py` 的 `OptionDataSource` 接口实现即可。
10. **K 线必须用前复权价**（`market.py` 会自动用 `adjclose` 并按比例缩放 O/H/L）。
    实测不复权会让 SPY 2005-2026 少算 306 个百分点、TLT 从 −9% 变成 +85%。
11. **自动交易有两种模式, 风控语义不同**(`autotrader.SINGLE` / `PORTFOLIO`)。
    单标的模式: 一个策略跑多只股票, 每只全仓或空仓, `max_position_pct` /
    `max_positions` / 单笔止损都生效。组合模式: 仓位由**目标权重**决定, 那几项
    不适用(组合本来就要同时拿十几只), 风控靠分散 + 回撤熔断; 也不挂单笔止损 ——
    止损卖掉后再平衡会立刻买回来, 只会来回磨损。
12. **容忍带只管再平衡, 不管建仓。** 目标权重可能比容忍带还小(比如 3.2% 配 2pp 带),
    如果建仓也走容忍带, 那些支柱永远建不上仓。
13. **轮动的选股规则只有一份**: `rotation.score_one()`, 回测的 `pick()` 和实盘的
    `live_picks()` 都调它。改这里等于同时改回测和实盘, 改完要跑等价性检验。
14. **`range="max"` 是陷阱, 别用。** 实测日线传 max 只回 405 根 —— 接口会偷偷
    降采样成月线。要全历史必须用 `market.ALL_RANGE` 哨兵, 它走 period1/period2,
    能拉到标的上市当天 (AAPL 11529 根回到 1980-12-12, SPY 8462 根回到 1993-01-29)。
    各周期实测上限见 `MarketData.RANGES`: 分钟线最多 1 个月, 60 分钟最多 2 年。
15. **行情源有兜底, 但三家的股息处理都不一样。** Yahoo 2021 年起在中国大陆不可
    访问, `MarketData` 会在 Yahoo 失败时自动切到国内源 (`pt/eastmoney.py`)。
    国内源**以腾讯为主, 东财只补腾讯做不到的**(超 8 年日线 / 分钟线)。

    实测 5 年总收益 vs Yahoo:
        GLD(不分红) 腾讯与 Yahoo 完全一致 | SPY 少 12pp | TLT 少 10pp | EFA 少 22pp
    腾讯对美股**完全不做股息复权**(qfq/hfq/不传参数结果相同);
    东财做但算法不同, 方向相反(XLU 2005-2026 多 41pp)。

    **实时报价三家完全一致**(实测偏差 0.000%)。所以 Yahoo 是基准, 国内源只是
    降级备份; PDF 里所有数字都是 Yahoo 口径。切换时状态栏会提示, 别把提示去掉。
    东财 K 线要间隔 1 秒, 且 `beg=0` 时会无视 `lmt` 直接返回全历史。
16. 报告回测结论时要给**分布**不是单个数字：用 `backtest.rolling_windows()` 给出中位数和最差情况，
   只报"最好"那一列是误导。
17. **用户账户数据神圣不可侵犯。** 2026-09-14 `tools/build_exe.py` 的
    `shutil.rmtree("dist")` 把一个账户的全部成交记录删干净了，而且一声不吭。
    从那以后定了四条：
    - 冻结运行时数据在 `%LOCALAPPDATA%\模拟炒股\data\`，**不在 exe 旁边**。
      放 exe 旁边有两条必丢路径：解压新版覆盖、重新打包 `--clean`。
      旧位置有数据的话 `config._app_dir()` 首次启动自动迁移。
    - `save_account` 要 `fsync` 再 `os.replace`。只改名不刷盘的话，硬重启会拿到
      一个改好名的空文件。
    - 每 20 分钟自动快照到 `data/backups/`，48 小时内全留、更早的每天一份。
      以前只在「重置/删除」前备份，等于平时完全没有兜底。
    - **读不出来绝不能默默新建账户。** `bootstrap()` 先翻备份恢复并置
      `RECOVERED_FROM`；坏文件改名成 `.corrupt-<时间>` 保留并记进 `LOAD_FAILURES`，
      启动时弹窗告诉用户。默默开新账户 = 数据没了还让人以为一切正常。
    任何碰 `dist/` 的脚本都必须先抢救 `data/`（见 `build_exe._rescue_data`）。
18. **界面文字双语，默认英文。** 所有显示给用户的中文写成 `_tr("中文原文")`，
    中文原文就是 key，译文在 `pt/lang/en_*.py`。加了界面文字就跑
    `python tools/check_lang.py`（查漏翻、占位符不一致、真跑一遍 `.format()`）。
    - **`config.py` 不许用 `_tr`**：那里有数据文件夹名 `模拟炒股`，翻译了就会去另一个
      文件夹找账户（又一次数据丢失）。config 也不能 import i18n（循环导入）。
    - **要存盘或当查找键的名字用 `N_("中文")`**，只标记不翻译，显示时再 `_tr()`。
      例子：组合预设名存进 `autotrader.json`、默认账户名 `DEFAULT_ACCOUNT_NAME`。
      否则切换语言后旧配置按名字就找不到了。下拉框用 `addItem(_tr(name), name)`，
      存 `currentData()` 不存 `currentText()`。
    - **不要拿显示文字做逻辑判断**。`options/engine.stats()` 按 note 里的关键词识别
      作废/交割，所以 `EXPIRED_MARKS` / `DELIVER_MARKS` 中英文都列了，
      英文译文必须含 `expired worthless` / `deliver`（`check_lang.py` 会查）。
    - 不能用 `t` / `_` / `tr` 当函数名：代码里当变量用了几百次，会撞名。
    - 一条译文里要调语序就全部用显式编号 `{0}{1}`，Python 不许和 `{}` 混用。
    - 语言启动时读一次（`i18n.LANG`），切换要重启；测试用 `PT_LANG=en/zh` 覆盖。
    - 设置页的「Language / 语言」那一组**故意不翻译**，否则切错语言的人找不到怎么切回来。
    - 存盘的历史数据（成交 note、自动交易日志、用户起的账户名）不翻译，
      只有新产生的记录跟随当前语言。

## 打包发布

```bash
python tools/build_exe.py      # -> dist/模拟炒股/  (免安装, 双击即开, 无黑窗口)
```

打包相关的坑, 改动前先看:

- **`sys.stderr` 在 `--windowed` 和 `pythonw` 下是 `None`。** 任何往 stderr 写东西的
  代码都会炸, 包括异常处理器自己 —— 结果是用户看到程序无声闪退。`main.py` 的
  `_excepthook` 已经处理了, 并会把完整堆栈落到 `data/错误日志.txt`。
- **`config.APP_DIR` 冻结运行时指向 `%LOCALAPPDATA%\模拟炒股\`**, 不是 `__file__`,
  也**不是 exe 所在目录**(那样重新打包/解压新版都会把数据删掉, 见不变量 17)。
- **打包前必须先抢救 `dist/<名字>/data/`**。`build_exe.main()` 开头的
  `_rescue_data()` 干这件事, 它必须在 `rmtree("dist")` **之前**调用。
- `tools/netcheck.py` 是行情连通性自检, 只用标准库, 单独打包只有 8MB。
  目标机器网络能不能用行情源, 先用它测, 别猜。

## 常用命令

```bash
python main.py          # 启动（Windows 上也可双击 启动模拟炒股.bat）
```

## 验证工具

`pt/strategy/validation.py` 提供 `walk_forward()` / `deflated_sharpe()` /
`probabilistic_sharpe()`。

改策略参数之前先读一下这三个函数在算什么。样本内把夏普调高很容易，
难的是证明那不是噪声：

- `walk_forward()` —— 只用训练段选参数，在没见过的测试段上评估，滚动推进
- `deflated_sharpe()` —— 试了 N 组参数再挑最好的那组，这个函数回答
  「扣掉挑选偏差之后，真实夏普 > 0 的概率还剩多少」
- 注意 DSR 公式里所有夏普都是**未年化**的，传年化值进去结果是错的

如果一个改动能让样本内夏普明显变好但 DSR 没动，那多半是在调噪声。
