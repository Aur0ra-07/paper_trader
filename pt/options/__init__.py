"""期权模块: 实时期权链、Black-Scholes 定价与希腊字母、期权交易与到期处理。

数据源做了抽象 (chain.OptionDataSource), 现在用 Yahoo 免费链;
以后要接 Polygon / ORATS 这类付费源做回测, 实现同一个接口即可。
"""
