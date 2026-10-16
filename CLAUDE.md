# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

北航食堂消费分析系统（对外称 Dining Trace / 干饭指北）— 通过 SSO 统一认证自动爬取校园卡食堂消费记录，以交互式可视化仪表盘展示分析结果。核心数据来自第三方校园卡平台（pass.cc-pay.cn / mall.cc-pay.cn），**服务端行为不受本项目控制且曾多次变化**。

> 对外材料（README、界面文案、截图文案）一律**不出现校名**，统一用「校园统一认证」「校园卡平台」等中性说法；SSO 端点集中在 `scraper/config.py`，方便换学校。

## Launch

```bash
# 推荐方式：双击 start.bat，浏览器中 SSO 登录后自动拉取数据并展示
streamlit run app.py

# 或命令行先拉取数据再启动（调试用）
python fetch_data.py --stu-no 学号      # 拉取（密码交互输入）
python fetch_data.py --stats           # 查看各学号本地数据范围/统计（快速验证拉取是否成功）
```

注意：**双击 .py 文件会闪退是正常的**（无 pause），日常使用走 start.bat 或命令行。

## Project Structure

```
├── app.py              # Streamlit 可视化面板（入口，含登录+PK加载对手）
├── fetch_data.py       # 命令行入口（拉取/查看统计）
├── start.bat           # Windows 一键启动
├── requirements.txt    # 依赖
├── LICENSE             # MIT
├── README.md           # 面向用户的项目说明
├── CLAUDE.md           # 面向 AI 助手的开发指引（本文件）
├── .github/workflows/  # CI：跑两个冒烟测试 + 检查隐私文件
├── docs/screenshots/   # README 配图
├── tools/              # 开发辅助脚本（不参与运行）
│   ├── smoke_test.py       # 数据变换逻辑冒烟测试（不依赖 Streamlit）
│   └── app_smoke_test.py   # app.py 无头集成测试（mock streamlit）
├── data/               # 本地数据库 + cookies（gitignored，含真实个人信息）
└── archive/            # 开发过程材料（gitignored，含真实学号/姓名/报告）
    ├── 历史对话.txt
    ├── 方法一结果.txt
    ├── 错误截图.png
    ├── *.docx          # 课程要求原件 + 实验报告
    └── pycache/        # 旧字节码
```

**两个 gitignored 目录都必须保持忽略**：`data/`（真实消费记录与登录凭据）与 `archive/`（含真实学号、姓名、对话记录）。任何时候都不要 `git add -f` 它们。

## Architecture

**数据流：** SSO 登录 → 获取 Cookie → 调用 mall.cc-pay.cn API → 存入 SQLite → Pandas 分析 → Plotly 图表 → Streamlit 展示

- **app.py** 集成完整 SSO 登录 + 数据拉取：用户在浏览器输入学号密码即完成全流程；PK 擂台页可再登录一个"对手"学号。5 个标签页：消费总览、食堂分析、时间分析、随机推荐、PK 对战
- **scraper/sso_login.py** 校园 CAS 协议自动登录（通用实现，端点读 `config.SSO_BASE`）：GET 登录页提 `execution` → POST → 手动跟随 302 链收 Cookie；已有 TGT(CASTGC) 时登录页直接 302，此时跳过表单直接跟链
- **scraper/fetcher.py** 封装校园卡平台 REST API：分页、去重、失败自动重试（网络抖动/被拒 3 次，间隔 2-4s 随机）
- **scraper/database.py** 所有查询带可选 `stu_no` 实现多用户隔离；transactions 以 `UNIQUE(date, amount, mer_name, balance, tx_name, stu_no)` 去重
- **fetch_data.py** `--stu-no`（拉取）、`--stats`（统计）两命令；**scraper/cli.py** 提供等价 argparse 版

## 返回值契约（重要）

`scraper/sso_login.py::sso_fetch_and_save()` 与 `scraper/fetcher.py::fetch_and_save()` 均返回 dict：
`{"ok": bool, "message": str, "stats": dict|None, "inserted": int, "skipped": int}`。
登录失败原因在 `SSOLogin.last_error`，`message` 会包含具体原因（密码错误/频繁/验证页截断）。
**调用方（app.py 的 `sso_login()` 包装、fetch_data.py、cli.py）必须按 dict 使用**——不要改成返回 None/布尔，否则 UI 错误提示会失效。

## 服务器端风控与韧性设计（2026-09 排查结论，重要）

校园卡平台 / 校方网关在 2026 年夏加入了反爬风控（cookie 出现 `_zte_cid_`/`_zte_sid_`/`insert_cookie` 等标记），表现为：

