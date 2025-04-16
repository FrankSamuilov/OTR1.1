import os
import time
import math
import numpy as np
import pandas as pd
import datetime
from binance.client import Client
from config import CONFIG, VERSION
from data_module import get_historical_data
from indicators_module import calculate_optimized_indicators, get_smc_trend_and_duration, find_swing_points, \
    calculate_fibonacci_retracements
from position_module import load_positions, get_total_position_exposure, calculate_order_amount, \
    adjust_position_for_market_change
from logger_setup import get_logger
from concurrent.futures import ThreadPoolExecutor, as_completed
from trade_module import get_max_leverage, get_precise_quantity, format_quantity
from quality_module import calculate_quality_score, detect_pattern_similarity, adjust_quality_for_similarity
from pivot_points_module import calculate_pivot_points, analyze_pivot_point_strategy
from advanced_indicators import calculate_smi, calculate_stochastic, calculate_parabolic_sar
from smc_enhanced_prediction import enhanced_smc_prediction, multi_timeframe_smc_prediction
from risk_management import adaptive_risk_management
from integration_module import calculate_enhanced_indicators, comprehensive_market_analysis, generate_trade_recommendation
from logger_utils import Colors, print_colored
import datetime
import time
from integration_module import calculate_enhanced_indicators, generate_trade_recommendation
from multi_timeframe_module import MultiTimeframeCoordinator
from EntryWaitingManager import EntryWaitingManager
# 导入集成模块（这是最简单的方法，因为它整合了所有其他模块的功能）
from integration_module import (
    calculate_enhanced_indicators,
    comprehensive_market_analysis,
    generate_trade_recommendation
)
import os
import json
import time
import datetime
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns


