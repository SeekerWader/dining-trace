"""北航统一认证 SSO 自动登录

流程:
  1. GET  sso.buaa.edu.cn/login?service=...  获取 execution 参数
  2. POST sso.buaa.edu.cn/login              提交学号密码
  3. 302 跟随重定向链，获取 pass.cc-pay.cn 的 Cookie

注意:
  cc-pay / 校方网关目前带有风控(验证页)机制，登录链偶发在到达
  cc-pay 之前就被一个 200 验证页截断。因此登录会自动重试几次，
  只有拿到 cc-pay 域 Cookie(connect.sid) 才算成功。
"""

import random
import requests
import re
import os
import time
from urllib.parse import urljoin

SSO_BASE = "https://sso.buaa.edu.cn"
SERVICE_URL = "https://pass.cc-pay.cn/login"
LOGIN_URL = f"{SSO_BASE}/login?service={requests.utils.quote(SERVICE_URL, safe='')}"
# 能证明已登录 cc-pay 的 Cookie 名（任意一个即可）
CCPAY_SESSION_COOKIE = "connect.sid"

# 登录尝试次数与间隔（随机化，避免触发风控）
LOGIN_RETRIES = 3
LOGIN_RETRY_SLEEP_RANGE = (2.0, 4.0)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


class SSOLogin:
    """北航统一认证 SSO 登录器"""

    #: 明确失败原因（用户名密码错误 / 频繁 / 验证码），不值得自动重试
    FATAL_ERR_KEYWORDS = ("密码", "用户名", "频繁", "验证码", "锁定", "冻结", "风险")

    def __init__(self, username, password):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        self.username = username
        self.password = password
        self.last_error = ""

    def _extract_form(self, html):
        """从 CAS 登录页提取表单信息"""
        form_data = {"action": LOGIN_URL}
        m = re.search(r'<form[^>]*action="([^"]*)"', html, re.IGNORECASE)
        if m:
            action = m.group(1)
            form_data["action"] = urljoin(LOGIN_URL, action) if not action.startswith("http") else action

        for m in re.finditer(r'<input[^>]*name="([^"]*)"[^>]*value="([^"]*)"[^>]*>', html):
            form_data[m.group(1)] = m.group(2).replace("&#x2F;", "/").replace("&#x3A;", ":")
        return form_data

    def _follow_redirects(self, resp):
        """从当前响应开始手动跟随重定向链，收集 Cookie。

        返回:
            (cookie_str|None, error_msg|None)
            cookie 里必须出现 connect.sid（cc-pay 会话）才算成功。
        """
        last_cookies = {}
        seen_urls = set()
        for _ in range(12):
            location = resp.headers.get("Location", "")
            if not location:
                break
            if not location.startswith("http"):
                location = urljoin(LOGIN_URL, location)
            if location in seen_urls:
                break  # 防循环
            seen_urls.add(location)
            try:
                resp = self.session.get(location, allow_redirects=False, timeout=15)
            except requests.RequestException as e:
                return None, f"跟随跳转失败: {e}"
            for c in self.session.cookies:
                last_cookies[c.name] = c.value
            if resp.status_code not in (301, 302, 303, 307, 308):
                break  # 链结束（页面型响应）

        cookie_str = "; ".join(f"{k}={v}" for k, v in last_cookies.items())
        n = len(last_cookies)
        _print(f"  [+] 登录完成，获取到 {n} 个 Cookie")
        if not last_cookies.get(CCPAY_SESSION_COOKIE):
            return None, (f"跳转链未到达 cc-pay 会话（可能被网关验证页拦截），"
                          f"仅 {n} 个 Cookie")
        return cookie_str, None

    def _hint_from_error_page(self, html):
        """从 CAS 错误页提取人话提示"""
        for m in re.finditer(r'<p[^>]*id="[^"]*msg[^"]*"[^>]*>(.*?)</p>',
                             html, re.DOTALL | re.IGNORECASE):
            t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if t:
                return t
        if any(k in html for k in ("验证码", "校验")):
            return "需要人机校验/验证码，请稍后重试"
        if "频繁" in html or "过频" in html or "稍后再试" in html:
            return "登录过于频繁，请等待 1-2 分钟后重试"
        if "密码" in html and ("错" in html or "无效" in html):
            return "用户名或密码错误"
        return ""

    def _attempt(self):
        """执行一次完整 SSO 登录。

        返回:
            (cookie_str|None, error_msg|None)
        """
        _print("[*] Step 1/3: 获取 SSO 登录页 ...")
        try:
            resp = self.session.get(LOGIN_URL, allow_redirects=False, timeout=15)
        except requests.RequestException as e:
            return None, f"访问 SSO 失败: {e}"

        # 会话已有 TGT(CASTGC) 时，登录页会直接 302 到 cc-pay：跟随即可
        if resp.status_code in (301, 302, 303, 307, 308):
            _print("    (已存在 SSO 会话，直接跟随跳转)")
            return self._follow_redirects(resp)

        resp.raise_for_status()
        form = self._extract_form(resp.text)
        execution = form.get("execution", "")
        if not execution:
            return None, "SSO 登录页未返回 execution（可能被验证页拦截）"

        _print("[*] Step 2/3: 提交学号密码 ...")
        post_data = {
            "username": self.username,
            "password": self.password,
            "execution": execution,
            "_eventId": form.get("_eventId", "submit"),
            "submit": form.get("submit", "登录"),
            "geolocation": form.get("geolocation", ""),
        }

        try:
            resp = self.session.post(
                form["action"], data=post_data,
                allow_redirects=False,
                headers={"Origin": SSO_BASE, "Referer": LOGIN_URL,
                         "Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
        except requests.RequestException as e:
            return None, f"登录请求失败: {e}"

        if resp.status_code not in (302, 303, 307, 308):
            hint = self._hint_from_error_page(resp.text)
            _print(f"  [!] 登录返回 {resp.status_code}: {hint or '未知错误'}")
            return None, hint or f"登录被拒绝 (HTTP {resp.status_code})"

        _print("[*] Step 3/3: 跟随重定向获取 Cookie ...")
        return self._follow_redirects(resp)

    def login(self):
        """执行 SSO 登录，返回 Cookie 字符串或 None。

        - 网络抖动 / 验证页截断等偶发问题会自动重试
        - 用户名密码错误、被限流等确定性失败不重试，直接返回
        失败原因保存在 self.last_error
        """
        last_err = ""
        for i in range(LOGIN_RETRIES):
            if i > 0:
                wait = random.uniform(*LOGIN_RETRY_SLEEP_RANGE)
                _print(f"  [~] 第 {i + 1}/{LOGIN_RETRIES} 次尝试，等待 {wait:.1f}s 后重试 ...")
                time.sleep(wait)
            cookie_str, err = self._attempt()
            if cookie_str:
                self.last_error = ""
                return cookie_str
            last_err = err or "未知错误"
            if any(k in last_err for k in self.FATAL_ERR_KEYWORDS):
                break  # 密码错误 / 限流 / 验证码：重试无意义甚至更糟
        self.last_error = last_err
        _print(f"[!] 登录失败: {last_err}")
        return None

    def login_and_save(self):
        """登录并保存 Cookie 到 data/cookies_{学号}.txt"""
        cookie_str = self.login()
        if not cookie_str:
            return False
        os.makedirs("data", exist_ok=True)
        with open(f"data/cookies_{self.username}.txt", "w", encoding="utf-8") as f:
            f.write(cookie_str)
        _print(f"[+] Cookie 已保存")
        return True


def sso_fetch_and_save(username, password, start_date=None, end_date=None):
    """
    SSO 登录 -> 拉取数据 -> 存库 一步到位。

    返回:
        dict: {"ok": bool, "message": str, "stats": dict|None, ...}
    """
    from .fetcher import fetch_and_save

    login = SSOLogin(username, password)
    cookie_str = login.login()
    if not cookie_str:
        hint = login.last_error
        msg = f"登录失败: {hint}" if hint else "登录失败: 未知错误"
        if any(k in msg for k in ("频繁", "验证码", "人机", "风险", "锁定", "冻结")):
            msg += "。请等待 1-2 分钟后再试"
        return {"ok": False, "message": msg,
                "stats": None, "inserted": 0, "skipped": 0}

    os.makedirs("data", exist_ok=True)
    with open(f"data/cookies_{username}.txt", "w", encoding="utf-8") as f:
        f.write(cookie_str)

    result = fetch_and_save(cookie_str, stu_no=username,
                            start_date=start_date, end_date=end_date)

    # 会话被服务器拒绝（刚登录即被风控标记等）时，间隔几秒自动重登一次
    msg = result.get("message", "")
    if not result.get("ok") and msg and "没有消费记录" not in msg:
        time.sleep(random.uniform(3.0, 5.0))
        _print("[~] 会话异常，自动重新登录一次 ...")
        cookie_str = login.login()
        if cookie_str:
            with open(f"data/cookies_{username}.txt", "w", encoding="utf-8") as f:
                f.write(cookie_str)
            result = fetch_and_save(cookie_str, stu_no=username,
                                    start_date=start_date, end_date=end_date)

    return result
