"""app.py 无头集成测试：用 mock 的 streamlit 真实执行 app.main()。

不需要浏览器、不需要真实数据、不联网，覆盖：
  1. 未登录首页
  2. 登录后仪表盘（5 个 tab 全部展开渲染）
  3. PK 擂台（对手已加载）
会在任何 app.py 内部异常时失败，适合作为提交前的回归检查。

用法: python tools/app_smoke_test.py
"""

import os
import sys
import types
import traceback
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CHART_CALLS = {"plotly": 0, "dataframe": 0, "metric": 0, "metrics": []}


# ─────────────────────────── mock streamlit ───────────────────────────
class _Ctx:
    """tabs / columns / expander / spinner 的上下文管理器"""

    def __init__(self, noop=True):
        self.noop = noop

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        if name == "metric":
            # 指标卡既可能渲染在 st.metric，也可能渲染在 st.columns(n)[i].metric
            def _m(label=None, value=None, *a, **k):
                CHART_CALLS["metric"] += 1
                CHART_CALLS["metrics"].append(f"{label}={value}")
            return _m
        return lambda *a, **k: _Ctx()


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:  # 与 st.session_state 行为一致
            raise AttributeError(name) from e

    def __setattr__(self, name, value):
        self[name] = value


def build_fake_streamlit(cfg):
    st = types.ModuleType("streamlit")
    st.session_state = _SessionState()

    def _noop(*a, **k):
        return None

    def _ctx(*a, **k):
        return _Ctx()

    for name in ("title", "header", "subheader", "caption", "markdown", "write", "text",
                 "divider", "success", "error", "warning", "info", "balloons", "rerun",
                 "set_page_config", "image"):
        setattr(st, name, _noop)

    # 侧边栏：控件按需返回值，其余属性访问是无害的桩
    class _Sidebar:
        def date_input(self, label=None, value=None, min_value=None, max_value=None, *a, **k):
            return value if isinstance(value, (list, tuple)) else (min_value, max_value)

        def multiselect(self, label=None, options=None, default=None, *a, **k):
            return list(options if default is None else default)

        def __getattr__(self, _name):
            return _noop

    st.sidebar = _Sidebar()

    # 布局
    st.tabs = lambda labels, *a, **k: [_Ctx() for _ in labels]
    st.columns = lambda spec, *a, **k: [_Ctx() for _ in (spec if isinstance(spec, (list, tuple)) else range(spec))]
    st.expander = _ctx
    st.spinner = _ctx

    # 控件：按 cfg 返回预设值
    st.button = lambda label=None, *a, **k: cfg["button"](label)
    st.text_input = lambda label=None, *a, **k: cfg["text_input"](label, k.get("key"))
    st.multiselect = lambda label=None, options=None, default=None, *a, **k: list(options if default is None else default)
    st.selectbox = lambda label=None, options=None, *a, **k: list(options)[0]
    st.radio = lambda label=None, options=None, *a, **k: list(options)[0]
    st.date_input = lambda label=None, value=None, min_value=None, max_value=None, *a, **k: (
        value if isinstance(value, (list, tuple)) else (min_value, max_value))

    # 输出类：计数以便断言确实渲染了内容
    def _plotly(*a, **k):
        CHART_CALLS["plotly"] += 1
    def _dataframe(*a, **k):
        CHART_CALLS["dataframe"] += 1
    def _metric(label=None, value=None, *a, **k):
        CHART_CALLS["metric"] += 1
        CHART_CALLS["metrics"].append(f"{label}={value}")

    st.plotly_chart = _plotly
    st.dataframe = _dataframe
    st.metric = _metric
    st.column_config = types.SimpleNamespace(
        NumberColumn=lambda **k: k, TextColumn=lambda **k: k)

    # pandas.read_sql 的 connection/sql 也会走这里，无需额外处理
    return st


