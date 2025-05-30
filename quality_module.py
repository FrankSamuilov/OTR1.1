import numpy as np
import pandas as pd
from data_module import get_historical_data
from indicators_module import calculate_optimized_indicators, get_smc_trend_and_duration, find_swing_points, \
    calculate_fibonacci_retracements


def calculate_quality_score(df, client=None, symbol=None, btc_df=None, config=None, logger=None):
    """
    计算0-10分的货币质量评分，10分表示低风险
    基于SMC策略（Smart Money Concept）和风险参数
    增强版：添加指标共振与交互性评估

    参数:
        df (DataFrame): 包含价格和计算指标的数据
        client: Binance客户端（可选）
        symbol: 交易对符号（可选）
        btc_df: BTC数据（可选，用于市场情绪评估）
        config: 配置对象（可选）
        logger: 日志对象（可选）

    返回:
        quality_score (float): 0-10分的质量评分
        metrics (dict): 计算过程中的指标明细
    """
    # 创建指标字典用于返回
    metrics = {}

    # 防御性检查
    if df is None or len(df) < 20:
        if logger:
            logger.warning(f"{symbol}数据不足，无法计算质量评分")
        print(f"⚠️ {symbol}数据不足，无法计算质量评分")
        return 0.0, {'error': 'insufficient_data'}

    # 基本风险评估 (3分)
    risk_score = 3.0
    print(f"📊 {symbol} - 基础风险评分: {risk_score}")

    # 1. 市场结构评估 (SMC核心) - 最高2分
    trend, duration, trend_info = get_smc_trend_and_duration(df, config, logger)
    metrics['trend'] = trend
    metrics['duration'] = duration
    print(f"📈 {symbol} - 市场趋势: {trend}, 持续时间: {duration}分钟")

    # 稳定上升趋势得高分
    if trend == "UP" and duration > 30:  # 缩短时间要求，从60分钟减至30分钟
        structure_score = 2.0
        print(f"✅ {symbol} - 稳定上升趋势，结构评分: 2.0")
    elif trend == "UP":
        structure_score = 1.5
        print(f"✅ {symbol} - 上升趋势，结构评分: 1.5")
    elif trend == "NEUTRAL":
        structure_score = 1.0
        print(f"⚖️ {symbol} - 中性趋势，结构评分: 1.0")
    elif trend == "DOWN" and duration > 30:  # 缩短时间要求
        structure_score = 0.5  # 风险较高
        print(f"⚠️ {symbol} - 明显下降趋势，结构评分: 0.5")
    else:
        structure_score = 0.8
        print(f"⚠️ {symbol} - 不明确趋势，结构评分: 0.8")
    metrics['structure_score'] = structure_score

    # 2. 订单块和流动性评估 - 最高2分
    try:
        # 成交量评估
        volume_mean = df['volume'].rolling(20).mean().iloc[-1]
        recent_volume = df['volume'].iloc[-1]
        volume_ratio = recent_volume / volume_mean if volume_mean > 0 else 1.0
        print(f"📊 {symbol} - 成交量比率: {volume_ratio:.2f}")

        # OBV趋势评估
        obv_trend = df['OBV'].iloc[-1] > df['OBV'].iloc[-5] if 'OBV' in df.columns and len(df) >= 5 else False
        print(f"📊 {symbol} - OBV趋势{'上升' if obv_trend else '下降'}")

        # ATR评估 - 波动率
        atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else 0
        atr_mean = df['ATR'].rolling(20).mean().iloc[-1] if 'ATR' in df.columns else 1
        atr_ratio = atr / atr_mean if atr_mean > 0 else 1.0
        print(f"📊 {symbol} - 波动率比率: {atr_ratio:.2f}")

        # 超级趋势评估
        supertrend_aligned = False
        if 'Supertrend_Direction' in df.columns:
            st_direction = df['Supertrend_Direction'].iloc[-1]
            supertrend_aligned = (st_direction > 0 and trend == "UP") or (st_direction < 0 and trend == "DOWN")
            print(
                f"📊 {symbol} - 超级趋势方向: {'上升' if st_direction > 0 else '下降'}, 与趋势一致: {supertrend_aligned}")

        # 订单块评估
        has_order_block = (volume_ratio > 1.3 and
                           abs(df['close'].iloc[-1] - df['close'].iloc[-2]) < atr)
        print(f"📊 {symbol} - 订单块检测: {'有' if has_order_block else '无'}")

        metrics['volume_ratio'] = volume_ratio
        metrics['atr_ratio'] = atr_ratio
        metrics['has_order_block'] = has_order_block
        metrics['supertrend_aligned'] = supertrend_aligned

        # 订单块评分
        if has_order_block and obv_trend and supertrend_aligned:
            order_block_score = 2.0
            print(f"✅ {symbol} - 订单块+OBV+超级趋势完美匹配，评分: 2.0")
        elif has_order_block and (obv_trend or supertrend_aligned):
            order_block_score = 1.5
            print(f"✅ {symbol} - 订单块部分匹配，评分: 1.5")
        elif has_order_block or obv_trend:
            order_block_score = 1.0
            print(f"⚖️ {symbol} - 有订单块或OBV趋势，评分: 1.0")
        elif volume_ratio > 0.8:
            order_block_score = 0.7
            print(f"⚠️ {symbol} - 成交量尚可，评分: 0.7")
        else:
            order_block_score = 0.5
            print(f"⚠️ {symbol} - 订单块评估不佳，评分: 0.5")

        # 波动性降分
        if atr_ratio > 1.5:  # 波动性高于平均的50%
            order_block_score *= 0.7  # 降低30%的评分
            print(f"⚠️ {symbol} - 波动性过高，订单块评分降至: {order_block_score:.2f}")

        metrics['order_block_score'] = order_block_score
    except Exception as e:
        if logger:
            logger.error(f"{symbol}订单块评估出错: {e}")
        order_block_score = 0.5
        metrics['order_block_error'] = str(e)
        print(f"❌ {symbol} - 订单块评估出错: {e}")

    # 3. 支撑阻力评估 - 最高2分
    try:
        swing_highs, swing_lows = find_swing_points(df)
        fib_levels = calculate_fibonacci_retracements(df)

        print(f"📊 {symbol} - 发现摆动高点: {len(swing_highs)}个, 摆动低点: {len(swing_lows)}个")
        if fib_levels:
            print(f"📊 {symbol} - 斐波那契水平: {[round(level, 4) for level in fib_levels[:3]]}...")

        current_price = df['close'].iloc[-1]

        # 确定当前支撑位和阻力位
        if len(swing_lows) >= 2:
            current_support = min(swing_lows[-1], swing_lows[-2])
        else:
            current_support = df['low'].min()

        if len(swing_highs) >= 2:
            current_resistance = max(swing_highs[-1], swing_highs[-2])
        else:
            current_resistance = df['high'].max()

        # 计算价格与支撑/阻力的距离
        support_distance = (current_price - current_support) / current_price
        resistance_distance = (current_resistance - current_price) / current_price

        print(f"📊 {symbol} - 距离支撑位: {support_distance:.2%}, 距离阻力位: {resistance_distance:.2%}")

        # 检查价格与斐波那契回撤位的位置
        near_fib_support = False
        fib_support_level = 0

        if fib_levels and len(fib_levels) >= 3:  # 确保有足够的斐波那契水平
            # 检查价格是否接近任何斐波那契支撑位
            for i, level in enumerate(fib_levels):
                if abs(current_price - level) / current_price < 0.01:  # 1%以内视为接近
                    near_fib_support = True
                    fib_support_level = i
                    print(f"✅ {symbol} - 价格接近斐波那契水平 {i}: {level:.4f}")
                    break

        metrics['support_distance'] = support_distance
        metrics['resistance_distance'] = resistance_distance
        metrics['near_fib_support'] = near_fib_support
        metrics['fib_support_level'] = fib_support_level

        # 支撑阻力评分
        if near_fib_support:
            # 黄金分割较高位置得分更高
            sr_score = 2.0 - (fib_support_level * 0.3)  # 0.382得2.0分，0.618得1.7分
            print(f"✅ {symbol} - 价格位于黄金分割位置，支撑阻力评分: {sr_score:.2f}")
        elif support_distance < 0.01 and resistance_distance > 0.05:
            # 接近支撑且远离阻力
            sr_score = 1.8
            print(f"✅ {symbol} - 价格接近支撑且远离阻力，支撑阻力评分: 1.8")
        elif support_distance < 0.03:
            # 相对接近支撑
            sr_score = 1.5
            print(f"✅ {symbol} - 价格相对接近支撑，支撑阻力评分: 1.5")
        elif resistance_distance < 0.03:
            # 相对接近阻力
            sr_score = 0.8
            print(f"⚠️ {symbol} - 价格接近阻力，支撑阻力评分: 0.8")
        else:
            # 处于中间位置
            sr_score = 1.0
            print(f"⚖️ {symbol} - 价格处于中间位置，支撑阻力评分: 1.0")

        metrics['sr_score'] = sr_score
    except Exception as e:
        if logger:
            logger.error(f"{symbol}支撑阻力评估出错: {e}")
        sr_score = 1.0
        metrics['sr_error'] = str(e)
        print(f"❌ {symbol} - 支撑阻力评估出错: {e}")

    # 4. 技术指标评估 - 最高2分
    try:
        # MACD
        macd = df['MACD'].iloc[-1] if 'MACD' in df.columns else 0
        macd_signal = df['MACD_signal'].iloc[-1] if 'MACD_signal' in df.columns else 0
        macd_cross = macd > macd_signal

        # 检查是否是最近的交叉
        macd_recent_cross = False
        if len(df) >= 3 and 'MACD' in df.columns and 'MACD_signal' in df.columns:
            if (macd > macd_signal and
                    df['MACD'].iloc[-2] <= df['MACD_signal'].iloc[-2]):
                macd_recent_cross = True
                print(f"📊 {symbol} - MACD最近发生金叉")
            elif (macd < macd_signal and
                  df['MACD'].iloc[-2] >= df['MACD_signal'].iloc[-2]):
                macd_recent_cross = True
                print(f"📊 {symbol} - MACD最近发生死叉")

        print(f"📊 {symbol} - MACD: {macd:.6f}, Signal: {macd_signal:.6f}, 金叉: {macd_cross}")

        # RSI
        rsi = df['RSI'].iloc[-1] if 'RSI' in df.columns else 50
        rsi_healthy = 30 <= rsi <= 70
        print(f"📊 {symbol} - RSI: {rsi:.2f}, 健康区间: {rsi_healthy}")

        # 均线
        ema5 = df['EMA5'].iloc[-1] if 'EMA5' in df.columns else 0
        ema20 = df['EMA20'].iloc[-1] if 'EMA20' in df.columns else 0
        price_above_ema = df['close'].iloc[-1] > ema20

        # 均线交叉检查
        ema_cross = False
        if len(df) >= 3 and 'EMA5' in df.columns and 'EMA20' in df.columns:
            if (ema5 > ema20 and
                    df['EMA5'].iloc[-2] <= df['EMA20'].iloc[-2]):
                ema_cross = True
                print(f"📊 {symbol} - 短期均线上穿长期均线（金叉）")
            elif (ema5 < ema20 and
                  df['EMA5'].iloc[-2] >= df['EMA20'].iloc[-2]):
                ema_cross = True
                print(f"📊 {symbol} - 短期均线下穿长期均线（死叉）")

        print(f"📊 {symbol} - EMA5: {ema5:.4f}, EMA20: {ema20:.4f}, 价格高于EMA20: {price_above_ema}")

        # 布林带
        bb_width = (df['BB_Upper'].iloc[-1] - df['BB_Lower'].iloc[-1]) / df['BB_Middle'].iloc[-1] if all(
            x in df.columns for x in ['BB_Upper', 'BB_Lower', 'BB_Middle']) else 0.1

        # 布林带位置
        if 'BB_Upper' in df.columns and 'BB_Lower' in df.columns and 'BB_Middle' in df.columns:
            bb_position = (df['close'].iloc[-1] - df['BB_Lower'].iloc[-1]) / (
                        df['BB_Upper'].iloc[-1] - df['BB_Lower'].iloc[-1])
            bb_position_text = (
                "上轨以上" if bb_position > 1 else
                "上轨附近" if bb_position > 0.9 else
                "上轨和中轨之间" if bb_position > 0.5 else
                "中轨附近" if bb_position > 0.45 and bb_position < 0.55 else
                "中轨和下轨之间" if bb_position > 0.1 else
                "下轨附近" if bb_position > 0 else
                "下轨以下"
            )
            print(f"📊 {symbol} - 布林带位置: {bb_position:.2f} ({bb_position_text})")
            metrics['bb_position'] = bb_position
            metrics['bb_position_text'] = bb_position_text

        print(f"📊 {symbol} - 布林带宽度: {bb_width:.4f}")

        metrics['macd_cross'] = macd_cross
        metrics['macd_recent_cross'] = macd_recent_cross
        metrics['rsi'] = rsi
        metrics['rsi_healthy'] = rsi_healthy
        metrics['price_above_ema'] = price_above_ema
        metrics['ema_cross'] = ema_cross
        metrics['bb_width'] = bb_width

        # 技术指标评分
        tech_score = 0.0

        # MACD交叉向上且RSI健康 +1.0
        if macd_cross and rsi_healthy:
            tech_score += 1.0
            print(f"✅ {symbol} - MACD金叉+RSI健康，技术加分: +1.0")
        # RSI健康但无交叉 +0.6
        elif rsi_healthy:
            tech_score += 0.6
            print(f"✅ {symbol} - RSI健康，技术加分: +0.6")
        # RSI超买或超卖 -0.2
        else:
            tech_score -= 0.2
            print(f"⚠️ {symbol} - RSI超买或超卖，技术减分: -0.2")

        # 价格在均线上方 +0.5
        if price_above_ema:
            tech_score += 0.5
            print(f"✅ {symbol} - 价格在均线上方，技术加分: +0.5")

        # 考虑布林带宽度 (标准情况下分值0.5，宽度越小越好)
        if bb_width < 0.03:  # 非常紧缩，可能即将突破
            tech_score += 0.5
            print(f"✅ {symbol} - 布林带紧缩，技术加分: +0.5")
        elif bb_width < 0.06:  # 较紧缩
            tech_score += 0.3
            print(f"✅ {symbol} - 布林带较紧缩，技术加分: +0.3")
        elif bb_width > 0.08:  # 较宽，波动较大
            tech_score -= 0.2
            print(f"⚠️ {symbol} - 布林带过宽，技术减分: -0.2")

        # Vortex指标评估 - 虚拟货币市场优化
        if 'VI_plus' in df.columns and 'VI_minus' in df.columns:
            vi_plus = df['VI_plus'].iloc[-1]
            vi_minus = df['VI_minus'].iloc[-1]
            vi_diff = df['VI_diff'].iloc[-1]

            # Vortex趋势方向是否与总体趋势一致
            vortex_trend_aligned = (vi_plus > vi_minus and trend == "UP") or (vi_plus < vi_minus and trend == "DOWN")

            # 趋势强度评估 - 针对虚拟货币波动性调整
            trend_strength = abs(vi_diff) * 10  # 放大差值

            print(f"📊 {symbol} - Vortex趋势指示: {'上升' if vi_plus > vi_minus else '下降'}, "
                  f"与主趋势一致: {vortex_trend_aligned}, 强度: {trend_strength:.2f}")

            # 记录指标值
            metrics['vortex_plus'] = float(vi_plus)
            metrics['vortex_minus'] = float(vi_minus)
            metrics['vortex_diff'] = float(vi_diff)
            metrics['vortex_aligned'] = vortex_trend_aligned
            metrics['vortex_strength'] = float(trend_strength)

            # 根据Vortex指标调整技术评分
            if vortex_trend_aligned:
                # 虚拟货币趋势一致性更重要，加大分数
                tech_score += 0.4
                print(f"✅ {symbol} - Vortex指标与主趋势一致，技术加分: +0.4")

                # 额外考虑趋势强度
                if trend_strength > 1.5:
                    tech_score += 0.2
                    print(f"✅ {symbol} - Vortex趋势强度高 ({trend_strength:.2f})，额外加分: +0.2")

            # 如果Vortex刚刚发生交叉，增加更多分数
            vortex_cross_up = df['Vortex_Cross_Up'].iloc[-1] if 'Vortex_Cross_Up' in df.columns else 0
            vortex_cross_down = df['Vortex_Cross_Down'].iloc[-1] if 'Vortex_Cross_Down' in df.columns else 0

            metrics['vortex_cross_up'] = bool(vortex_cross_up)
            metrics['vortex_cross_down'] = bool(vortex_cross_down)

            if (vortex_cross_up and trend == "UP") or (vortex_cross_down and trend == "DOWN"):
                # 虚拟货币交叉信号更有价值，加大分数
                tech_score += 0.5
                print(f"✅ {symbol} - Vortex指标刚刚发生与趋势一致的交叉，重要信号加分: +0.5")

        # 确保在范围内
        tech_score = max(0.0, min(2.0, tech_score))
        print(f"📊 {symbol} - 最终技术指标评分: {tech_score:.2f}")
        metrics['tech_score'] = tech_score
    except Exception as e:
        if logger:
            logger.error(f"{symbol}技术指标评估出错: {e}")
        tech_score = 0.8
        metrics['tech_error'] = str(e)
        print(f"❌ {symbol} - 技术指标评估出错: {e}")

    # 5. 市场情绪评估 - 最高1分
    try:
        market_score = 0.5  # 默认中性
        print(f"📊 {symbol} - 默认市场情绪评分: 0.5")

        # 如果提供了BTC数据，评估整体市场情绪
        if btc_df is not None and len(btc_df) > 5:
            btc_change = (btc_df['close'].iloc[-1] - btc_df['close'].iloc[-5]) / btc_df['close'].iloc[-5]
            print(f"📊 {symbol} - BTC变化率: {btc_change:.2%}")

            if btc_change > 0.02:  # BTC上涨超过2%
                market_score = 1.0
                print(f"✅ {symbol} - BTC强势上涨，市场情绪评分: 1.0")
            elif btc_change > 0.005:  # BTC小幅上涨
                market_score = 0.8
                print(f"✅ {symbol} - BTC小幅上涨，市场情绪评分: 0.8")
            elif btc_change < -0.02:  # BTC下跌超过2%
                market_score = 0.2
                print(f"⚠️ {symbol} - BTC强势下跌，市场情绪评分: 0.2")
            elif btc_change < -0.005:  # BTC小幅下跌
                market_score = 0.3
                print(f"⚠️ {symbol} - BTC小幅下跌，市场情绪评分: 0.3")

        # 如果提供了客户端和符号，也可以查看期货资金费率
        if client and symbol:
            try:
                funding_rate = float(client.futures_mark_price(symbol=symbol)['lastFundingRate'])
                print(f"📊 {symbol} - 资金费率: {funding_rate:.6f}")

                # 负的资金费率通常对做多有利
                if funding_rate < -0.0002:  # 明显为负
                    market_score += 0.1
                    print(f"✅ {symbol} - 负资金费率，市场情绪加分: +0.1")
                elif funding_rate > 0.0002:  # 明显为正
                    market_score -= 0.1
                    print(f"⚠️ {symbol} - 正资金费率，市场情绪减分: -0.1")
            except:
                pass  # 忽略资金费率获取错误

        metrics['market_score'] = market_score
    except Exception as e:
        if logger:
            logger.error(f"{symbol}市场情绪评估出错: {e}")
        market_score = 0.5
        metrics['market_error'] = str(e)
        print(f"❌ {symbol} - 市场情绪评估出错: {e}")

    # 震荡市场检测与降分
    is_ranging = False
    if 'ADX' in df.columns:
        adx = df['ADX'].iloc[-1]
        if adx < 20:
            is_ranging = True
            # 震荡市场降分
            quality_penalty = 2.0  # 在震荡市场降低2分
            print(f"⚠️ {symbol} - 检测到震荡市场 (ADX: {adx:.2f} < 20)，评分惩罚: -2.0")
            metrics['is_ranging'] = True
            metrics['adx_value'] = adx
        else:
            print(f"📊 {symbol} - ADX: {adx:.2f} >= 20，非震荡市场")


    # 汇总得分
    quality_score = risk_score + structure_score + order_block_score + sr_score + tech_score + market_score

    # 对震荡市场进行惩罚
    if is_ranging:
        quality_score = max(0.0, quality_score - 2.0)

    # 对趋势不明确的市场降分
    if trend == "NEUTRAL":
        quality_score *= 0.8
        print(f"⚠️ {symbol} - 趋势不明确，总评分乘以0.8")

    # 确保最终分数在0-10范围内
    quality_score = max(0.0, min(10.0, quality_score))

    # 记录所有评分组成
    metrics['risk_score'] = risk_score
    metrics['final_score'] = quality_score

    print(f"🏆 {symbol} - 最终质量评分: {quality_score:.2f}")
    print(
        f"组成: 风险({risk_score}) + 结构({structure_score}) + 订单块({order_block_score}) + 支撑阻力({sr_score}) + 技术({tech_score}) + 市场({market_score})")

    if logger:
        logger.info(f"{symbol}质量评分: {quality_score:.2f}", extra=metrics)

    return quality_score, metrics