# 在文件开头导入所需的模块后，添加这个类定义
class EnhancedTradingBot:
    def __init__(self, api_key: str, api_secret: str, config: dict):
        print("初始化 EnhancedTradingBot...")
        self.config = config
        self.client = Client(api_key, api_secret)
        self.logger = get_logger()
        self.trade_cycle = 0
        self.open_positions = []  # 存储持仓信息
        self.api_request_delay = 0.5  # API请求延迟以避免限制
        self.historical_data_cache = {}  # 缓存历史数据
        self.quality_score_history = {}  # 存储质量评分历史
        self.similar_patterns_history = {}  # 存储相似模式历史
        self.hedge_mode_enabled = True  # 默认启用双向持仓
        self.dynamic_take_profit = 0.0175  # 默认2.5%止盈
        self.dynamic_stop_loss = -0.0125  # 默认2.0%止损
        self.market_bias = "neutral"  # 市场偏向：bullish/bearish/neutral
        self.trend_priority = False  # 是否优先考虑趋势明确的交易对
        self.strong_trend_symbols = []  # 趋势明确的交易对列表
        self.entry_manager = EntryWaitingManager(self)
        # 多时间框架协调器初始化
        self.mtf_coordinator = MultiTimeframeCoordinator(self.client, self.logger)
        print("✅ 多时间框架协调器初始化完成")

        # 创建日志目录
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            print(f"已创建日志目录: {log_dir}")


        # 尝试启用双向持仓模式
        try:
            position_mode = self.client.futures_get_position_mode()
            if position_mode['dualSidePosition']:
                print("双向持仓模式已启用")
                self.hedge_mode_enabled = True
            else:
                print("尝试启用双向持仓模式...")
                self.client.futures_change_position_mode(dualSidePosition=True)
                print("已启用双向持仓模式")
                self.hedge_mode_enabled = True
        except Exception as e:
            if "code=-4059" in str(e):
                print("双向持仓模式已启用，无需更改")
                self.hedge_mode_enabled = True
            else:
                print(f"⚠️ 启用双向持仓模式失败: {e}")
                self.logger.error("启用双向持仓模式失败", extra={"error": str(e)})
                self.hedge_mode_enabled = False

        print(f"初始化完成，交易对: {self.config['TRADE_PAIRS']}")



    def manage_open_positions(self):
        """管理现有持仓，使用每个持仓的特定止盈止损设置"""
        self.load_existing_positions()

        if not self.open_positions:
            self.logger.info("当前无持仓")
            return

        current_time = time.time()
        positions_to_remove = []  # 记录需要移除的持仓

        for pos in self.open_positions:
            symbol = pos["symbol"]
            position_side = pos.get("position_side", "LONG")
            entry_price = pos["entry_price"]

            # 获取当前价格
            try:
                ticker = self.client.futures_symbol_ticker(symbol=symbol)
                current_price = float(ticker['price'])
            except Exception as e:
                print(f"⚠️ 无法获取 {symbol} 当前价格: {e}")
                continue

            # 计算盈亏百分比
            if position_side == "LONG":
                profit_pct = (current_price - entry_price) / entry_price
            else:  # SHORT
                profit_pct = (entry_price - current_price) / entry_price

            # 使用持仓记录的个性化止盈止损设置，而不是全局默认值
            take_profit = pos.get("dynamic_take_profit", 0.0175)  # 使用持仓特定的止盈值，默认2.5%
            stop_loss = pos.get("stop_loss", -0.0125)  # 使用持仓特定的止损值，默认-1.75%

            profit_color = Colors.GREEN if profit_pct >= 0 else Colors.RED
            print(
                f"{symbol} {position_side}: 当前盈亏 {profit_color}{profit_pct:.2%}{Colors.RESET}, "
                f"止盈线 {take_profit:.2%}, 止损线 {stop_loss:.2%}"
            )

            # 检查是否达到止盈条件
            if profit_pct >= take_profit:
                print(f"🔔 {symbol} {position_side} 达到止盈条件 ({profit_pct:.2%} >= {take_profit:.2%})，执行平仓...")
                success, closed = self.close_position(symbol, position_side)
                if success:
                    print(f"✅ {symbol} {position_side} 止盈平仓成功!")
                    positions_to_remove.append(pos)
                    self.logger.info(f"{symbol} {position_side}止盈平仓", extra={
                        "profit_pct": profit_pct,
                        "take_profit": take_profit,
                        "entry_price": entry_price,
                        "exit_price": current_price
                    })

            # 检查是否达到止损条件
            elif profit_pct <= stop_loss:
                print(f"🔔 {symbol} {position_side} 达到止损条件 ({profit_pct:.2%} <= {stop_loss:.2%})，执行平仓...")
                success, closed = self.close_position(symbol, position_side)
                if success:
                    print(f"✅ {symbol} {position_side} 止损平仓成功!")
                    positions_to_remove.append(pos)
                    self.logger.info(f"{symbol} {position_side}止损平仓", extra={
                        "profit_pct": profit_pct,
                        "stop_loss": stop_loss,
                        "entry_price": entry_price,
                        "exit_price": current_price
                    })

        # 从持仓列表中移除已平仓的持仓
        for pos in positions_to_remove:
            if pos in self.open_positions:
                self.open_positions.remove(pos)

        # 重新加载持仓以确保数据最新
        self.load_existing_positions()


    def calculate_dynamic_order_amount(self, risk, account_balance):
        """基于风险和账户余额计算适当的订单金额"""
        # 基础订单百分比 - 默认账户的5%
        base_pct = 5.0

        # 根据风险调整订单百分比
        if risk > 0.05:  # 高风险
            adjusted_pct = base_pct * 0.6  # 减小到基础的60%
        elif risk > 0.03:  # 中等风险
            adjusted_pct = base_pct * 0.8  # 减小到基础的80%
        elif risk < 0.01:  # 低风险
            adjusted_pct = base_pct * 1.2  # 增加到基础的120%
        else:
            adjusted_pct = base_pct

        # 计算订单金额
        order_amount = account_balance * (adjusted_pct / 100)

        # 确保订单金额在合理范围内
        min_amount = 5.0  # 最小5 USDC
        max_amount = account_balance * 0.1  # 最大为账户10%

        order_amount = max(min_amount, min(order_amount, max_amount))

        print_colored(f"动态订单金额: {order_amount:.2f} USDC ({adjusted_pct:.1f}% 账户余额)", Colors.INFO)

        return order_amount

    def check_and_reconnect_api(self):
        """检查API连接并在必要时重新连接"""
        try:
            # 简单测试API连接
            self.client.ping()
            print("✅ API连接检查: 连接正常")
            return True
        except Exception as e:
            print(f"⚠️ API连接检查失败: {e}")
            self.logger.warning(f"API连接失败，尝试重新连接", extra={"error": str(e)})

            # 重试计数
            retry_count = 3
            reconnected = False

            for attempt in range(retry_count):
                try:
                    print(f"🔄 尝试重新连接API (尝试 {attempt + 1}/{retry_count})...")
                    # 重新创建客户端
                    self.client = Client(self.api_key, self.api_secret)

                    # 验证连接
                    self.client.ping()

                    print("✅ API重新连接成功")
                    self.logger.info("API重新连接成功")
                    reconnected = True
                    break
                except Exception as reconnect_error:
                    print(f"❌ 第{attempt + 1}次重连失败: {reconnect_error}")
                    time.sleep(5 * (attempt + 1))  # 指数退避

            if not reconnected:
                print("❌ 所有重连尝试失败，将在下一个周期重试")
                self.logger.error("API重连失败", extra={"attempts": retry_count})
                return False

            return reconnected

    def active_position_monitor(self, check_interval=15):
        """
        主动监控持仓，确保及时执行止盈止损，支持动态止盈止损
        """
        print(f"🔄 启动主动持仓监控（每{check_interval}秒检查一次）")

        try:
            while True:
                # 如果没有持仓，等待一段时间后再检查
                if not self.open_positions:
                    time.sleep(check_interval)
                    continue

                # 加载最新持仓
                self.load_existing_positions()

                # 当前持仓列表的副本，用于检查
                positions = self.open_positions.copy()

                for pos in positions:
                    symbol = pos["symbol"]
                    position_side = pos.get("position_side", "LONG")
                    entry_price = pos["entry_price"]

                    # 获取当前价格
                    try:
                        ticker = self.client.futures_symbol_ticker(symbol=symbol)
                        current_price = float(ticker['price'])
                    except Exception as e:
                        print(f"⚠️ 获取{symbol}价格失败: {e}")
                        continue

                    # 计算利润百分比
                    if position_side == "LONG":
                        profit_pct = (current_price - entry_price) / entry_price
                    else:  # SHORT
                        profit_pct = (entry_price - current_price) / entry_price

                    # 使用持仓特定的止盈止损设置，而不是全局默认值
                    take_profit = pos.get("dynamic_take_profit", 0.0175)  # 默认2.5%
                    stop_loss = pos.get("stop_loss", -0.0125)  # 默认-1.75%

                    # 日志记录当前状态
                    if check_interval % 60 == 0:  # 每分钟记录一次
                        print(
                            f"{symbol} {position_side}: 盈亏 {profit_pct:.2%}, 止盈 {take_profit:.2%}, 止损 {stop_loss:.2%}")

                    # 检查止盈条件
                    if profit_pct >= take_profit:
                        print(
                            f"🔔 主动监控: {symbol} {position_side} 达到止盈条件 ({profit_pct:.2%} >= {take_profit:.2%})")
                        success, closed = self.close_position(symbol, position_side)
                        if success:
                            print(f"✅ {symbol} {position_side} 止盈平仓成功: +{profit_pct:.2%}")
                            self.logger.info(f"{symbol} {position_side}主动监控止盈平仓", extra={
                                "profit_pct": profit_pct,
                                "take_profit": take_profit,
                                "entry_price": entry_price,
                                "exit_price": current_price
                            })

                    # 检查止损条件
                    elif profit_pct <= stop_loss:
                        print(
                            f"🔔 主动监控: {symbol} {position_side} 达到止损条件 ({profit_pct:.2%} <= {stop_loss:.2%})")
                        success, closed = self.close_position(symbol, position_side)
                        if success:
                            print(f"✅ {symbol} {position_side} 止损平仓成功: {profit_pct:.2%}")
                            self.logger.info(f"{symbol} {position_side}主动监控止损平仓", extra={
                                "profit_pct": profit_pct,
                                "stop_loss": stop_loss,
                                "entry_price": entry_price,
                                "exit_price": current_price
                            })

                # 等待下一次检查
                time.sleep(check_interval)
        except Exception as e:
            print(f"主动持仓监控发生错误: {e}")
            self.logger.error(f"主动持仓监控错误", extra={"error": str(e)})

    def trade(self):
        """增强版多时框架集成交易循环，包含主动持仓监控"""
        import threading

        print("启动增强版多时间框架集成交易机器人...")
        self.logger.info("增强版多时间框架集成交易机器人启动", extra={"version": "Enhanced-MTF-" + VERSION})

        # 在单独的线程中启动主动持仓监控
        monitor_thread = threading.Thread(target=self.active_position_monitor, args=(15,), daemon=True)
        monitor_thread.start()
        print("✅ 主动持仓监控已在后台启动（每15秒检查一次）")

        # 初始化API连接
        self.check_and_reconnect_api()

        while True:
            try:
                self.trade_cycle += 1
                print(f"\n======== 交易循环 #{self.trade_cycle} ========")
                current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"当前时间: {current_time}")

                # 每10个周期运行资源管理和API检查
                if self.trade_cycle % 10 == 0:
                    self.manage_resources()
                    self.check_and_reconnect_api()

                # 每5个周期分析一次市场条件
                if self.trade_cycle % 5 == 0:
                    print("\n----- 分析市场条件 -----")
                    market_conditions = self.adapt_to_market_conditions()
                    market_bias = market_conditions['market_bias']
                    print(
                        f"市场分析完成: {'看涨' if market_bias == 'bullish' else '看跌' if market_bias == 'bearish' else '中性'} 偏向")

                # 获取账户余额
                account_balance = self.get_futures_balance()
                print(f"账户余额: {account_balance:.2f} USDC")
                self.logger.info("账户余额", extra={"balance": account_balance})

                if account_balance < self.config.get("MIN_MARGIN_BALANCE", 10):
                    print(f"⚠️ 账户余额不足，最低要求: {self.config.get('MIN_MARGIN_BALANCE', 10)} USDC")
                    self.logger.warning("账户余额不足", extra={"balance": account_balance,
                                                               "min_required": self.config.get("MIN_MARGIN_BALANCE",
                                                                                               10)})
                    time.sleep(60)
                    continue

                # 管理现有持仓
                self.manage_open_positions()

                # 分析交易对并生成建议
                trade_candidates = []
                for symbol in self.config["TRADE_PAIRS"]:
                    try:
                        print(f"\n分析交易对: {symbol}")
                        # 获取基础数据
                        df = self.get_historical_data_with_cache(symbol, force_refresh=True)
                        if df is None:
                            print(f"❌ 无法获取{symbol}数据")
                            continue

                        # 使用新的信号生成函数
                        signal, quality_score = self.generate_trade_signal(df, symbol)

                        # 跳过保持信号
                        if signal == "HOLD":
                            print(f"⏸️ {symbol} 保持观望")
                            continue

                        # 检查原始信号是否为轻量级
                        is_light = False
                        # 临时获取原始信号
                        _, _, details = self.mtf_coordinator.generate_signal(symbol, quality_score)
                        raw_signal = details.get("coherence", {}).get("recommendation", "")
                        if raw_signal.startswith("LIGHT_"):
                            is_light = True
                            print_colored(f"{symbol} 检测到轻量级信号，将使用较小仓位", Colors.YELLOW)

                        # 获取当前价格
                        try:
                            ticker = self.client.futures_symbol_ticker(symbol=symbol)
                            current_price = float(ticker['price'])
                        except Exception as e:
                            print(f"❌ 获取{symbol}价格失败: {e}")
                            continue

                        # 预测未来价格
                        predicted = None
                        if "price_prediction" in details and details["price_prediction"].get("valid", False):
                            predicted = details["price_prediction"]["predicted_price"]
                        else:
                            predicted = self.predict_short_term_price(symbol, horizon_minutes=90)  # 使用90分钟预测

                        if predicted is None:
                            predicted = current_price * (1.05 if signal == "BUY" else 0.95)  # 默认5%变动

                        # 计算预期价格变动百分比
                        expected_movement = abs(predicted - current_price) / current_price * 100

                        # 如果预期变动小于2.5%，则跳过交易
                        if expected_movement < 1.75:  # 将最小要求从2.5%降低到1.75%
                            print_colored(
                                f"⚠️ {symbol}的预期价格变动({expected_movement:.2f}%)小于最低要求(1.75%)，跳过交易",
                                Colors.WARNING)
                            continue

                        # 计算风险和交易金额
                        risk = expected_movement / 100  # 预期变动作为风险指标

                        # 计算交易金额时考虑轻量级信号
                        candidate_amount = self.calculate_dynamic_order_amount(risk, account_balance)
                        if is_light:
                            candidate_amount *= 0.5  # 轻量级信号使用半仓
                            print_colored(f"{symbol} 轻量级信号，使用50%标准仓位: {candidate_amount:.2f} USDC",
                                          Colors.YELLOW)

                        # 添加到候选列表
                        candidate = {
                            "symbol": symbol,
                            "signal": signal,
                            "quality_score": quality_score,
                            "current_price": current_price,
                            "predicted_price": predicted,
                            "risk": risk,
                            "amount": candidate_amount,
                            "is_light": is_light,
                            "expected_movement": expected_movement
                        }

                        trade_candidates.append(candidate)

                        print_colored(
                            f"候选交易: {symbol} {signal}, "
                            f"质量评分: {quality_score:.2f}, "
                            f"预期波动: {expected_movement:.2f}%, "
                            f"下单金额: {candidate_amount:.2f} USDC",
                            Colors.GREEN if signal == "BUY" else Colors.RED
                        )

                    except Exception as e:
                        self.logger.error(f"处理{symbol}时出错: {e}")
                        print(f"❌ 处理{symbol}时出错: {e}")

                # 按质量评分排序候选交易
                trade_candidates.sort(key=lambda x: x["quality_score"], reverse=True)

                # 显示详细交易计划
                if trade_candidates:
                    print("\n==== 详细交易计划 ====")
                    for idx, candidate in enumerate(trade_candidates, 1):
                        symbol = candidate["symbol"]
                        signal = candidate["signal"]
                        quality = candidate["quality_score"]
                        current = candidate["current_price"]
                        predicted = candidate["predicted_price"]
                        amount = candidate["amount"]
                        is_light = candidate["is_light"]
                        expected_movement = candidate["expected_movement"]

                        side_color = Colors.GREEN if signal == "BUY" else Colors.RED
                        position_type = "轻仓位" if is_light else "标准仓位"

                        print(f"\n{idx}. {symbol} - {side_color}{signal}{Colors.RESET} ({position_type})")
                        print(f"   质量评分: {quality:.2f}")
                        print(f"   当前价格: {current:.6f}, 预测价格: {predicted:.6f}")
                        print(f"   预期波动: {expected_movement:.2f}%")
                        print(f"   下单金额: {amount:.2f} USDC")
                else:
                    print("\n本轮无交易候选")

                # 执行交易
                executed_count = 0
                max_trades = min(self.config.get("MAX_PURCHASES_PER_ROUND", 3), len(trade_candidates))

                for candidate in trade_candidates:
                    if executed_count >= max_trades:
                        break

                    symbol = candidate["symbol"]
                    signal = candidate["signal"]
                    amount = candidate["amount"]
                    quality_score = candidate["quality_score"]
                    is_light = candidate["is_light"]

                    print(f"\n🚀 执行交易: {symbol} {signal}, 金额: {amount:.2f} USDC{' (轻仓位)' if is_light else ''}")

                    # 计算适合的杠杆水平
                    leverage = self.calculate_leverage_from_quality(quality_score)
                    if is_light:
                        # 轻仓位降低杠杆
                        leverage = max(1, int(leverage * 0.7))
                        print_colored(f"轻仓位降低杠杆至 {leverage}倍", Colors.YELLOW)

                    # 执行交易
                    if self.place_futures_order_usdc(symbol, signal, amount, leverage):
                        executed_count += 1
                        print(f"✅ {symbol} {signal} 交易成功")
                    else:
                        print(f"❌ {symbol} {signal} 交易失败")

                # 显示持仓卖出预测
                self.display_position_sell_timing()

                # 打印交易循环总结
                print(f"\n==== 交易循环总结 ====")
                print(f"分析交易对: {len(self.config['TRADE_PAIRS'])}个")
                print(f"交易候选: {len(trade_candidates)}个")
                print(f"执行交易: {executed_count}个")

                # 循环间隔
                sleep_time = 60
                print(f"\n等待 {sleep_time} 秒进入下一轮...")
                time.sleep(sleep_time)

            except KeyboardInterrupt:
                print("\n用户中断，退出程序")
                self.logger.info("用户中断，程序结束")
                break
            except Exception as e:
                self.logger.error(f"交易循环异常: {e}")
                print(f"错误: {e}")
                time.sleep(30)

    def is_near_resistance(self, price, swing_highs, fib_levels, threshold=0.01):
        """检查价格是否接近阻力位"""
        # 检查摆动高点
        for high in swing_highs:
            if abs(price - high) / price < threshold:
                return True

        # 检查斐波那契阻力位
        if fib_levels and len(fib_levels) >= 3:
            for level in fib_levels:
                if abs(price - level) / price < threshold:
                    return True

        return False

    def adapt_to_market_conditions(self):
        """根据市场条件动态调整交易参数 - 改进版，增强健壮性"""
        print("\n===== 市场条件分析与参数适配 =====")

        # 初始化默认值，确保变量始终被定义
        avg_volatility = 1.0  # 默认波动性
        avg_trend_strength = 20.0  # 默认趋势强度
        market_bias = "neutral"  # 默认市场偏向

        # 分析当前市场波动性
        volatility_levels = {}
        trend_strengths = {}
        market_sentiment_score = 0.0
        sentiment_factors = 0
        btc_price_change = None

        # 尝试获取BTC数据
        btc_df = None
        try:
            # 尝试获取BTC数据，但不依赖它
            btc_df = self.get_btc_data()
            print("✅ 成功尝试获取BTC数据")
        except Exception as e:
            print(f"⚠️ BTC数据获取失败，将使用默认市场情绪: {e}")
            # 继续执行，使用默认值

        # 分析各交易对的波动性和趋势强度
        try:
            for symbol in self.config["TRADE_PAIRS"]:
                df = self.get_historical_data_with_cache(symbol, force_refresh=True)
                if df is not None and 'close' in df.columns and len(df) > 20:
                    # 计算波动性（当前ATR相对于历史的比率）
                    if 'ATR' in df.columns:
                        current_atr = df['ATR'].iloc[-1]
                        avg_atr = df['ATR'].rolling(20).mean().iloc[-1]
                        volatility_ratio = current_atr / avg_atr if avg_atr > 0 else 1.0
                        volatility_levels[symbol] = volatility_ratio

                        # 检查趋势强度
                        if 'ADX' in df.columns:
                            adx = df['ADX'].iloc[-1]
                            trend_strengths[symbol] = adx
        except Exception as e:
            print(f"⚠️ 分析波动性和趋势强度时出错: {e}")

        # 计算整体市场波动性
        if volatility_levels:
            avg_volatility = sum(volatility_levels.values()) / len(volatility_levels)
            print(f"📈 平均市场波动性: {avg_volatility:.2f}x (1.0为正常水平)")
        else:
            print(f"📈 使用默认市场波动性: {avg_volatility:.2f}x")

        # 计算整体趋势强度
        if trend_strengths:
            avg_trend_strength = sum(trend_strengths.values()) / len(trend_strengths)
            print(f"📏 平均趋势强度(ADX): {avg_trend_strength:.2f} (>25为强趋势)")
        else:
            print(f"📏 使用默认趋势强度(ADX): {avg_trend_strength:.2f}")

        # 使用固定的止盈止损设置，不依赖市场条件
        self.dynamic_take_profit = 0.0175  # 固定1.75%止盈
        self.dynamic_stop_loss = -0.0125  # 固定1.25%止损
        print(f"ℹ️ 使用固定止盈1.75%，止损1.25%")

        # 保留市场情绪代码，但使用默认值
        self.market_bias = market_bias
        print(f"📊 市场情绪: {market_bias} (暂时使用默认值)")

        return {
            "volatility": avg_volatility,  # 确保返回已定义的值
            "trend_strength": avg_trend_strength,
            "btc_change": btc_price_change,
            "take_profit": self.dynamic_take_profit,
            "stop_loss": self.dynamic_stop_loss,
            "market_bias": self.market_bias
        }

    def is_near_support(self, price, swing_lows, fib_levels, threshold=0.01):
        """检查价格是否接近支撑位"""
        # 检查摆动低点
        for low in swing_lows:
            if abs(price - low) / price < threshold:
                return True

        # 检查斐波那契支撑位
        if fib_levels and len(fib_levels) >= 3:
            for level in fib_levels:
                if abs(price - level) / price < threshold:
                    return True

        return False

    def place_hedge_orders(self, symbol, primary_side, quality_score):
        """
        根据质量评分和信号放置订单，支持双向持仓 - 修复版
        """
        account_balance = self.get_futures_balance()

        if account_balance < self.config.get("MIN_MARGIN_BALANCE", 10):
            self.logger.warning(f"账户余额不足，无法交易: {account_balance} USDC")
            return False

        # 计算下单金额，确保不超过账户余额的5%
        order_amount = account_balance * 0.05
        print(f"📊 账户余额: {account_balance} USDC, 下单金额: {order_amount:.2f} USDC (5%)")

        # 双向持仓模式
        if primary_side == "BOTH":
            # 质量评分在中间区域时采用双向持仓
            if 4.0 <= quality_score <= 6.0:
                # 使用6:4比例分配多空仓位
                long_ratio = 0.6
                short_ratio = 0.4

                long_amount = order_amount * long_ratio
                short_amount = order_amount * short_ratio

                print(f"🔄 执行双向持仓 - 多头: {long_amount:.2f} USDC, 空头: {short_amount:.2f} USDC")

                # 计算每个方向的杠杆
                long_leverage = self.calculate_leverage_from_quality(quality_score)
                short_leverage = max(1, long_leverage - 2)  # 空头杠杆略低

                # 先执行多头订单
                long_success = self.place_futures_order_usdc(symbol, "BUY", long_amount, long_leverage)
                time.sleep(1)
                # 再执行空头订单
                short_success = self.place_futures_order_usdc(symbol, "SELL", short_amount, short_leverage)

                return long_success or short_success
            else:
                # 偏向某一方向
                side = "BUY" if quality_score > 5.0 else "SELL"
                leverage = self.calculate_leverage_from_quality(quality_score)
                return self.place_futures_order_usdc(symbol, side, order_amount, leverage)

        elif primary_side in ["BUY", "SELL"]:
            # 根据评分调整杠杆倍数
            leverage = self.calculate_leverage_from_quality(quality_score)
            return self.place_futures_order_usdc(symbol, primary_side, order_amount, leverage)
        else:
            self.logger.warning(f"{symbol}未知交易方向: {primary_side}")
            return False

    def get_futures_balance(self):
        """获取USDC期货账户余额"""
        try:
            assets = self.client.futures_account_balance()
            for asset in assets:
                if asset["asset"] == "USDC":
                    return float(asset["balance"])
            return 0.0
        except Exception as e:
            self.logger.error(f"获取期货余额失败: {e}")
            return 0.0

    def get_historical_data_with_cache(self, symbol, interval="15m", limit=200, force_refresh=False):
        """获取历史数据，使用缓存减少API调用 - 改进版"""
        cache_key = f"{symbol}_{interval}_{limit}"
        current_time = time.time()

        # 更频繁刷新缓存 - 减少到5分钟
        cache_ttl = 300  # 5分钟

        # 对于长时间运行的会话，每小时强制刷新一次
        hourly_force_refresh = self.trade_cycle % 12 == 0  # 假设每5分钟一个周期

        # 检查缓存是否存在且有效
        if not force_refresh and not hourly_force_refresh and cache_key in self.historical_data_cache:
            cache_item = self.historical_data_cache[cache_key]
            if current_time - cache_item['timestamp'] < cache_ttl:
                self.logger.info(f"使用缓存数据: {symbol}")
                return cache_item['data']

        # 获取新数据
        try:
            df = get_historical_data(self.client, symbol)
            if df is not None and not df.empty:
                # 缓存数据
                self.historical_data_cache[cache_key] = {
                    'data': df,
                    'timestamp': current_time
                }
                self.logger.info(f"获取并缓存新数据: {symbol}")
                return df
            else:
                self.logger.warning(f"无法获取{symbol}的数据")
                return None
        except Exception as e:
            self.logger.error(f"获取{symbol}历史数据失败: {e}")
            return None

    def predict_short_term_price(self, symbol, horizon_minutes=60, environment=None):
        """考虑市场环境的价格预测"""
        df = self.get_historical_data_with_cache(symbol)
        if df is None or df.empty or len(df) < 20:
            return None

        try:
            # 计算指标
            df = calculate_optimized_indicators(df)

            # 如果未提供环境，则进行分类
            if environment is None:
                environment = classify_market_environment(df)

            # 根据环境调整预测方法
            if environment in ["STRONG_TREND", "TREND"]:
                # 趋势市场使用线性回归，更远的预测
                multiplier = self.config.get("TREND_PREDICTION_MULTIPLIER", 25)  # 更大的乘数

                window_length = min(self.config.get("PREDICTION_WINDOW", 60), len(df))
                window = df['close'].tail(window_length)
                smoothed = window.rolling(window=3, min_periods=1).mean().bfill()

                x = np.arange(len(smoothed))
                slope, intercept = np.polyfit(x, smoothed, 1)

                current_price = smoothed.iloc[-1]
                candles_needed = horizon_minutes / 15.0

                predicted_price = current_price + slope * candles_needed * multiplier

            elif environment == "RANGING":
                # 震荡市场使用均值回归预测
                mean_price = df['close'].tail(20).mean()
                current_price = df['close'].iloc[-1]

                # 均值回归: 向均值移动25%的距离
                reversion_rate = 0.25
                predicted_price = current_price + (mean_price - current_price) * reversion_rate

            elif environment == "ACCUMULATION":
                # 积累期，预测可能的突破方向
                bb_width = ((df['BB_Upper'].iloc[-1] - df['BB_Lower'].iloc[-1]) /
                            df['BB_Middle'].iloc[-1]) if all(x in df.columns for x in
                                                             ['BB_Upper', 'BB_Lower', 'BB_Middle']) else 0.1

                if bb_width < 0.03:  # 极窄带宽，可能即将突破
                    # 检查量能变化预测突破方向
                    vol_change = df['volume'].pct_change(5).iloc[-1]

                    current_price = df['close'].iloc[-1]
                    bb_middle = df['BB_Middle'].iloc[-1]

                    if vol_change > 0.3:  # 成交量增加30%
                        # 可能是突破信号，预测向上或向下突破
                        if current_price > bb_middle:
                            # 价格在中轨上方，预测上突破
                            predicted_price = df['BB_Upper'].iloc[-1] * 1.05
                        else:
                            # 价格在中轨下方，预测下突破
                            predicted_price = df['BB_Lower'].iloc[-1] * 0.95
                    else:
                        # 无明确突破迹象，预测小幅波动
                        predicted_price = current_price * (1 + np.random.uniform(-0.01, 0.01))
                else:
                    # 常规积累期，预测区间内波动
                    current_price = df['close'].iloc[-1]
                    predicted_price = current_price * (1 + np.random.uniform(-0.02, 0.02))

            else:  # WEAK_TREND或其他
                # 使用默认预测方法但降低倍增因子
                window_length = min(self.config.get("PREDICTION_WINDOW", 40), len(df))
                window = df['close'].tail(window_length)
                smoothed = window.rolling(window=3, min_periods=1).mean().bfill()

                x = np.arange(len(smoothed))
                slope, intercept = np.polyfit(x, smoothed, 1)

                current_price = smoothed.iloc[-1]
                candles_needed = horizon_minutes / 15.0
                multiplier = self.config.get("PREDICTION_MULTIPLIER", 10)  # 默认倍增因子

                predicted_price = current_price + slope * candles_needed * multiplier

            # 确保预测有意义
            current_price = df['close'].iloc[-1]

            # 根据环境限制预测幅度
            if environment == "RANGING":
                # 震荡市场预测波动有限
                max_change = 0.03  # 最大3%变化
            elif environment == "ACCUMULATION":
                # 积累期可能突破，允许更大变化
                max_change = 0.08  # 最大8%变化
            elif environment == "STRONG_TREND":
                # 强趋势，允许更大幅度
                max_change = 0.15  # 最大15%变化
            else:
                # 其他情况
                max_change = 0.05  # 最大5%变化

            # 限制在合理范围内
            max_price = current_price * (1 + max_change)
            min_price = current_price * (1 - max_change)
            predicted_price = max(min(predicted_price, max_price), min_price)

            return predicted_price
        except Exception as e:
            self.logger.error(f"{symbol} 价格预测失败: {e}")
            return None

    def manage_resources(self):
        """定期管理和清理资源，防止内存泄漏"""
        # 启动时间
        if not hasattr(self, 'resource_management_start_time'):
            self.resource_management_start_time = time.time()
            return

        # 当前内存使用统计
        import psutil
        process = psutil.Process(os.getpid())
        memory_usage = process.memory_info().rss / 1024 / 1024  # 转换为MB

        # 日志记录内存使用
        print(f"ℹ️ 当前内存使用: {memory_usage:.2f} MB")
        self.logger.info(f"内存使用情况", extra={"memory_mb": memory_usage})

        # 限制缓存大小
        if len(self.historical_data_cache) > 50:
            # 删除最老的缓存
            oldest_keys = sorted(
                self.historical_data_cache.keys(),
                key=lambda k: self.historical_data_cache[k]['timestamp']
            )[:10]

            for key in oldest_keys:
                del self.historical_data_cache[key]

            print(f"🧹 清理了{len(oldest_keys)}个历史数据缓存项")
            self.logger.info(f"清理历史数据缓存", extra={"cleaned_items": len(oldest_keys)})

        # 限制持仓历史记录大小
        if hasattr(self, 'position_history') and len(self.position_history) > 1000:
            self.position_history = self.position_history[-1000:]
            self._save_position_history()
            print(f"🧹 持仓历史记录裁剪至1000条")
            self.logger.info(f"裁剪持仓历史记录", extra={"max_records": 1000})

        # 重置一些累积的统计数据
        if self.trade_cycle % 100 == 0:
            self.quality_score_history = {}
            self.similar_patterns_history = {}
            print(f"🔄 重置质量评分历史和相似模式历史")
            self.logger.info(f"重置累积统计数据")

        # 运行垃圾回收
        import gc
        collected = gc.collect()
        print(f"♻️ 垃圾回收完成，释放了{collected}个对象")

        # 计算运行时间
        run_hours = (time.time() - self.resource_management_start_time) / 3600
        print(f"⏱️ 机器人已运行: {run_hours:.2f}小时")

    def generate_trade_signal(self, df, symbol):
        """生成考虑市场环境的交易信号"""
        if df is None or len(df) < 20:
            return "HOLD", 0

        try:
            # 计算指标
            df = calculate_optimized_indicators(df)
            if df is None or df.empty:
                return "HOLD", 0

            # 1. 分类市场环境
            environment = self.classify_market_environment(df)
            print_colored(f"{symbol} 当前市场环境: {environment}", Colors.BLUE + Colors.BOLD)

            # 2. 根据环境选择适合的指标和权重
            indicator_signals = {}

            # ===== 震荡市场优先指标 =====
            if environment == "RANGING" or environment == "ACCUMULATION":
                # RSI信号(震荡市场的主要指标)
                if 'RSI' in df.columns:
                    rsi = df['RSI'].iloc[-1]
                    if rsi < 30:
                        indicator_signals["RSI"] = {"signal": "BUY", "strength": 0.8, "value": rsi}
                        print_colored(f"RSI: {rsi:.2f} - 超卖区域，看涨信号", Colors.GREEN)
                    elif rsi > 70:
                        indicator_signals["RSI"] = {"signal": "SELL", "strength": 0.8, "value": rsi}
                        print_colored(f"RSI: {rsi:.2f} - 超买区域，看跌信号", Colors.RED)
                    else:
                        indicator_signals["RSI"] = {"signal": "NEUTRAL", "strength": 0.3, "value": rsi}
                        print_colored(f"RSI: {rsi:.2f} - 中性区域", Colors.GRAY)

                # 布林带信号
                if all(x in df.columns for x in ['BB_Upper', 'BB_Lower', 'BB_Middle']):
                    close = df['close'].iloc[-1]
                    upper = df['BB_Upper'].iloc[-1]
                    lower = df['BB_Lower'].iloc[-1]
                    middle = df['BB_Middle'].iloc[-1]

                    bb_position = (close - lower) / (upper - lower)

                    if close > upper * 0.98:
                        if environment == "RANGING":
                            indicator_signals["Bollinger"] = {"signal": "SELL", "strength": 0.7}
                            print_colored(f"布林带: 价格接近上轨 ({bb_position:.2f})，震荡市场卖出信号", Colors.RED)
                        elif environment == "ACCUMULATION":
                            indicator_signals["Bollinger"] = {"signal": "BUY", "strength": 0.5}
                            print_colored(f"布林带: 价格突破上轨 ({bb_position:.2f})，积累期潜在突破", Colors.GREEN)
                    elif close < lower * 1.02:
                        if environment == "RANGING":
                            indicator_signals["Bollinger"] = {"signal": "BUY", "strength": 0.7}
                            print_colored(f"布林带: 价格接近下轨 ({bb_position:.2f})，震荡市场买入信号", Colors.GREEN)
                        elif environment == "ACCUMULATION":
                            indicator_signals["Bollinger"] = {"signal": "SELL", "strength": 0.5}
                            print_colored(f"布林带: 价格突破下轨 ({bb_position:.2f})，积累期潜在下破", Colors.RED)
                    else:
                        if bb_position > 0.8:
                            indicator_signals["Bollinger"] = {"signal": "SELL", "strength": 0.4}
                            print_colored(f"布林带: 价格位于上侧 ({bb_position:.2f})，偏向卖出", Colors.YELLOW)
                        elif bb_position < 0.2:
                            indicator_signals["Bollinger"] = {"signal": "BUY", "strength": 0.4}
                            print_colored(f"布林带: 价格位于下侧 ({bb_position:.2f})，偏向买入", Colors.YELLOW)
                        else:
                            indicator_signals["Bollinger"] = {"signal": "NEUTRAL", "strength": 0.3}
                            print_colored(f"布林带: 价格位于中间区域 ({bb_position:.2f})，中性信号", Colors.GRAY)

                # 威廉指标(R%)，震荡市场的反转指标
                if 'Williams_R' in df.columns:
                    williams = df['Williams_R'].iloc[-1]

                    if williams <= -80:
                        indicator_signals["Williams_R"] = {"signal": "BUY", "strength": 0.7, "value": williams}
                        print_colored(f"威廉指标: {williams:.2f} - 超卖区域，看涨信号", Colors.GREEN)
                    elif williams >= -20:
                        indicator_signals["Williams_R"] = {"signal": "SELL", "strength": 0.7, "value": williams}
                        print_colored(f"威廉指标: {williams:.2f} - 超买区域，看跌信号", Colors.RED)
                    else:
                        indicator_signals["Williams_R"] = {"signal": "NEUTRAL", "strength": 0.3, "value": williams}
                        print_colored(f"威廉指标: {williams:.2f} - 中性区域", Colors.GRAY)

            # ===== 趋势市场优先指标 =====
            if environment in ["STRONG_TREND", "TREND", "WEAK_TREND"]:
                # 超级趋势(趋势市场的主要指标)
                if 'Supertrend_Direction' in df.columns:
                    st_direction = df['Supertrend_Direction'].iloc[-1]

                    if st_direction > 0:
                        strength = 0.8 if environment == "STRONG_TREND" else 0.6
                        indicator_signals["Supertrend"] = {"signal": "BUY", "strength": strength}
                        print_colored(f"超级趋势: 上升趋势，看涨信号", Colors.GREEN)
                    elif st_direction < 0:
                        strength = 0.8 if environment == "STRONG_TREND" else 0.6
                        indicator_signals["Supertrend"] = {"signal": "SELL", "strength": strength}
                        print_colored(f"超级趋势: 下降趋势，看跌信号", Colors.RED)

                # MACD(趋势跟踪指标)
                if 'MACD' in df.columns and 'MACD_signal' in df.columns:
                    macd = df['MACD'].iloc[-1]
                    signal = df['MACD_signal'].iloc[-1]

                    if macd > signal:
                        strength = 0.7 if environment == "STRONG_TREND" else 0.5
                        indicator_signals["MACD"] = {"signal": "BUY", "strength": strength}
                        print_colored(f"MACD: {macd:.4f} > 信号线 {signal:.4f}，看涨信号", Colors.GREEN)
                    elif macd < signal:
                        strength = 0.7 if environment == "STRONG_TREND" else 0.5
                        indicator_signals["MACD"] = {"signal": "SELL", "strength": strength}
                        print_colored(f"MACD: {macd:.4f} < 信号线 {signal:.4f}，看跌信号", Colors.RED)
                    else:
                        indicator_signals["MACD"] = {"signal": "NEUTRAL", "strength": 0.3}
                        print_colored(f"MACD: {macd:.4f} = 信号线 {signal:.4f}，中性信号", Colors.GRAY)

                # Vortex指标(趋势确认)
                if 'VI_plus' in df.columns and 'VI_minus' in df.columns:
                    vi_plus = df['VI_plus'].iloc[-1]
                    vi_minus = df['VI_minus'].iloc[-1]

                    if vi_plus > vi_minus:
                        strength = 0.6 if vi_plus - vi_minus > 0.05 else 0.4
                        indicator_signals["Vortex"] = {"signal": "BUY", "strength": strength}
                        print_colored(f"Vortex: VI+ {vi_plus:.4f} > VI- {vi_minus:.4f}，看涨信号", Colors.GREEN)
                    elif vi_plus < vi_minus:
                        strength = 0.6 if vi_minus - vi_plus > 0.05 else 0.4
                        indicator_signals["Vortex"] = {"signal": "SELL", "strength": strength}
                        print_colored(f"Vortex: VI+ {vi_plus:.4f} < VI- {vi_minus:.4f}，看跌信号", Colors.RED)
                    else:
                        indicator_signals["Vortex"] = {"signal": "NEUTRAL", "strength": 0.3}
                        print_colored(f"Vortex: VI+ {vi_plus:.4f} = VI- {vi_minus:.4f}，中性信号", Colors.GRAY)

            # ===== 每种环境都要检查的指标 =====

            # 动量指标
            if 'Momentum' in df.columns:
                momentum = df['Momentum'].iloc[-1]

                if momentum > 0:
                    strength = 0.5 if environment in ["STRONG_TREND", "TREND"] else 0.3
                    indicator_signals["Momentum"] = {"signal": "BUY", "strength": strength}
                    print_colored(f"动量: {momentum:.2f} > 0，看涨信号", Colors.GREEN)
                elif momentum < 0:
                    strength = 0.5 if environment in ["STRONG_TREND", "TREND"] else 0.3
                    indicator_signals["Momentum"] = {"signal": "SELL", "strength": strength}
                    print_colored(f"动量: {momentum:.2f} < 0，看跌信号", Colors.RED)
                else:
                    indicator_signals["Momentum"] = {"signal": "NEUTRAL", "strength": 0.2}
                    print_colored(f"动量: {momentum:.2f} = 0，中性信号", Colors.GRAY)

            # 移动平均线指标
            if 'EMA5' in df.columns and 'EMA20' in df.columns:
                ema5 = df['EMA5'].iloc[-1]
                ema20 = df['EMA20'].iloc[-1]

                if ema5 > ema20:
                    strength = 0.6 if environment in ["STRONG_TREND", "TREND"] else 0.4
                    indicator_signals["EMA"] = {"signal": "BUY", "strength": strength}
                    print_colored(f"EMA: 短期(5) {ema5:.2f} > 长期(20) {ema20:.2f}，看涨信号", Colors.GREEN)
                elif ema5 < ema20:
                    strength = 0.6 if environment in ["STRONG_TREND", "TREND"] else 0.4
                    indicator_signals["EMA"] = {"signal": "SELL", "strength": strength}
                    print_colored(f"EMA: 短期(5) {ema5:.2f} < 长期(20) {ema20:.2f}，看跌信号", Colors.RED)
                else:
                    indicator_signals["EMA"] = {"signal": "NEUTRAL", "strength": 0.2}
                    print_colored(f"EMA: 短期(5) {ema5:.2f} = 长期(20) {ema20:.2f}，中性信号", Colors.GRAY)

            # 3. 综合各指标信号
            buy_strength = 0
            sell_strength = 0
            total_strength = 0

            for indicator, data in indicator_signals.items():
                if data["signal"] == "BUY":
                    buy_strength += data["strength"]
                elif data["signal"] == "SELL":
                    sell_strength += data["strength"]
                total_strength += data["strength"]

            # 确保总强度不为零
            if total_strength == 0:
                total_strength = 1

            # 归一化买卖信号强度
            buy_ratio = buy_strength / total_strength
            sell_ratio = sell_strength / total_strength

            # 输出信号比例
            print_colored(f"信号强度比例 - 买入: {buy_ratio:.2f}, 卖出: {sell_ratio:.2f}", Colors.BLUE)

            # 4. 基于环境的不同阈值
            if environment in ["STRONG_TREND", "TREND"]:
                # 趋势市场需要更强的信号
                buy_threshold = 0.65  # 需要65%的买入信号
                sell_threshold = 0.65  # 需要65%的卖出信号
            else:
                # 震荡市场可以更积极
                buy_threshold = 0.55  # 需要55%的买入信号
                sell_threshold = 0.55  # 需要55%的卖出信号

            # 5. 确定最终信号
            if buy_ratio >= buy_threshold:
                final_signal = "BUY"
                # 质量评分模拟 - 基于信号强度(0-10分)
                adjusted_score = 5.0 + (buy_ratio * 5.0)  # 分数范围5-10
            elif sell_ratio >= sell_threshold:
                final_signal = "SELL"
                # 质量评分模拟 - 基于信号强度(0-10分)
                adjusted_score = 5.0 - (sell_ratio * 5.0)  # 分数范围0-5
            else:
                final_signal = "HOLD"
                # 中性评分
                adjusted_score = 5.0

            # 6. 记录最终信号
            print_colored(f"{symbol} 环境感知信号: {final_signal}, 评分: {adjusted_score:.2f}", Colors.BOLD)

            return final_signal, adjusted_score

        except Exception as e:
            self.logger.error(f"{symbol} 信号生成失败: {e}")
            return "HOLD", 0

    def diagnose_indicators(self, df, symbol):
        """诊断各指标状态，帮助识别问题"""
        print_colored(f"\n===== {symbol} 指标诊断 =====", Colors.BLUE + Colors.BOLD)

        # 检查趋势指标
        if 'ADX' in df.columns:
            adx = df['ADX'].iloc[-1]
            if adx > 30:
                print_colored(f"ADX: {adx:.2f} - 强趋势", Colors.GREEN + Colors.BOLD)
            elif adx > 20:
                print_colored(f"ADX: {adx:.2f} - 弱趋势", Colors.GREEN)
            else:
                print_colored(f"ADX: {adx:.2f} - 无趋势/震荡", Colors.YELLOW)

        # 检查超级趋势
        if 'Supertrend_Direction' in df.columns:
            st_dir = df['Supertrend_Direction'].iloc[-1]
            if st_dir > 0:
                print_colored("超级趋势: 上升趋势", Colors.GREEN)
            elif st_dir < 0:
                print_colored("超级趋势: 下降趋势", Colors.RED)
            else:
                print_colored("超级趋势: 中性", Colors.GRAY)

        # 检查布林带
        if all(x in df.columns for x in ['BB_Upper', 'BB_Lower', 'BB_Middle']):
            close = df['close'].iloc[-1]
            upper = df['BB_Upper'].iloc[-1]
            lower = df['BB_Lower'].iloc[-1]
            middle = df['BB_Middle'].iloc[-1]

            bb_width = (upper - lower) / middle
            position = (close - lower) / (upper - lower)

            print_colored(f"布林带宽度: {bb_width:.4f}", Colors.BLUE)

            if bb_width < 0.03:
                print_colored("布林带极度收缩，可能即将突破", Colors.YELLOW + Colors.BOLD)
            elif bb_width < 0.06:
                print_colored("布林带收缩，波动性减小", Colors.YELLOW)

            if position > 0.8:
                print_colored(f"价格位置: 接近上轨 ({position:.2f})", Colors.RED)
            elif position < 0.2:
                print_colored(f"价格位置: 接近下轨 ({position:.2f})", Colors.GREEN)
            else:
                print_colored(f"价格位置: 中间区域 ({position:.2f})", Colors.GRAY)

        # 检查RSI
        if 'RSI' in df.columns:
            rsi = df['RSI'].iloc[-1]
            if rsi > 70:
                print_colored(f"RSI: {rsi:.2f} - 超买", Colors.RED)
            elif rsi < 30:
                print_colored(f"RSI: {rsi:.2f} - 超卖", Colors.GREEN)
            else:
                print_colored(f"RSI: {rsi:.2f} - 中性", Colors.GRAY)

        # 检查MACD
        if 'MACD' in df.columns and 'MACD_signal' in df.columns:
            macd = df['MACD'].iloc[-1]
            signal = df['MACD_signal'].iloc[-1]
            hist = df['MACD_histogram'].iloc[-1] if 'MACD_histogram' in df.columns else macd - signal

            if macd > signal:
                print_colored(f"MACD: {macd:.4f} > 信号线 {signal:.4f} (柱状图: {hist:.4f})", Colors.GREEN)
            else:
                print_colored(f"MACD: {macd:.4f} < 信号线 {signal:.4f} (柱状图: {hist:.4f})", Colors.RED)

        # 检查Vortex
        if 'VI_plus' in df.columns and 'VI_minus' in df.columns:
            vi_plus = df['VI_plus'].iloc[-1]
            vi_minus = df['VI_minus'].iloc[-1]
            diff = vi_plus - vi_minus

            if diff > 0:
                print_colored(f"Vortex: VI+ {vi_plus:.4f} > VI- {vi_minus:.4f} (差值: {diff:.4f})", Colors.GREEN)
            else:
                print_colored(f"Vortex: VI+ {vi_plus:.4f} < VI- {vi_minus:.4f} (差值: {diff:.4f})", Colors.RED)

        # 检查移动平均线
        if 'EMA5' in df.columns and 'EMA20' in df.columns:
            ema5 = df['EMA5'].iloc[-1]
            ema20 = df['EMA20'].iloc[-1]

            if ema5 > ema20:
                print_colored(f"EMA交叉: 短期(5) {ema5:.2f} > 长期(20) {ema20:.2f}", Colors.GREEN)
            else:
                print_colored(f"EMA交叉: 短期(5) {ema5:.2f} < 长期(20) {ema20:.2f}", Colors.RED)

    def classify_market_environment(self, df):
        """
        将市场分类为：强趋势、弱趋势、震荡、突破前的积累
        """
        # 获取ADX - 趋势强度指标
        adx = df['ADX'].iloc[-1] if 'ADX' in df.columns else 0

        # 获取布林带宽度
        bbw = ((df['BB_Upper'].iloc[-1] - df['BB_Lower'].iloc[-1]) /
               df['BB_Middle'].iloc[-1]) if all(x in df.columns for x in
                                                ['BB_Upper', 'BB_Lower', 'BB_Middle']) else 0.1

        # 计算波动率比率
        atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else 0
        atr_mean = df['ATR'].rolling(20).mean().iloc[-1] if 'ATR' in df.columns else 1
        atr_ratio = atr / atr_mean if atr_mean > 0 else 1.0

        # 市场环境分类
        if adx > 30:
            if atr_ratio > 1.5:
                return "STRONG_TREND"  # 强趋势
            else:
                return "TREND"  # 普通趋势
        elif adx < 20:
            if bbw < 0.05:
                return "ACCUMULATION"  # 积累期(可能的突破前兆)
            else:
                return "RANGING"  # 震荡市场
        else:
            return "WEAK_TREND"  # 弱趋势

    def place_hedge_orders(self, symbol, primary_side, quality_score):
        """根据质量评分和信号放置订单，支持双向持仓"""
        account_balance = self.get_futures_balance()

        if account_balance < self.config.get("MIN_MARGIN_BALANCE", 10):
            self.logger.warning(f"账户余额不足，无法交易: {account_balance} USDC")
            return False

        # 检查当前持仓
        total_exposure, symbol_exposures = get_total_position_exposure(self.open_positions, account_balance)
        symbol_exposure = symbol_exposures.get(symbol, 0)

        # 计算下单金额
        order_amount, order_pct = calculate_order_amount(
            account_balance,
            symbol_exposure,
            max_total_exposure=85,
            max_symbol_exposure=15,
            default_order_pct=5
        )

        if order_amount <= 0:
            self.logger.warning(f"{symbol}下单金额过小或超出限额")
            return False

        # 双向持仓模式
        if primary_side == "BOTH":
            # 质量评分在中间区域时采用双向持仓
            if 4.0 <= quality_score <= 6.0:
                long_amount = order_amount * 0.6  # 60%做多
                short_amount = order_amount * 0.4  # 40%做空

                long_success = self.place_futures_order_usdc(symbol, "BUY", long_amount)
                time.sleep(1)  # 避免API请求过快
                short_success = self.place_futures_order_usdc(symbol, "SELL", short_amount)

                if long_success and short_success:
                    self.logger.info(f"{symbol}双向持仓成功", extra={
                        "long_amount": long_amount,
                        "short_amount": short_amount,
                        "quality_score": quality_score
                    })
                    return True
                else:
                    self.logger.warning(f"{symbol}双向持仓部分失败", extra={
                        "long_success": long_success,
                        "short_success": short_success
                    })
                    return long_success or short_success
            else:
                # 偏向某一方向
                side = "BUY" if quality_score > 5.0 else "SELL"
                return self.place_futures_order_usdc(symbol, side, order_amount)

        elif primary_side in ["BUY", "SELL"]:
            # 根据评分调整杠杆倍数
            leverage = self.calculate_leverage_from_quality(quality_score)
            return self.place_futures_order_usdc(symbol, primary_side, order_amount, leverage)
        else:
            self.logger.warning(f"{symbol}未知交易方向: {primary_side}")
            return False

    def calculate_leverage_from_quality(self, quality_score):
        """根据质量评分计算合适的杠杆水平"""
        if quality_score >= 9.0:
            return 20  # 最高质量，最高杠杆
        elif quality_score >= 8.0:
            return 15
        elif quality_score >= 7.0:
            return 10
        elif quality_score >= 6.0:
            return 8
        elif quality_score >= 5.0:
            return 5
        elif quality_score >= 4.0:
            return 3
        else:
            return 2  # 默认低杠杆

    def check_entry_timing(self, symbol: str, side: str) -> dict:
        """
        检查当前是否是好的入场时机，如果不是则提供预计入场价格和等待时间

        参数:
            symbol: 交易对符号
            side: 交易方向 ('BUY' 或 'SELL')

        返回:
            dict: 包含入场决策和等待建议的字典
            {
                "should_enter": 是否应该立即入场(布尔值),
                "expected_price": 预期入场价格,
                "wait_minutes": 预计等待分钟数,
                "reason": 决策理由,
                "timing_quality": 入场时机质量评估
            }
        """
        from logger_utils import Colors, print_colored
        from pivot_points_module import calculate_pivot_points, analyze_pivot_point_strategy
        from indicators_module import find_swing_points, calculate_fibonacci_retracements, get_smc_trend_and_duration

        # 默认返回结果 - 允许入场
        result = {
            "should_enter": True,
            "expected_price": 0.0,
            "wait_minutes": 0,
            "reason": "默认允许入场",
            "timing_quality": "未知"
        }

        # 获取历史数据
        df = self.get_historical_data_with_cache(symbol)
        if df is None or df.empty or len(df) < 20:
            return result  # 如果无法获取数据，默认允许入场

        # 添加必要的技术指标
        try:
            # 确保数据中包含支点
            if 'Classic_PP' not in df.columns:
                df = calculate_pivot_points(df, method='classic')

            # 获取支点分析
            pivot_analysis = analyze_pivot_point_strategy(df, method='classic')

            # 获取当前价格
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])

            # 获取摆动点
            swing_highs, swing_lows = find_swing_points(df)

            # 获取Fibonacci回撤水平
            fib_levels = calculate_fibonacci_retracements(df)

            # 获取趋势信息
            trend, duration, trend_info = get_smc_trend_and_duration(df)

            # 获取布林带信息
            bb_upper = df['BB_Upper'].iloc[-1] if 'BB_Upper' in df.columns else None
            bb_lower = df['BB_Lower'].iloc[-1] if 'BB_Lower' in df.columns else None
            bb_middle = df['BB_Middle'].iloc[-1] if 'BB_Middle' in df.columns else None

            # 获取ATR信息，用于评估波动性
            atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else (df['high'].iloc[-1] - df['low'].iloc[-1]) * 0.1

            # 根据ATR和当前价格计算预期等待时间(假设每分钟价格变动约为ATR的5%)
            atr_per_minute = atr * 0.05

            # 1. 检查买入入场条件
            if side == "BUY":
                # 获取关键支撑和阻力位
                support_1 = pivot_analysis["support_1"]
                resistance_1 = pivot_analysis["resistance_1"]
                pivot_point = pivot_analysis["pivot_point"]

                # 买入最佳入场条件:

                # A. 价格已经突破阻力位 - 立即入场
                if current_price > resistance_1 * 1.005:  # 突破阻力位R1达0.5%
                    result["should_enter"] = True
                    result["reason"] = f"价格 {current_price:.6f} 已突破阻力位 R1 {resistance_1:.6f}，确认上涨趋势"
                    result["timing_quality"] = "优秀"
                    return result

                # B. 价格在支撑位附近 - 立即入场
                if current_price < support_1 * 1.01:  # 在支撑位S1附近1%范围内
                    result["should_enter"] = True
                    result["reason"] = f"价格 {current_price:.6f} 接近支撑位 S1 {support_1:.6f}，可能反弹"
                    result["timing_quality"] = "优秀"
                    return result

                # C. 布林带突破 - 立即入场
                if bb_upper is not None and current_price > bb_upper * 1.002:
                    result["should_enter"] = True
                    result["reason"] = f"价格 {current_price:.6f} 突破布林带上轨 {bb_upper:.6f}，动能上升"
                    result["timing_quality"] = "优秀"
                    return result

                # D. 趋势向上且回调到支撑位 - 立即入场
                if trend == "UP" and current_price < bb_middle * 1.01 and current_price > bb_middle * 0.99:
                    result["should_enter"] = True
                    result["reason"] = f"价格回调至中轨附近 {bb_middle:.6f}，上升趋势中的回调买入"
                    result["timing_quality"] = "良好"
                    return result

                # E. 特定Fibonacci回撤位 - 立即入场
                if fib_levels and len(fib_levels) >= 3:
                    fib_0382 = fib_levels[1]  # 0.382回撤位
                    fib_0618 = fib_levels[2]  # 0.618回撤位

                    if abs(current_price - fib_0618) / fib_0618 < 0.01:
                        result["should_enter"] = True
                        result["reason"] = f"价格 {current_price:.6f} 接近 0.618 Fibonacci回撤位 {fib_0618:.6f}"
                        result["timing_quality"] = "良好"
                        return result

                    if abs(current_price - fib_0382) / fib_0382 < 0.01:
                        result["should_enter"] = True
                        result["reason"] = f"价格 {current_price:.6f} 接近 0.382 Fibonacci回撤位 {fib_0382:.6f}"
                        result["timing_quality"] = "良好"
                        return result

                # F. 支点信号强烈建议买入 - 立即入场
                if pivot_analysis["signal"] == "BUY" and pivot_analysis["confidence"] >= 0.7:
                    result["should_enter"] = True
                    result["reason"] = f"支点分析给出高置信度买入信号: {pivot_analysis['reason']}"
                    result["timing_quality"] = "良好"
                    return result

                # 如果没有满足最佳入场条件，提供等待建议:

                # 情况1: 价格高于阻力位下方 - 等待回调
                if current_price > pivot_point and current_price < resistance_1 * 0.99:
                    expected_price = resistance_1 * 1.01  # 期望价格突破阻力位1%
                    price_diff = expected_price - current_price
                    wait_minutes = max(10, abs(int(price_diff / atr_per_minute)))

                    result["should_enter"] = False
                    result["expected_price"] = expected_price
                    result["wait_minutes"] = wait_minutes
                    result["reason"] = f"价格接近阻力位，等待突破 R1 {resistance_1:.6f} 后入场"
                    result["timing_quality"] = "一般"
                    return result

                # 情况2: 价格远离支撑位 - 等待回调到支撑位
                if current_price > support_1 * 1.03:
                    expected_price = support_1 * 1.01  # 期望价格靠近支撑位1%内
                    price_diff = current_price - expected_price
                    wait_minutes = max(15, abs(int(price_diff / atr_per_minute)))

                    result["should_enter"] = False
                    result["expected_price"] = expected_price
                    result["wait_minutes"] = wait_minutes
                    result["reason"] = f"价格远离支撑位，等待回调至 S1 {support_1:.6f} 附近后入场"
                    result["timing_quality"] = "一般"
                    return result

                # 情况3: 价格远离中轨 - 等待回调到中轨
                if bb_middle is not None and current_price > bb_middle * 1.02:
                    expected_price = bb_middle
                    price_diff = current_price - expected_price
                    wait_minutes = max(12, abs(int(price_diff / atr_per_minute)))

                    result["should_enter"] = False
                    result["expected_price"] = expected_price
                    result["wait_minutes"] = wait_minutes
                    result["reason"] = f"价格高于中轨，等待回调至布林带中轨 {bb_middle:.6f} 后入场"
                    result["timing_quality"] = "一般"
                    return result

                # 如果没有明确的等待条件，默认允许入场
                result["timing_quality"] = "一般"
                return result

            # 2. 检查卖出入场条件
            elif side == "SELL":
                # 获取关键支撑和阻力位
                support_1 = pivot_analysis["support_1"]
                resistance_1 = pivot_analysis["resistance_1"]
                pivot_point = pivot_analysis["pivot_point"]

                # 卖出最佳入场条件:

                # A. 价格已经跌破支撑位 - 立即入场
                if current_price < support_1 * 0.995:  # 跌破支撑位S1达0.5%
                    result["should_enter"] = True
                    result["reason"] = f"价格 {current_price:.6f} 已跌破支撑位 S1 {support_1:.6f}，确认下跌趋势"
                    result["timing_quality"] = "优秀"
                    return result

                # B. 价格在阻力位附近 - 立即入场
                if current_price > resistance_1 * 0.99:  # 在阻力位R1附近1%范围内
                    result["should_enter"] = True
                    result["reason"] = f"价格 {current_price:.6f} 接近阻力位 R1 {resistance_1:.6f}，可能回落"
                    result["timing_quality"] = "优秀"
                    return result

                # C. 布林带突破 - 立即入场
                if bb_lower is not None and current_price < bb_lower * 0.998:
                    result["should_enter"] = True
                    result["reason"] = f"价格 {current_price:.6f} 跌破布林带下轨 {bb_lower:.6f}，动能下降"
                    result["timing_quality"] = "优秀"
                    return result

                # D. 趋势向下且反弹到阻力位 - 立即入场
                if trend == "DOWN" and current_price < bb_middle * 1.01 and current_price > bb_middle * 0.99:
                    result["should_enter"] = True
                    result["reason"] = f"价格反弹至中轨附近 {bb_middle:.6f}，下降趋势中的反弹卖出"
                    result["timing_quality"] = "良好"
                    return result

                # E. 特定Fibonacci回撤位 - 立即入场
                if fib_levels and len(fib_levels) >= 3:
                    fib_0382 = fib_levels[1]  # 0.382回撤位
                    fib_0618 = fib_levels[2]  # 0.618回撤位

                    if abs(current_price - fib_0382) / fib_0382 < 0.01:
                        result["should_enter"] = True
                        result["reason"] = f"价格 {current_price:.6f} 接近 0.382 Fibonacci回撤位 {fib_0382:.6f}"
                        result["timing_quality"] = "良好"
                        return result

                    if abs(current_price - fib_0618) / fib_0618 < 0.01:
                        result["should_enter"] = True
                        result["reason"] = f"价格 {current_price:.6f} 接近 0.618 Fibonacci回撤位 {fib_0618:.6f}"
                        result["timing_quality"] = "良好"
                        return result

                # F. 支点信号强烈建议卖出 - 立即入场
                if pivot_analysis["signal"] == "SELL" and pivot_analysis["confidence"] >= 0.7:
                    result["should_enter"] = True
                    result["reason"] = f"支点分析给出高置信度卖出信号: {pivot_analysis['reason']}"
                    result["timing_quality"] = "良好"
                    return result

                # 如果没有满足最佳入场条件，提供等待建议:

                # 情况1: 价格低于支撑位上方 - 等待跌破
                if current_price < pivot_point and current_price > support_1 * 1.01:
                    expected_price = support_1 * 0.99  # 期望价格跌破支撑位1%
                    price_diff = current_price - expected_price
                    wait_minutes = max(10, abs(int(price_diff / atr_per_minute)))

                    result["should_enter"] = False
                    result["expected_price"] = expected_price
                    result["wait_minutes"] = wait_minutes
                    result["reason"] = f"价格接近支撑位，等待跌破 S1 {support_1:.6f} 后入场"
                    result["timing_quality"] = "一般"
                    return result

                # 情况2: 价格远离阻力位 - 等待反弹到阻力位
                if current_price < resistance_1 * 0.97:
                    expected_price = resistance_1 * 0.99  # 期望价格靠近阻力位1%内
                    price_diff = expected_price - current_price
                    wait_minutes = max(15, abs(int(price_diff / atr_per_minute)))

                    result["should_enter"] = False
                    result["expected_price"] = expected_price
                    result["wait_minutes"] = wait_minutes
                    result["reason"] = f"价格远离阻力位，等待反弹至 R1 {resistance_1:.6f} 附近后入场"
                    result["timing_quality"] = "一般"
                    return result

                # 情况3: 价格远离中轨 - 等待反弹到中轨
                if bb_middle is not None and current_price < bb_middle * 0.98:
                    expected_price = bb_middle
                    price_diff = expected_price - current_price
                    wait_minutes = max(12, abs(int(price_diff / atr_per_minute)))

                    result["should_enter"] = False
                    result["expected_price"] = expected_price
                    result["wait_minutes"] = wait_minutes
                    result["reason"] = f"价格低于中轨，等待反弹至布林带中轨 {bb_middle:.6f} 后入场"
                    result["timing_quality"] = "一般"
                    return result

                # 如果没有明确的等待条件，默认允许入场
                result["timing_quality"] = "一般"
                return result

        except Exception as e:
            # 如果计算过程出错，记录日志并默认允许入场
            import traceback
            error_details = traceback.format_exc()
            print_colored(f"⚠️ 入场时机检查出错: {str(e)}", Colors.ERROR)
            self.logger.error("入场时机检查出错", extra={"error": str(e), "traceback": error_details})
            return result

        # 如果执行到这里，表示没有匹配到任何入场条件，返回默认结果
        return result

    def place_futures_order_usdc(self, symbol: str, side: str, amount: float, leverage: int = 5) -> bool:
        """
        执行期货市场订单 - 使用固定止盈止损，不依赖市场预测

        参数:
            symbol: 交易对符号
            side: 交易方向 ('BUY' 或 'SELL')
            amount: 交易金额(USDC)
            leverage: 杠杆倍数

        返回:
            bool: 交易是否成功
        """
        import math
        import time
        from logger_utils import Colors, print_colored

        try:
            # 获取当前账户余额
            account_balance = self.get_futures_balance()
            print(f"📊 当前账户余额: {account_balance:.2f} USDC")

            # 获取当前价格
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])

            # 使用固定的止盈止损值，不依赖预测
            take_profit = 0.0175  # 固定1.75%止盈
            stop_loss = -0.0125  # 固定1.25%止损
            print_colored(f"📊 使用固定止盈1.75%，止损1.25%", Colors.BLUE)

            # 严格限制订单金额不超过账户余额的5%
            max_allowed_amount = account_balance * 0.05

            if amount > max_allowed_amount:
                print(f"⚠️ 订单金额 {amount:.2f} USDC 超过账户余额5%限制，已调整为 {max_allowed_amount:.2f} USDC")
                amount = max_allowed_amount

            # 确保最低订单金额
            min_amount = self.config.get("MIN_NOTIONAL", 5)
            if amount < min_amount and account_balance >= min_amount:
                amount = min_amount
                print(f"⚠️ 订单金额已调整至最低限额: {min_amount} USDC")

            # 获取交易对信息
            info = self.client.futures_exchange_info()

            step_size = None
            min_qty = None
            notional_min = None

            # 查找该交易对的所有过滤器
            for item in info['symbols']:
                if item['symbol'] == symbol:
                    for f in item['filters']:
                        # 数量精度
                        if f['filterType'] == 'LOT_SIZE':
                            step_size = float(f['stepSize'])
                            min_qty = float(f['minQty'])
                            max_qty = float(f['maxQty'])
                        # 最小订单价值
                        elif f['filterType'] == 'MIN_NOTIONAL':
                            notional_min = float(f.get('notional', 0))
                    break

            # 确保找到了必要的信息
            if step_size is None:
                print_colored(f"❌ {symbol} 无法获取交易精度信息", Colors.ERROR)
                return False

            # 计算数量并应用精度限制
            raw_qty = amount / current_price

            # 计算实际需要的保证金
            margin_required = amount / leverage
            if margin_required > account_balance:
                print(f"❌ 保证金不足: 需要 {margin_required:.2f} USDC, 账户余额 {account_balance:.2f} USDC")
                return False

            # 应用数量精度
            precision = int(round(-math.log(step_size, 10), 0))
            quantity = math.floor(raw_qty * 10 ** precision) / 10 ** precision

            # 确保数量>=最小数量
            if quantity < min_qty:
                print_colored(f"⚠️ {symbol} 数量 {quantity} 小于最小交易量 {min_qty}，已调整", Colors.WARNING)
                quantity = min_qty

            # 格式化为字符串(避免科学计数法问题)
            qty_str = f"{quantity:.{precision}f}"

            # 检查最小订单价值
            notional = quantity * current_price
            if notional_min and notional < notional_min:
                print_colored(f"⚠️ {symbol} 订单价值 ({notional:.2f}) 低于最小要求 ({notional_min})", Colors.WARNING)
                new_qty = math.ceil(notional_min / current_price * 10 ** precision) / 10 ** precision
                quantity = max(min_qty, new_qty)
                qty_str = f"{quantity:.{precision}f}"
                notional = quantity * current_price

            print_colored(f"🔢 {symbol} 计划交易: 金额={amount:.2f} USDC, 数量={quantity}, 价格={current_price}",
                          Colors.INFO)
            print_colored(f"🔢 杠杆: {leverage}倍, 实际保证金: {notional / leverage:.2f} USDC", Colors.INFO)

            # 设置杠杆
            try:
                self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
                print(f"✅ {symbol} 设置杠杆成功: {leverage}倍")
            except Exception as e:
                print(f"⚠️ {symbol} 设置杠杆失败: {e}，使用默认杠杆 1")
                leverage = 1

            # 执行交易
            try:
                if hasattr(self, 'hedge_mode_enabled') and self.hedge_mode_enabled:
                    # 双向持仓模式
                    pos_side = "LONG" if side.upper() == "BUY" else "SHORT"
                    order = self.client.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type="MARKET",
                        quantity=qty_str,
                        positionSide=pos_side
                    )
                else:
                    # 单向持仓模式
                    order = self.client.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type="MARKET",
                        quantity=qty_str
                    )

                print_colored(f"✅ {side} {symbol} 成功, 数量={quantity}, 杠杆={leverage}倍", Colors.GREEN)
                self.logger.info(f"{symbol} {side} 订单成功", extra={
                    "order_id": order.get("orderId", "unknown"),
                    "quantity": quantity,
                    "notional": notional,
                    "leverage": leverage,
                    "take_profit": take_profit * 100,
                    "stop_loss": abs(stop_loss) * 100
                })

                # 记录持仓信息 - 使用固定止盈止损
                self.record_open_position(symbol, side, current_price, quantity,
                                          take_profit=take_profit,
                                          stop_loss=stop_loss)
                return True

            except Exception as e:
                order_error = str(e)
                print_colored(f"❌ {symbol} {side} 订单执行失败: {order_error}", Colors.ERROR)

                if "insufficient balance" in order_error.lower() or "margin is insufficient" in order_error.lower():
                    print_colored(f"  原因: 账户余额或保证金不足", Colors.WARNING)
                    print_colored(f"  当前余额: {account_balance} USDC, 需要保证金: {notional / leverage:.2f} USDC",
                                  Colors.WARNING)
                elif "precision" in order_error.lower():
                    print_colored(f"  原因: 价格或数量精度不正确", Colors.WARNING)
                elif "lot size" in order_error.lower():
                    print_colored(f"  原因: 订单大小不符合要求", Colors.WARNING)
                elif "min notional" in order_error.lower():
                    print_colored(f"  原因: 订单价值低于最小要求", Colors.WARNING)

                self.logger.error(f"{symbol} {side} 交易失败", extra={"error": order_error})
                return False

        except Exception as e:
            print_colored(f"❌ {symbol} {side} 交易过程中发生错误: {e}", Colors.ERROR)
            self.logger.error(f"{symbol} 交易错误", extra={"error": str(e)})
            return False

    def record_open_position(self, symbol, side, entry_price, quantity, take_profit=0.0175, stop_loss=-0.0125):
        """记录新开的持仓，使用固定的止盈止损比例

        参数:
            symbol: 交易对符号
            side: 交易方向 ('BUY' 或 'SELL')
            entry_price: 入场价格
            quantity: 交易数量
            take_profit: 止盈百分比，默认1.75%
            stop_loss: 止损百分比，默认-1.25%
        """
        position_side = "LONG" if side.upper() == "BUY" else "SHORT"

        # 检查是否已有同方向持仓
        for i, pos in enumerate(self.open_positions):
            if pos["symbol"] == symbol and pos.get("position_side", None) == position_side:
                # 合并持仓
                total_qty = pos["quantity"] + quantity
                new_entry = (pos["entry_price"] * pos["quantity"] + entry_price * quantity) / total_qty
                self.open_positions[i]["entry_price"] = new_entry
                self.open_positions[i]["quantity"] = total_qty
                self.open_positions[i]["last_update_time"] = time.time()

                # 使用固定的止盈止损比例
                self.open_positions[i]["dynamic_take_profit"] = take_profit  # 固定2.5%止盈
                self.open_positions[i]["stop_loss"] = stop_loss  # 固定1.75%止损

                self.logger.info(f"更新{symbol} {position_side}持仓", extra={
                    "new_entry_price": new_entry,
                    "total_quantity": total_qty,
                    "take_profit": take_profit,
                    "stop_loss": stop_loss
                })
                return

        # 添加新持仓，使用固定的止盈止损比例
        new_pos = {
            "symbol": symbol,
            "side": side,
            "position_side": position_side,
            "entry_price": entry_price,
            "quantity": quantity,
            "open_time": time.time(),
            "last_update_time": time.time(),
            "max_profit": 0.0,
            "dynamic_take_profit": take_profit,  # 固定2.5%止盈
            "stop_loss": stop_loss,  # 固定1.75%止损
            "position_id": f"{symbol}_{position_side}_{int(time.time())}"
        }

        self.open_positions.append(new_pos)
        self.logger.info(f"新增{symbol} {position_side}持仓", extra={
            **new_pos,
            "take_profit": take_profit,
            "stop_loss": stop_loss
        })

        print_colored(
            f"📝 新增{symbol} {position_side}持仓，止盈: {take_profit * 100:.2f}%，止损: {abs(stop_loss) * 100:.2f}%",
            Colors.GREEN + Colors.BOLD)

    def close_position(self, symbol, position_side=None):
        """平仓指定货币对的持仓，并记录历史"""
        try:
            # 查找匹配的持仓
            positions_to_close = []
            for pos in self.open_positions:
                if pos["symbol"] == symbol:
                    if position_side is None or pos.get("position_side", "LONG") == position_side:
                        positions_to_close.append(pos)

            if not positions_to_close:
                print(f"⚠️ 未找到 {symbol} {position_side or '任意方向'} 的持仓")
                return False, []

            closed_positions = []
            success = False

            for pos in positions_to_close:
                pos_side = pos.get("position_side", "LONG")
                quantity = pos["quantity"]

                # 平仓方向
                close_side = "SELL" if pos_side == "LONG" else "BUY"

                print(f"📉 平仓 {symbol} {pos_side}, 数量: {quantity}")

                try:
                    # 获取精确数量
                    info = self.client.futures_exchange_info()
                    step_size = None

                    for item in info['symbols']:
                        if item['symbol'] == symbol:
                            for f in item['filters']:
                                if f['filterType'] == 'LOT_SIZE':
                                    step_size = float(f['stepSize'])
                                    break
                            break

                    if step_size:
                        precision = int(round(-math.log(step_size, 10), 0))
                        formatted_qty = f"{quantity:.{precision}f}"
                    else:
                        formatted_qty = str(quantity)

                    # 执行平仓订单
                    if hasattr(self, 'hedge_mode_enabled') and self.hedge_mode_enabled:
                        order = self.client.futures_create_order(
                            symbol=symbol,
                            side=close_side,
                            type="MARKET",
                            quantity=formatted_qty,
                            positionSide=pos_side
                        )
                    else:
                        order = self.client.futures_create_order(
                            symbol=symbol,
                            side=close_side,
                            type="MARKET",
                            quantity=formatted_qty,
                            reduceOnly=True
                        )

                    # 获取平仓价格
                    ticker = self.client.futures_symbol_ticker(symbol=symbol)
                    exit_price = float(ticker['price'])

                    # 计算盈亏
                    entry_price = pos["entry_price"]
                    if pos_side == "LONG":
                        profit_pct = (exit_price - entry_price) / entry_price * 100
                    else:
                        profit_pct = (entry_price - exit_price) / entry_price * 100

                    # 记录平仓成功
                    closed_positions.append(pos)
                    success = True

                    print(f"✅ {symbol} {pos_side} 平仓成功，盈亏: {profit_pct:.2f}%")
                    self.logger.info(f"{symbol} {pos_side} 平仓成功", extra={
                        "profit_pct": profit_pct,
                        "entry_price": entry_price,
                        "exit_price": exit_price
                    })

                except Exception as e:
                    print(f"❌ {symbol} {pos_side} 平仓失败: {e}")
                    self.logger.error(f"{symbol} 平仓失败", extra={"error": str(e)})

            # 从本地持仓列表中移除已平仓的持仓
            for pos in closed_positions:
                if pos in self.open_positions:
                    self.open_positions.remove(pos)

            # 重新加载持仓以确保数据最新
            self.load_existing_positions()

            return success, closed_positions

        except Exception as e:
            print(f"❌ 平仓过程中发生错误: {e}")
            self.logger.error(f"平仓过程错误", extra={"symbol": symbol, "error": str(e)})
            return False, []



    def display_positions_status(self):
        """显示所有持仓的状态"""
        if not self.open_positions:
            print("当前无持仓")
            return

        print("\n==== 当前持仓状态 ====")
        print(f"{'交易对':<10} {'方向':<6} {'持仓量':<10} {'开仓价':<10} {'当前价':<10} {'利润率':<8} {'持仓时间':<8}")
        print("-" * 70)

        current_time = time.time()

        for pos in self.open_positions:
            symbol = pos["symbol"]
            position_side = pos["position_side"]
            quantity = pos["quantity"]
            entry_price = pos["entry_price"]
            open_time = pos["open_time"]

            # 获取当前价格
            try:
                ticker = self.client.futures_symbol_ticker(symbol=symbol)
                current_price = float(ticker['price'])
            except:
                current_price = 0.0

            # 计算利润率
            if position_side == "LONG":
                profit_pct = ((current_price - entry_price) / entry_price) * 100
            else:  # SHORT
                profit_pct = ((entry_price - current_price) / entry_price) * 100

            # 计算持仓时间
            holding_hours = (current_time - open_time) / 3600

            print(
                f"{symbol:<10} {position_side:<6} {quantity:<10.6f} {entry_price:<10.4f} {current_price:<10.4f} {profit_pct:<8.2f}% {holding_hours:<8.2f}h")

        print("-" * 70)

    def get_btc_data(self):
        """专门获取BTC数据的方法"""
        try:
            # 直接从API获取最新数据，完全绕过缓存
            print("正在直接从API获取BTC数据...")

            # 尝试不同的交易对名称
            btc_symbols = ["BTCUSDT", "BTCUSDC"]

            for symbol in btc_symbols:
                try:
                    # 直接调用client.futures_klines而不是get_historical_data
                    klines = self.client.futures_klines(
                        symbol=symbol,
                        interval="15m",
                        limit=30  # 获取足够多的数据点
                    )

                    if klines and len(klines) > 20:
                        print(f"✅ 成功获取{symbol}数据: {len(klines)}行")

                        # 转换为DataFrame
                        df = pd.DataFrame(klines, columns=[
                            'time', 'open', 'high', 'low', 'close', 'volume',
                            'close_time', 'quote_asset_volume', 'trades',
                            'taker_base_vol', 'taker_quote_vol', 'ignore'
                        ])

                        # 转换数据类型
                        for col in ['open', 'high', 'low', 'close', 'volume']:
                            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

                        # 转换时间
                        df['time'] = pd.to_datetime(df['time'], unit='ms', errors='coerce')

                        print(f"BTC价格范围: {df['close'].min():.2f} - {df['close'].max():.2f}")
                        return df
                    else:
                        print(f"⚠️ {symbol}数据不足或为空")
                except Exception as e:
                    print(f"⚠️ 获取{symbol}数据失败: {e}")
                    continue

            # 如果所有交易对都失败，打印更多调试信息
            print("🔍 正在尝试获取可用的交易对列表...")
            try:
                # 获取可用的交易对列表
                exchange_info = self.client.futures_exchange_info()
                available_symbols = [info['symbol'] for info in exchange_info['symbols']]
                btc_symbols = [sym for sym in available_symbols if 'BTC' in sym]
                print(f"发现BTC相关交易对: {btc_symbols[:5]}...")
            except Exception as e:
                print(f"获取交易对列表失败: {e}")

            print("❌ 所有尝试获取BTC数据的方法都失败了")
            return None

        except Exception as e:
            print(f"❌ 获取BTC数据出错: {e}")
            return None

    def load_existing_positions(self):
        """加载现有持仓"""
        self.open_positions = load_positions(self.client, self.logger)

    def execute_with_retry(self, func, *args, max_retries=3, **kwargs):
        """执行函数并在失败时自动重试"""
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt < max_retries - 1:
                    sleep_time = 2 ** attempt  # 指数退避
                    print(f"操作失败，{sleep_time}秒后重试: {e}")
                    time.sleep(sleep_time)
                else:
                    print(f"操作失败，已达到最大重试次数: {e}")
                    raise

    def check_api_connection(self):
        """检查API连接状态"""
        try:
            account_info = self.client.futures_account()
            if "totalMarginBalance" in account_info:
                print("✅ API连接正常")
                return True
            else:
                print("❌ API连接异常: 返回数据格式不正确")
                return False
        except Exception as e:
            print(f"❌ API连接异常: {e}")
            return False

    def display_position_sell_timing(self):
        """显示持仓的预期卖出时机"""
        if not self.open_positions:
            return

        print("\n==== 持仓卖出预测 ====")
        print(f"{'交易对':<10} {'方向':<6} {'当前价':<10} {'预测价':<10} {'预期收益':<10} {'预计时间':<8}")
        print("-" * 70)

        for pos in self.open_positions:
            symbol = pos["symbol"]
            position_side = pos["position_side"]
            entry_price = pos["entry_price"]
            quantity = pos["quantity"]

            # 获取当前价格
            try:
                ticker = self.client.futures_symbol_ticker(symbol=symbol)
                current_price = float(ticker['price'])
            except:
                current_price = 0.0

            # 预测未来价格
            predicted_price = self.predict_short_term_price(symbol)
            if predicted_price is None:
                predicted_price = current_price

            # 计算预期收益
            if position_side == "LONG":
                expected_profit = (predicted_price - entry_price) * quantity
            else:  # SHORT
                expected_profit = (entry_price - predicted_price) * quantity

            # 计算预计时间
            df = self.get_historical_data_with_cache(symbol)
            if df is not None and len(df) > 10:
                window = df['close'].tail(10)
                x = np.arange(len(window))
                slope, _ = np.polyfit(x, window, 1)

                if abs(slope) > 0.00001:
                    minutes_needed = abs((predicted_price - current_price) / slope) * 5
                else:
                    minutes_needed = 60
            else:
                minutes_needed = 60

            print(
                f"{symbol:<10} {position_side:<6} {current_price:<10.4f} {predicted_price:<10.4f} {expected_profit:<10.2f} {minutes_needed:<8.0f}分钟")

        print("-" * 70)


    def display_quality_scores(self):
        """显示所有交易对的质量评分"""
        print("\n==== 质量评分排名 ====")
        print(f"{'交易对':<10} {'评分':<6} {'趋势':<8} {'回测':<8} {'相似模式':<12}")
        print("-" * 50)

        scores = []
        for symbol in self.config["TRADE_PAIRS"]:
            df = self.get_historical_data_with_cache(symbol)
            if df is None:
                continue

            df = calculate_optimized_indicators(df)
            quality_score, metrics = calculate_quality_score(df, self.client, symbol, None, self.config,
                                                             self.logger)

            trend = metrics.get("trend", "NEUTRAL")

            # 获取相似度信息
            similarity_info = self.similar_patterns_history.get(symbol, {"max_similarity": 0, "is_similar": False})
            similarity_pct = round(similarity_info["max_similarity"] * 100, 1) if similarity_info[
                "is_similar"] else 0

            scores.append((symbol, quality_score, trend, similarity_pct))

        # 按评分排序
        scores.sort(key=lambda x: x[1], reverse=True)

        for symbol, score, trend, similarity_pct in scores:
            backtest = "N/A"  # 回测暂未实现
            print(f"{symbol:<10} {score:<6.2f} {trend:<8} {backtest:<8} {similarity_pct:<12.1f}%")

        print("-" * 50)


