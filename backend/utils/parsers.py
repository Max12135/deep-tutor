"""
安全的解析工具
"""

import json
import logging

logger = logging.getLogger(__name__)


def safe_parse(data, default=None):
    """安全解析字符串为 Python 对象

    Args:
        data: 待解析的数据（可以是 str, dict, list 等）
        default: 解析失败时的默认值

    Returns:
        解析后的对象，或默认值
    """
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return data
    if not isinstance(data, str) or not data.strip():
        return default

    try:
        # 优先尝试 JSON 解析
        return json.loads(data)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse as JSON: {e}")
        return default


def safe_parse_ast(data, default=None):
    """使用 ast.literal_eval 安全解析字符串

    仅用于需要支持 Python 语法的情况（如布尔值、None 等）

    Args:
        data: 待解析的字符串
        default: 解析失败时的默认值

    Returns:
        解析后的对象，或默认值
    """
    if not isinstance(data, str) or not data.strip():
        return default

    try:
        import ast
        return ast.literal_eval(data)
    except (ValueError, SyntaxError) as e:
        logger.warning(f"Failed to parse with ast.literal_eval: {e}")
        return default