def detect_pattern_similarity(df, historical_dfs, window_length=10, similarity_threshold=0.8, logger=None):
    """
    检测当前市场模式与历史模式的相似度

    参数:
        df (DataFrame): 当前市场数据
        historical_dfs (list): 历史数据框列表，每个元素都是包含时间戳的DataFrame
        window_length (int): 比较窗口长度，默认10
        similarity_threshold (float): 相似度阈值
        logger: 日志对象（可选）

    返回:
        similarity_info (dict): 包含最高相似度和相应时间的信息
    """
    if df is None or len(df) < window_length:
        return {'max_similarity': 0, 'similar_time': None, 'is_similar': False}

    # 提取当前模式特征
    try:
        # 使用价格变化率作为特征，减少绝对价格的影响
        current_pattern = []
        for i in range(1, window_length):
            # 使用收盘价变化率
            change_rate = df['close'].iloc[-i] / df['close'].iloc[-i - 1] - 1
            current_pattern.append(change_rate)

        current_pattern = np.array(current_pattern)

        # 寻找最相似的历史模式
        max_similarity = 0
        similar_time = None

        for hist_df in historical_dfs:
            if hist_df is None or len(hist_df) < window_length + 1:
                continue

            # 对每个可能的窗口计算相似度
            for i in range(len(hist_df) - window_length):
                hist_pattern = []
                for j in range(1, window_length):
                    hist_change_rate = hist_df['close'].iloc[i + j] / hist_df['close'].iloc[i + j - 1] - 1
                    hist_pattern.append(hist_change_rate)

                hist_pattern = np.array(hist_pattern)

                # 计算欧几里得距离
                if len(hist_pattern) == len(current_pattern):
                    distance = np.sqrt(np.sum((current_pattern - hist_pattern) ** 2))
                    # 最大可能距离（假设每个点变化率相差2, 即一个+100%一个-100%）
                    max_distance = np.sqrt(window_length * 4)
                    # 归一化为相似度
                    similarity = 1 - (distance / max_distance)

                    if similarity > max_similarity:
                        max_similarity = similarity
                        # 获取这个窗口的时间
                        if 'time' in hist_df.columns:
                            similar_time = hist_df['time'].iloc[i]
                        else:
                            similar_time = f"索引位置 {i}"

        # 是否达到相似度阈值
        is_similar = max_similarity >= similarity_threshold

        similarity_info = {
            'max_similarity': max_similarity,
            'similar_time': similar_time,
            'is_similar': is_similar
        }

        return similarity_info
    except Exception as e:
        if logger:
            logger.error(f"模式相似度检测出错: {e}")
        return {'max_similarity': 0, 'similar_time': None, 'is_similar': False, 'error': str(e)}


def adjust_quality_for_similarity(quality_score, similarity_info, adjustment_factor=0.1):
    """
    根据相似度信息调整质量评分

    参数:
        quality_score (float): 初始质量评分
        similarity_info (dict): 相似度信息
        adjustment_factor (float): 调整因子，默认0.1（10%）

    返回:
        adjusted_score (float): 调整后的评分
    """
    if not similarity_info['is_similar']:
        return quality_score

    # 对于高相似度，降低风险偏差，即提高评分
    similarity = similarity_info['max_similarity']
    adjustment = quality_score * adjustment_factor * (similarity - 0.8) / 0.2

    # 调整评分，但确保不超过10
    adjusted_score = min(10.0, quality_score + adjustment)

    return adjusted_score