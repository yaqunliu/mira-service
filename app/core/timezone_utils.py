"""
时区工具模块
统一使用 Asia/Shanghai 时区处理所有时间相关操作
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# 应用时区：Asia/Shanghai
APP_TIMEZONE = ZoneInfo("Asia/Shanghai")


def now() -> datetime:
    """
    获取当前时间（Asia/Shanghai 时区）
    
    Returns:
        时区感知的当前时间（Asia/Shanghai）
    """
    return datetime.now(APP_TIMEZONE)


def today_start() -> datetime:
    """
    获取今天的开始时间（00:00:00，Asia/Shanghai 时区）
    
    Returns:
        今天 00:00:00 的时间（Asia/Shanghai）
    """
    now_dt = now()
    return now_dt.replace(hour=0, minute=0, second=0, microsecond=0)


def today_end() -> datetime:
    """
    获取今天的结束时间（次日 00:00:00，Asia/Shanghai 时区）
    
    Returns:
        明天 00:00:00 的时间（Asia/Shanghai）
    """
    return today_start() + timedelta(days=1)


def month_start() -> datetime:
    """
    获取本月的开始时间（1号 00:00:00，Asia/Shanghai 时区）
    
    Returns:
        本月1号 00:00:00 的时间（Asia/Shanghai）
    """
    now_dt = now()
    return now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def to_aware(dt: datetime) -> datetime:
    """
    将datetime转换为时区感知的datetime（Asia/Shanghai）
    
    如果datetime已经是时区感知的，则转换为Asia/Shanghai时区
    如果datetime是naive（无时区），则假设它是Asia/Shanghai时区并添加时区信息
    
    Args:
        dt: 要转换的datetime对象
        
    Returns:
        时区感知的datetime（Asia/Shanghai）
    """
    if dt.tzinfo is None:
        # naive datetime，假设是Asia/Shanghai时区
        return dt.replace(tzinfo=APP_TIMEZONE)
    else:
        # 已有时区信息，转换为Asia/Shanghai时区
        return dt.astimezone(APP_TIMEZONE)


def to_naive(dt: datetime) -> datetime:
    """
    将时区感知的datetime转换为naive datetime（移除时区信息）
    
    Args:
        dt: 时区感知的datetime对象
        
    Returns:
        naive datetime对象
    """
    if dt.tzinfo is None:
        return dt
    # 转换为Asia/Shanghai时区后再移除时区信息
    dt_shanghai = dt.astimezone(APP_TIMEZONE)
    return dt_shanghai.replace(tzinfo=None)