def _save_position_history(self):
    """保存持仓历史到文件"""
    try:
        with open("position_history.json", "w") as f:
            json.dump(self.position_history, f, indent=4)
    except Exception as e:
        print(f"❌ 保存持仓历史失败: {e}")


def _load_position_history(self):
    """从文件加载持仓历史"""
    try:
        if os.path.exists("position_history.json"):
            with open("position_history.json", "r") as f:
                self.position_history = json.load(f)
        else:
            self.position_history = []
    except Exception as e:
        print(f"❌ 加载持仓历史失败: {e}")
        self.position_history = []


def analyze_position_statistics(self):
    """分析并显示持仓统计数据"""
    # 基本统计
    stats = {
        "total_trades": len(self.position_history),
        "winning_trades": 0,
        "losing_trades": 0,
        "total_profit": 0.0,
        "total_loss": 0.0,
        "avg_holding_time": 0.0,
        "symbols": {},
        "hourly_distribution": [0] * 24,  # 24小时
        "daily_distribution": [0] * 7,  # 周一到周日
    }

    holding_times = []

    for pos in self.position_history:
        profit = pos.get("profit_pct", 0)
        symbol = pos.get("symbol", "unknown")
        holding_time = pos.get("holding_time", 0)  # 小时

        # 按交易对统计
        if symbol not in stats["symbols"]:
            stats["symbols"][symbol] = {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "profit": 0.0,
                "loss": 0.0
            }

        stats["symbols"][symbol]["total"] += 1

        # 胜率与盈亏统计
        if profit > 0:
            stats["winning_trades"] += 1
            stats["total_profit"] += profit
            stats["symbols"][symbol]["wins"] += 1
            stats["symbols"][symbol]["profit"] += profit
        else:
            stats["losing_trades"] += 1
            stats["total_loss"] += abs(profit)
            stats["symbols"][symbol]["losses"] += 1
            stats["symbols"][symbol]["loss"] += abs(profit)

        # 时间统计
        if holding_time > 0:
            holding_times.append(holding_time)

        # 小时分布
        if "open_time" in pos:
            open_time = datetime.datetime.fromtimestamp(pos["open_time"])
            stats["hourly_distribution"][open_time.hour] += 1
            stats["daily_distribution"][open_time.weekday()] += 1

    # 计算平均持仓时间
    if holding_times:
        stats["avg_holding_time"] = sum(holding_times) / len(holding_times)

    # 计算胜率
    if stats["total_trades"] > 0:
        stats["win_rate"] = stats["winning_trades"] / stats["total_trades"] * 100
    else:
        stats["win_rate"] = 0

    # 计算盈亏比
    if stats["total_loss"] > 0:
        stats["profit_loss_ratio"] = stats["total_profit"] / stats["total_loss"]
    else:
        stats["profit_loss_ratio"] = float('inf')  # 无亏损

    # 计算每个交易对的胜率和平均盈亏
    for symbol, data in stats["symbols"].items():
        if data["total"] > 0:
            data["win_rate"] = data["wins"] / data["total"] * 100
            data["avg_profit"] = data["profit"] / data["wins"] if data["wins"] > 0 else 0
            data["avg_loss"] = data["loss"] / data["losses"] if data["losses"] > 0 else 0
            data["net_profit"] = data["profit"] - data["loss"]

    return stats


