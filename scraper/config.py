"""配置信息（无个人信息，可公开）

换学校/换平台时，改这里就够了，不需要动其他文件。
"""

# ── 校园卡平台 API ──
API_BASE = "https://mall.cc-pay.cn/api"
TRADES_URL = f"{API_BASE}/campus_card/trades"
USER_URL = f"{API_BASE}/user"

# ── 统一认证（CAS）SSO ──
# 学校统一认证的基地址；本仓库默认填的是一所高校的可用端点，
# 若你的学校使用其他地址，改成自己的即可。
SSO_BASE = "https://sso.buaa.edu.cn"
# 认证成功后要跳转到的业务地址（校园卡平台登录入口）
SSO_SERVICE_URL = "https://pass.cc-pay.cn/login"

# 请求间隔（秒）
REQUEST_INTERVAL = 0.5

# 每页大小
PAGE_SIZE = 200

# 数据文件路径（已在 .gitignore 中排除）
DB_PATH = "data/canteen.db"

# 日期范围（留空则使用合理的默认范围）
START_DATE = None
END_DATE = None
