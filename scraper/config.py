"""配置信息（无个人信息，可公开）"""

# API 配置
API_BASE = "https://mall.cc-pay.cn/api"
TRADES_URL = f"{API_BASE}/campus_card/trades"
USER_URL = f"{API_BASE}/user"

# 请求间隔（秒）
REQUEST_INTERVAL = 0.5

# 每页大小
PAGE_SIZE = 200

# 数据文件路径（已在 .gitignore 中排除）
DB_PATH = "data/canteen.db"

# 日期范围（留空则使用合理的默认范围）
START_DATE = None
END_DATE = None