def generate_statistics_charts(self, stats):
    """生成统计图表"""
    import matplotlib.pyplot as plt
    import seaborn as sns
    from matplotlib.dates import DateFormatter

    # 确保目录存在
    charts_dir = "statistics_charts"
    if not os.path.exists(charts_dir):
        os.makedirs(charts_dir)

    # 设置样式
    plt.style.use('seaborn-v0_8-whitegrid')  # 使用兼容的样式

    # 1. 交易对胜率对比图
    plt.figure(figsize=(12, 6))
    symbols = list(stats["symbols"].keys())
    win_rates = [data["win_rate"] for data in stats["symbols"].values()]
    trades = [data["total"] for data in stats["symbols"].values()]

    # 按交易次数排序
    sorted_idx = sorted(range(len(trades)), key=lambda i: trades[i], reverse=True)
    symbols = [symbols[i] for i in sorted_idx]
    win_rates = [win_rates[i] for i in sorted_idx]
    trades = [trades[i] for i in sorted_idx]

    colors = ['green' if wr >= 50 else 'red' for wr in win_rates]

    if symbols:  # 确保有数据
        plt.bar(symbols, win_rates, color=colors)
        plt.axhline(y=50, color='black', linestyle='--', alpha=0.7)
        plt.xlabel('交易对')
        plt.ylabel('胜率 (%)')
        plt.title('各交易对胜率对比')
        plt.xticks(rotation=45)

        # 添加交易次数标签
        for i, v in enumerate(win_rates):
            plt.text(i, v + 2, f"{trades[i]}次", ha='center')

        plt.tight_layout()
        plt.savefig(f"{charts_dir}/symbol_win_rates.png")
    plt.close()

    # 2. 日内交易分布
    plt.figure(figsize=(12, 6))
    plt.bar(range(24), stats["hourly_distribution"])
    plt.xlabel('小时')
    plt.ylabel('交易次数')
    plt.title('日内交易时间分布')
    plt.xticks(range(24))
    plt.tight_layout()
    plt.savefig(f"{charts_dir}/hourly_distribution.png")
    plt.close()

    # 3. 每周交易分布
    plt.figure(figsize=(10, 6))
    days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    plt.bar(days, stats["daily_distribution"])
    plt.xlabel('星期')
    plt.ylabel('交易次数')
    plt.title('每周交易日分布')
    plt.tight_layout()
    plt.savefig(f"{charts_dir}/daily_distribution.png")
    plt.close()

    # 4. 交易对净利润对比
    plt.figure(figsize=(12, 6))
    sorted_symbols = sorted(stats["symbols"].items(), key=lambda x: x[1]["total"], reverse=True)
    net_profits = [data["net_profit"] for _, data in sorted_symbols]
    symbols_sorted = [s for s, _ in sorted_symbols]

    if symbols_sorted:  # 确保有数据
        colors = ['green' if np >= 0 else 'red' for np in net_profits]
        plt.bar(symbols_sorted, net_profits, color=colors)
        plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        plt.xlabel('交易对')
        plt.ylabel('净利润 (%)')
        plt.title('各交易对净利润对比')
        plt.xticks(rotation=45)
        plt.tight_layout()
    plt.savefig(f"{charts_dir}/symbol_net_profits.png")
    plt.close()

    # 5. 盈亏分布图
    if self.position_history:
        profits = [pos.get("profit_pct", 0) for pos in self.position_history]
        plt.figure(figsize=(12, 6))
        sns.histplot(profits, bins=20, kde=True)
        plt.axvline(x=0, color='red', linestyle='--', alpha=0.7)
        plt.xlabel('盈亏百分比 (%)')
        plt.ylabel('次数')
        plt.title('交易盈亏分布')
        plt.tight_layout()
        plt.savefig(f"{charts_dir}/profit_distribution.png")
    plt.close()


