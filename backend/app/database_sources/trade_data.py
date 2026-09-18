from __future__ import annotations


DATABASE_ID = "trade_data"

SYNONYMS: dict[str, list[str]] = {
    "trade_data.stock_daily.symbol": ["股票代码", "证券代码", "代码"],
    "trade_data.stock_daily.stock_name": ["股票名称", "证券名称", "名称"],
    "trade_data.stock_daily.trade_date": ["交易日期", "交易日", "日期"],
    "trade_data.stock_daily.close": ["收盘价", "收盘价格"],
    "trade_data.stock_daily.volume": ["成交量", "交易量"],
    "trade_data.stock_daily.turnover": ["成交额", "交易额"],
    "trade_data.stock_daily.total_market_cap": ["总市值", "市值"],
    "trade_data.stock_daily.float_market_cap": ["流通市值"],
    "trade_data.stock_daily.industry_level_1": ["一级行业", "申万一级行业"],
    "trade_data.stock_daily.industry_level_2": ["二级行业", "申万二级行业"],
    "trade_data.stock_daily.industry_level_3": ["三级行业", "申万三级行业"],
    "trade_data.index_daily.index_code": ["指数代码", "大盘代码", "代码"],
    "trade_data.index_daily.trade_date": ["交易日期", "交易日", "日期"],
    "trade_data.index_daily.open": ["开盘点位", "开盘指数", "开盘价"],
    "trade_data.index_daily.high": ["最高点位", "最高指数", "最高价"],
    "trade_data.index_daily.low": ["最低点位", "最低指数", "最低价"],
    "trade_data.index_daily.close": ["收盘点位", "收盘指数", "收盘价"],
    "trade_data.index_daily.volume": ["指数成交量", "成交量", "交易量"],
    "trade_data.index_daily.turnover": ["指数成交额", "成交额", "交易额"],
}