- **登录链偶发被"验证页"截断**：SSO POST 后跟 302 链时，某跳返回 200 验证页（而非继续 302），链结束于未达 cc-pay。判定成功的标准是拿到 **`.cc-pay.cn` 域的 `connect.sid`**；只有 6 个左右 SSO 域 cookie（CASTGC/_zte_*）即失败。`login()` 对此自动重试最多 3 次（间隔随机 2-4s）
- **连续快速登录会触发限流/会话撤销**：短时间多次登录（多账号/多次点击）后，新会话可能立刻被服务器标记，`/api/user` 与 trades 都返回 401。界面操作间应留间隔；fetch 阶段失败会间隔 3-5s 自动重新登录一次
- **用户名密码错误/限流/需验证码等确定性失败绝不重试**（`SSOLogin.FATAL_ERR_KEYWORDS`）——重试会放大风控甚至锁号
- **会话存活期很短**：设计上每次使用都全新登录（app 不持久复用 cookie）；`data/cookies_*.txt` 仅调试用
- 登录成功后程序随机等待 1-2s 再打接口，降低刚登录即被误判的概率

## Key Technical Details

- **API 信封：** 响应 `{"success": bool, "type": 200|401, "message": str, "data": {...}}`。401 典型值：`{"success":false,"type":401,"message":"用户验证失败: 需要用户登录","sub_type":"4000011"}`——fetcher 遇 type 401/403 不重试直接上报
- **trades 接口：** `https://mall.cc-pay.cn/api/campus_card/trades`，参数 `pageNum`、`pageSize`（≤200）、`minTsCreation`/`maxTsCreation`（UTC，"当天16:00Z" = 北京时间次日 0 点）、`tradeType=all`、`stuNo`；金额单位 分，负值 = 消费
- **拉取窗口：** 默认全量从 `2024-01-01` 起（fetcher 内 `min_ts` 兜底值），**增量更新靠数据库 UNIQUE 去重而非时间窗口**；`data.count` 字段不可靠（曾出现 count=0 但有数据），翻页终止依赖"当页 < pageSize"
- **Cookie 处理：** 直接设 `session.headers["Cookie"]` 平铺字符串而非 CookieJar（避免 URL 编码值触发 http.client latin-1 异常）；平铺串含 sso 域 cookie 无害，cc-pay 只看 connect.sid
- **故障排查快速路径：** ① `python fetch_data.py --stats` 看该学号数据最新日期是否推进；② 检查 `data/cookies_*.txt` 是否含 `connect.sid` 判断登录链成败；③ 若怀疑服务端又变了，写一次性脚本做**全新登录 + 逐步打印每跳 status/Location/Set-Cookie**，用实时会话直接打两个 API 对比（不要拿旧 cookie 文件测，会话早已失效）
- **Windows GBK 编码：** 终端 print 中文用 `_print()` 捕获 `UnicodeEncodeError` 回退 ASCII；PowerShell 下 python 输出建议 `PYTHONIOENCODING=utf-8` 或重定向到 UTF-8 文件再读，避免乱码与 UTF-16 陷阱
- **隐私保护：** 代码无任何个人信息；`data/*.db`、`data/cookies*.txt` 在 `.gitignore`；学号显示 `前4位****`。**分享项目给他人前必须删除 data/ 下的 db 与 cookies**（含真实消费记录与姓名）

## Dependencies

- requests, streamlit, plotly, pandas（无版本锁定，兼容最新版；start.bat 首次运行自动 pip install）

## Testing

```bash
python tools/smoke_test.py       # 数据变换逻辑（pandas 版本兼容性）
python tools/app_smoke_test.py   # app.py 无头集成测试（mock streamlit）
```

两个脚本都用**合成数据**，不联网、不读用户的 `data/canteen.db`，改完代码应保持全绿。
CI（`.github/workflows/smoke.yml`）在每次 push/PR 时跑它们，并额外检查 `data/`、`archive/` 没有混进版本库。

## Streamlit 的两个坑（改代码前必读）

1. **模块级代码只在进程首轮执行。** `import app` 被 `sys.modules` 缓存，Streamlit 后续每次交互只是重跑脚本主体，不会重跑 `import`。所以任何"每轮都要生效"的初始化都必须放在 `main()` 里调用（`init_session()` 就是这么处理的，且必须保持幂等）。否则新开的浏览器会话会报 `AttributeError: st.session_state has no attribute "logged_in"`。
2. **会话状态可能只剩一半。** 代码热重载后 `st.session_state` 里可能残留 `logged_in=True` 却没有 `df`。`sidebar_login()` 已改为在这种情况下自动从数据库重载，不要退回成"静默显示首页"。

自动化测试 `tools/app_smoke_test.py` 用 mock 的 streamlit 模块真实执行 `app.main()`，并覆盖了上述两种场景，改动数据流时请留意别把这两个用例改坏。

