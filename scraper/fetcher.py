"""校园卡消费记录爬虫"""

import random
import requests
import time
from datetime import date

from .config import (
    TRADES_URL, USER_URL,
    REQUEST_INTERVAL, PAGE_SIZE,
    START_DATE, END_DATE,
)

# 单页请求失败时的重试次数（服务器偶发风控/网络抖动，重试一次通常能过）
PAGE_RETRIES = 3
# 重试等待区间（秒，随机化以降低被风控的概率）
RETRY_SLEEP_RANGE = (2.0, 4.0)
# 翻页上限，防止异常时无限请求
MAX_PAGES = 60


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def _server_msg(result):
    """从接口响应中提取人话错误信息"""
    if not result:
        return ""
    msg = (result.get("message") or "").strip()
    if not msg:
        return ""
    return msg


class CanteenFetcher:
    """校园卡消费记录抓取器"""

    def __init__(self, cookie_str="", stu_no=""):
        if not stu_no:
            raise ValueError("请提供学号 (stu_no)")
        self.stu_no = stu_no

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json;charset=utf-8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": (
                f"https://mall.cc-pay.cn/cardInquiry"
                f"?stuNo={self.stu_no}&linkfrom=pass"
            ),
        })

        if cookie_str:
            self.set_cookies(cookie_str)

    def set_cookies(self, cookie_str):
        self.session.headers["Cookie"] = cookie_str.strip()

    def get_user_info(self):
        """获取当前用户信息"""
        try:
            ts = int(time.time() * 1000)
            resp = self.session.get(f"{USER_URL}?t={ts}", timeout=15)
            if resp.status_code == 200:
                return resp.json()
            return None
        except requests.RequestException:
            return None

    def fetch_page(self, page_num=1, page_size=None,
                   start_date=None, end_date=None):
        """获取一页交易记录，失败返回 None"""
        if page_size is None:
            page_size = PAGE_SIZE

        min_ts = f"{start_date}T16:00:00.000Z" if start_date else "2024-01-01T16:00:00.000Z"
        max_ts = f"{end_date}T15:59:59.999Z" if end_date else f"{date.today()}T15:59:59.999Z"

        params = {
            "t": int(time.time() * 1000),
            "pageSize": page_size,
            "pageNum": page_num,
            "minTsCreation": min_ts,
            "maxTsCreation": max_ts,
            "tradeType": "all",
            "stuNo": self.stu_no,
        }

        try:
            resp = self.session.get(TRADES_URL, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            return None
        except requests.RequestException:
            return None

    def fetch_all(self, start_date=None, end_date=None):
        """
        获取所有页的交易记录。

        返回:
            dict: {"trades": [...], "error": None | 中途错误描述}
            - trades 已去重
            - 第一页即失败时 trades 为空列表，错误写入 error
            - 中途某页失败时保留已抓取的部分，error 说明截断原因
        """
        all_trades = []
        page_num = 1
        last_err = None
        _print("[*] 开始拉取消费记录 ...")

        while page_num <= MAX_PAGES:
            result = None
            for attempt in range(PAGE_RETRIES):
                result = self.fetch_page(
                    page_num=page_num,
                    start_date=start_date or START_DATE,
                    end_date=end_date or END_DATE,
                )
                if result is None:
                    last_err = "请求超时或网络异常"
                elif not result.get("success"):
                    msg = _server_msg(result)
                    last_err = f"服务器拒绝: {msg}" if msg else "服务器拒绝请求"
                    # 401 这类会话问题重试意义不大，提前失败并上报
                    if result.get("type") in (401, 403):
                        break
                else:
                    break
                if attempt < PAGE_RETRIES - 1:
                    time.sleep(random.uniform(*RETRY_SLEEP_RANGE))

            if result is None or not result.get("success"):
                if page_num == 1:
                    return {"trades": [], "error": last_err}
                _print(f"  [!] 第 {page_num} 页拉取失败({last_err})，保留已获取数据")
                break

            data = result.get("data", {})
            trades = data.get("data", [])
            if not trades:
                break

            all_trades.extend(trades)
            _print(f"  [+] 第 {page_num} 页: {len(trades)} 条 (累计 {len(all_trades)} 条)")

            total_count = data.get("count", 0)
            if total_count and total_count > 0:
                if page_num >= (total_count + PAGE_SIZE - 1) // PAGE_SIZE:
                    break
            if len(trades) < data.get("pageSize", PAGE_SIZE):
                break

            page_num += 1
            time.sleep(REQUEST_INTERVAL)

        # 去重
        seen = set()
        unique = []
        for tx in all_trades:
            key = (tx.get("date", ""), tx.get("amount", 0),
                   tx.get("merName", ""), tx.get("balance", 0),
                   tx.get("txName", ""))
            if key not in seen:
                seen.add(key)
                unique.append(tx)

        _print(f"  [*] 共 {len(unique)} 条有效记录")
        return {"trades": unique, "error": last_err}


def fetch_and_save(cookie_str, stu_no="", start_date=None, end_date=None):
    """
    抓取记录并存入数据库。

    参数:
        cookie_str: Cookie 字符串
        stu_no: 学号（必填）
        start_date, end_date: 日期范围

    返回:
        dict: {"ok": bool, "message": str, "stats": dict|None,
               "inserted": int, "skipped": int}
    """
    result = {"ok": False, "message": "", "stats": None,
              "inserted": 0, "skipped": 0}
    if not stu_no:
        result["message"] = "缺少学号"
        return result

    from .database import init_db, insert_transactions, get_statistics

    init_db()
    fetcher = CanteenFetcher(cookie_str, stu_no=stu_no)

    # 登录后稍等片刻再打接口，降低刚登录就被风控误判的概率
    time.sleep(random.uniform(1.0, 2.0))

    _print("[*] 验证 Cookie ...")
    info = fetcher.get_user_info()
    if not (info and info.get("success")):
        msg = "Cookie 无效或已过期"
        if info:
            m = _server_msg(info)
            if m and "验证失败" not in m:
                msg += f"（服务器: {m}）"
        _print(f"[!] {msg}")
        result["message"] = f"登录状态验证失败: {msg}。可能是服务器风控，请稍后重试"
        return result

    out = fetcher.fetch_all(start_date=start_date, end_date=end_date)
    trades, err = out.get("trades", []), out.get("error")
    if not trades:
        if err:
            result["message"] = f"拉取消费记录失败: {err}。可能是会话被服务器拒绝，请重新登录再试"
            _print(f"[-] 拉取失败: {err}")
        else:
            result["message"] = "该时间范围内没有消费记录"
            _print("[-] 没有获取到任何记录")
        return result

    _print(f"\n[*] 存入数据库 ...")
    inserted, skipped = insert_transactions(trades, stu_no=stu_no)
    _print(f"  [+] 新增 {inserted} 条, 跳过 {skipped} 条重复")
    result["inserted"] = inserted
    result["skipped"] = skipped

    stats = get_statistics(stu_no=stu_no)
    result["stats"] = stats
    result["ok"] = True
    result["message"] = f"新增 {inserted} 条记录"
    _print(f"\n[*] 统计概览 ({stu_no}):")
    _print(f"  - 总消费: {stats['total_spent'] / 100:.2f} 元")
    _print(f"  - 总充值: {stats['total_recharge'] / 100:.2f} 元")
    _print(f"  - 消费次数: {stats['tx_count']} 次")
    _print(f"  - 去过食堂: {stats['canteen_count']} 个")

    return result
