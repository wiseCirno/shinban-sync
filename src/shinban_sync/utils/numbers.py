def parse_int(value: object, default: int | None = None) -> int:
    """把配置或报文里的数字转成 int。失败时返回 default，没有 default 就抛 ValueError。"""
    try:
        if isinstance(value, bool):
            raise TypeError
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            return int(value.strip())
        if isinstance(value, (bytes, bytearray)):
            return int(value)
        raise TypeError
    except (TypeError, ValueError):
        if default is not None:
            return default
        raise ValueError(f"无法解析整数: {value!r}") from None


def parse_float(value: object, default: float | None = None) -> float:
    try:
        if isinstance(value, bool):
            raise TypeError
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value.strip())
        raise TypeError
    except (TypeError, ValueError):
        if default is not None:
            return default
        raise ValueError(f"无法解析数字: {value!r}") from None