def generate_statistics_report(self, stats):
    """生成HTML统计报告"""
    report_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>交易统计报告 - {report_time}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1, h2, h3 {{ color: #333; }}
            .stat-card {{ background-color: #f9f9f9; border-radius: 5px; padding: 15px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .green {{ color: green; }}
            .red {{ color: red; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            tr:nth-child(even) {{ background-color: #f9f9f9; }}
            .chart-container {{ display: flex; flex-wrap: wrap; justify-content: space-between; }}
            .chart {{ width: 48%; margin-bottom: 20px; }}
            @media (max-width: 768px) {{ .chart {{ width: 100%; }} }}
        </style>
    </head>
    <body>
        <h1>交易统计报告</h1>
        <p>生成时间: {report_time}</p>

        <div class="stat-card">
            <h2>总体概览</h2>
            <table>
                <tr><th>指标</th><th>数值</th></tr>
                <tr><td>总交易次数</td><td>{stats['total_trades']}</td></tr>
                <tr><td>盈利交易</td><td>{stats['winning_trades']} ({stats['win_rate']:.2f}%)</td></tr>
                <tr><td>亏损交易</td><td>{stats['losing_trades']}</td></tr>
                <tr><td>总盈利</td><td class="green">{stats['total_profit']:.2f}%</td></tr>
                <tr><td>总亏损</td><td class="red">{stats['total_loss']:.2f}%</td></tr>
                <tr><td>净盈亏</td><td class="{('green' if stats['total_profit'] > stats['total_loss'] else 'red')}">{stats['total_profit'] - stats['total_loss']:.2f}%</td></tr>
                <tr><td>盈亏比</td><td>{stats['profit_loss_ratio']:.2f}</td></tr>
                <tr><td>平均持仓时间</td><td>{stats['avg_holding_time']:.2f} 小时</td></tr>
            </table>
        </div>

        <div class="stat-card">
            <h2>交易对分析</h2>
            <table>
                <tr>
                    <th>交易对</th>
                    <th>交易次数</th>
                    <th>胜率</th>
                    <th>平均盈利</th>
                    <th>平均亏损</th>
                    <th>净盈亏</th>
                </tr>
    """

    # 按交易次数排序
    sorted_symbols = sorted(stats["symbols"].items(), key=lambda x: x[1]["total"], reverse=True)

    for symbol, data in sorted_symbols:
        html += f"""
                <tr>
                    <td>{symbol}</td>
                    <td>{data['total']}</td>
                    <td>{data['win_rate']:.2f}%</td>
                    <td class="green">{data['avg_profit']:.2f}%</td>
                    <td class="red">{data['avg_loss']:.2f}%</td>
                    <td class="{('green' if data['net_profit'] >= 0 else 'red')}">{data['net_profit']:.2f}%</td>
                </tr>
        """

    html += """
            </table>
        </div>

        <div class="chart-container">
            <div class="chart">
                <h3>交易对胜率对比</h3>
                <img src="statistics_charts/symbol_win_rates.png" width="100%">
            </div>
            <div class="chart">
                <h3>交易对净利润对比</h3>
                <img src="statistics_charts/symbol_net_profits.png" width="100%">
            </div>
            <div class="chart">
                <h3>日内交易时间分布</h3>
                <img src="statistics_charts/hourly_distribution.png" width="100%">
            </div>
            <div class="chart">
                <h3>每周交易日分布</h3>
                <img src="statistics_charts/daily_distribution.png" width="100%">
            </div>
            <div class="chart">
                <h3>交易盈亏分布</h3>
                <img src="statistics_charts/profit_distribution.png" width="100%">
            </div>
        </div>
    </body>
    </html>
    """

    # 写入HTML文件
    with open("trading_statistics_report.html", "w") as f:
        f.write(html)

    print(f"✅ 统计报告已生成: trading_statistics_report.html")
    return "trading_statistics_report.html"


def show_statistics(self):
    """显示交易统计信息"""
    # 加载持仓历史
    self._load_position_history()

    if not self.position_history:
        print("⚠️ 没有交易历史记录，无法生成统计")
        return

    print(f"📊 生成交易统计，共 {len(self.position_history)} 条记录")

    # 分析数据
    stats = self.analyze_position_statistics()

    # 生成图表
    self.generate_statistics_charts(stats)

    # 生成报告
    report_file = self.generate_statistics_report(stats)

    # 显示简要统计
    print("\n===== 交易统计摘要 =====")
    print(f"总交易: {stats['total_trades']} 次")
    print(f"盈利交易: {stats['winning_trades']} 次 ({stats['win_rate']:.2f}%)")
    print(f"亏损交易: {stats['losing_trades']} 次")
    print(f"总盈利: {stats['total_profit']:.2f}%")
    print(f"总亏损: {stats['total_loss']:.2f}%")
    print(f"净盈亏: {stats['total_profit'] - stats['total_loss']:.2f}%")
    print(f"盈亏比: {stats['profit_loss_ratio']:.2f}")
    print(f"平均持仓时间: {stats['avg_holding_time']:.2f} 小时")
    print(f"详细报告: {report_file}")


def check_all_positions_status(self):
    """检查所有持仓状态，确认是否有任何持仓达到止盈止损条件，支持动态止盈止损"""
    self.load_existing_positions()

    if not self.open_positions:
        print("当前无持仓，状态检查完成")
        return

    print("\n===== 持仓状态检查 =====")
    positions_requiring_action = []

    for pos in self.open_positions:
        symbol = pos["symbol"]
        position_side = pos.get("position_side", "LONG")
        entry_price = pos["entry_price"]
        open_time = datetime.datetime.fromtimestamp(pos["open_time"]).strftime("%Y-%m-%d %H:%M:%S")

        try:
            # 获取当前价格
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])

            # 计算盈亏
            if position_side == "LONG":
                profit_pct = (current_price - entry_price) / entry_price
            else:
                profit_pct = (entry_price - current_price) / entry_price

            # 获取持仓特定的止盈止损设置
            take_profit = pos.get("dynamic_take_profit", 0.0175)  # 默认2.5%
            stop_loss = pos.get("stop_loss", -0.0125)  # 默认-1.75%

            status = "正常"
            action_needed = False

            if profit_pct >= take_profit:
                status = f"⚠️ 已达到止盈条件 ({profit_pct:.2%} >= {take_profit:.2%})"
                action_needed = True
            elif profit_pct <= stop_loss:
                status = f"⚠️ 已达到止损条件 ({profit_pct:.2%} <= {stop_loss:.2%})"
                action_needed = True

            holding_time = (time.time() - pos["open_time"]) / 3600

            print(f"{symbol} {position_side}: 开仓于 {open_time}, 持仓 {holding_time:.2f}小时")
            print(f"  入场价: {entry_price:.6f}, 当前价: {current_price:.6f}, 盈亏: {profit_pct:.2%}")
            print(f"  止盈: {take_profit:.2%}, 止损: {stop_loss:.2%}")
            print(f"  状态: {status}")

            if action_needed:
                positions_requiring_action.append((symbol, position_side, status))

        except Exception as e:
            print(f"检查 {symbol} 状态时出错: {e}")

    if positions_requiring_action:
        print("\n需要处理的持仓:")
        for symbol, side, status in positions_requiring_action:
            print(f"- {symbol} {side}: {status}")
    else:
        print("\n所有持仓状态正常，没有达到止盈止损条件")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='增强版交易机器人')
    parser.add_argument('--stats', action='store_true', help='生成交易统计报告')
    args = parser.parse_args()

    API_KEY = "R1rNhHUjRNZ2Qkrbl05Odc7GseGaVSPqr7l7NHsI0AUHtY6sM4C24wJW14c01m5B"
    API_SECRET = "AQPSTJN2CjfnvesLCdjKJffo5obacHqpMJIhtZPpoXwR40Ja90F03jSS9so5wJjW"

    bot = EnhancedTradingBot(API_KEY, API_SECRET, CONFIG)

    if args.stats:
        bot.show_statistics()
    else:
        bot.trade()