def build_demo_df(stu_no, seed=1):
    """合成一张与 database 读出来等价的 DataFrame"""
    import random
    import pandas as pd
    random.seed(seed)
    canteens = ["学一食堂", "北区学生第三食堂", "学生第四食堂", "教工食堂", "沙河第一食堂",
                "清真食堂", "沙河风味餐厅", "学二食堂"]
    rows = []
    day = datetime(2025, 3, 1, 0, 0, 0)
    for i in range(130):
        d0 = day + timedelta(days=i)
        if d0.weekday() == 6 and random.random() < 0.6:
            continue
        for hour, lo, hi, p in [(7, 200, 700, .9), (8, 200, 800, .5),
                                (11, 800, 2200, .95), (12, 800, 2400, .8),
                                (17, 800, 2300, .9), (18, 900, 2600, .6),
                                (20, 300, 1500, .2)]:
            if random.random() < p:
                rows.append({"date": d0.replace(hour=hour, minute=random.randint(0, 59)),
                             "amount": -random.randint(lo, hi),
                             "mer_name": random.choice(canteens),
                             "balance": random.randint(0, 300000),
                             "tx_name": "持卡人消费"})
    df = pd.DataFrame(rows)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def run_case(name, logged_in, opponent=False, expect_charts=False, fresh_session=False):
    import importlib
    import pandas as pd

    CHART_CALLS.update(plotly=0, dataframe=0, metric=0)

    def button(label):
        # 已登录时“退出”按钮绝不能点（会清空状态退回首页）；
        # 其余按钮返回 True，以便覆盖抽签、加载对手等分支。
        if label and "退出" in str(label):
            return False
        return bool(logged_in)

    fake = build_fake_streamlit({"button": button, "text_input": lambda label, key: "20241001"})
    sys.modules["streamlit"] = fake

    # 让 app.py 从合成数据而不是真实数据库取数
    import scraper.database as db
    demo = build_demo_df("20241001", seed=1)
    oppo = build_demo_df("20241002", seed=2)

    def fake_read_sql(sql, conn, params=None, **k):
        return (oppo if "20241002" in str(params) else demo).copy()

    db.get_connection = lambda: None
    pd.read_sql = fake_read_sql
    # 阻止任何真实网络登录
    import scraper.sso_login as sso
    sso.sso_fetch_and_save = lambda *a, **k: {
        "ok": True, "message": "demo", "stats": None, "inserted": 0, "skipped": 0}

    fake.session_state.clear()
    fake.session_state.update({
        "logged_in": logged_in, "stu_no": "20241001" if logged_in else "",
        "df": None,
        "opponent_logged_in": opponent,
        "opponent_stu": "20241002" if opponent else "",
        "opponent_df": None,
    })

    for mod in ("app",):
        sys.modules.pop(mod, None)
    app = importlib.import_module("app")

    # 让 app 从合成数据取数（保持 df=None，以验证 app.py 的自我恢复逻辑）
    app.load_data_from_db = lambda s: app._prepare_df(
        (oppo if s == "20241002" else demo).copy())
    if opponent:
        fake.session_state["opponent_df"] = app.load_data_from_db("20241002")

    if fresh_session:
        # 模拟“模块已被缓存、新开一个浏览器会话”的场景：模块级 init_session()
        # 不会再执行，此时 session_state 里一个键都没有
        fake.session_state.clear()

    app.main()

    if fresh_session:
        assert fake.session_state.get("logged_in") is False, \
            "新会话下 main() 没有补上默认状态"

    if expect_charts:
        assert CHART_CALLS["plotly"] > 0, "仪表盘没有渲染任何图表，测试未覆盖到目标代码路径"
        # 注意：侧边栏走的是 st.sidebar.metric（不经过 st.metric 桩），所以这里断言
        # 侧边栏指标 + 主区域指标卡的总数
        assert len(CHART_CALLS["metrics"]) > 0, "仪表盘没有渲染任何指标卡"
        assert CHART_CALLS["dataframe"] > 0, "仪表盘没有渲染任何数据表"
    print(f"  [OK]   {name}: plotly={CHART_CALLS['plotly']} "
          f"dataframe={CHART_CALLS['dataframe']} metric={len(CHART_CALLS['metrics'])}")


def main():
    print(f"python {sys.version.split()[0]}")
    failed = []
    cases = [("未登录首页", dict(logged_in=False, opponent=False), False),
             ("登录后仪表盘（5 tab）", dict(logged_in=True, opponent=False), True),
             ("PK 擂台（对手已加载）", dict(logged_in=True, opponent=True), True),
             ("新浏览器会话（空 session_state）", dict(logged_in=False, opponent=False,
                                                    fresh_session=True), False)]
    for name, args, expect in cases:
        try:
            run_case(name, expect_charts=expect, **args)
        except Exception:
            failed.append(name)
            print(f"  [FAIL] {name}:\n{traceback.format_exc()}")
    print()
    if failed:
        print(f"[X] 失败 {len(failed)} 项: {failed}")
        return 1
    print(f"[+] app.main() 全部 {len(cases)} 种状态无异常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
