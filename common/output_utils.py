"""
统一输出格式化工具模块
提供一致的控制台输出格式，包括标题、分隔线、状态提示等
"""

from typing import List, Optional
from colorama import Fore, Style, init

# 初始化colorama
init(autoreset=True)

# 格式化常量
SEPARATOR_CHAR = "—"
HEADER_LENGTH = 50
TITLE_LENGTH = 30


def print_header(title: str, char: str = SEPARATOR_CHAR, length: int = HEADER_LENGTH) -> None:
    """打印标题头"""
    if len(title) > length - 6:  # 为前后的字符留空间
        title = title[:length - 9] + "..."
    
    padding = (length - len(title) - 4) // 2
    header = f"{char * 2} {title} {char * (length - len(title) - 4 - padding)}"
    print(Fore.CYAN + header + Style.RESET_ALL)


def print_section(title: str) -> None:
    """打印章节标题"""
    print(f"\n{Fore.YELLOW}{SEPARATOR_CHAR * 2} {title} {SEPARATOR_CHAR * 2}{Style.RESET_ALL}")


def print_separator(char: str = "=", length: int = HEADER_LENGTH) -> None:
    """打印分隔线"""
    print(char * length)


def print_status(message: str, status: str = "INFO", color: Optional[str] = None) -> None:
    """打印状态消息"""
    color_map = {
        "SUCCESS": Fore.GREEN,
        "ERROR": Fore.RED,
        "WARNING": Fore.YELLOW,
        "INFO": Fore.CYAN,
        "DEBUG": Fore.MAGENTA
    }
    
    if color:
        # 如果直接指定颜色
        color_code = getattr(Fore, color.upper(), Fore.WHITE)
    else:
        # 根据状态选择颜色
        color_code = color_map.get(status.upper(), Fore.WHITE)
    
    print(f"{color_code}{message}{Style.RESET_ALL}")


def print_key_value(key: str, value: str, key_width: int = 20) -> None:
    """打印键值对"""
    formatted_key = f"{key}:".ljust(key_width)
    print(f"  {formatted_key} {value}")


def print_list_item(item: str, status: Optional[str] = None, indent: int = 2) -> None:
    """打印列表项"""
    spaces = " " * indent
    
    if status:
        color_map = {
            "online": Fore.GREEN,
            "offline": Fore.RED,
            "pending": Fore.YELLOW,
            "unknown": Fore.MAGENTA
        }
        color = color_map.get(status.lower(), Fore.WHITE)
        print(f"{spaces}{color}{item}{Style.RESET_ALL}")
    else:
        print(f"{spaces}{item}")


def print_progress_dots(count: int = 1) -> None:
    """打印进度点"""
    print("." * count, end="", flush=True)


def format_duration(seconds: float) -> str:
    """格式化时间长度"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}分{secs:.0f}秒"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}小时{minutes}分"


def format_timestamp(timestamp: float, format_type: str = "datetime") -> str:
    """格式化时间戳"""
    import time
    
    if timestamp <= 0:
        return "未知"
    
    if format_type == "datetime":
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
    elif format_type == "time":
        return time.strftime('%H:%M:%S', time.localtime(timestamp))
    elif format_type == "relative":
        now = time.time()
        diff = now - timestamp
        
        if diff < 60:
            return f"{int(diff)}秒前"
        elif diff < 3600:
            return f"{int(diff // 60)}分钟前"
        elif diff < 86400:
            return f"{int(diff // 3600)}小时前"
        else:
            return f"{int(diff // 86400)}天前"
    else:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))


def print_table_header(headers: List[str], widths: Optional[List[int]] = None) -> None:
    """打印表格头"""
    if not widths:
        widths = [15] * len(headers)
    
    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(Fore.CYAN + header_row + Style.RESET_ALL)
    print("-" * len(header_row))


def print_table_row(values: List[str], widths: Optional[List[int]] = None, colors: Optional[List[str]] = None) -> None:
    """打印表格行"""
    if not widths:
        widths = [15] * len(values)
    
    if not colors:
        colors = [Fore.WHITE] * len(values)
    
    row_parts = []
    for value, width, color in zip(values, widths, colors):
        colored_value = f"{color}{str(value).ljust(width)}{Style.RESET_ALL}"
        row_parts.append(colored_value)
    
    print("  ".join(row_parts))


def confirm_action(message: str, default: bool = False) -> bool:
    """确认操作"""
    suffix = " (Y/n)" if default else " (y/N)"
    response = input(f"{message}{suffix}: ").strip().lower()
    
    if not response:
        return default
    return response in ['y', 'yes', '是', '确认']


def input_with_default(prompt: str, default: str = "") -> str:
    """带默认值的输入"""
    if default:
        full_prompt = f"{prompt} (当前: {default}): "
    else:
        full_prompt = f"{prompt}: "
    
    result = input(full_prompt).strip()
    return result if result else default
