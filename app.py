"""
北航食堂消费记录 - 可视化面板
启动: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import random
from datetime import datetime, date

from scraper.database import get_connection, init_db, get_statistics

# ── 页面配置 ──
st.set_page_config(page_title="北航干饭指北", page_icon="🍜", layout="wide")


# ── Session 状态 ──
def init_session():
    """初始化 session 状态。

    必须幂等：模块级只会在进程首轮执行一次，而 Streamlit 之后每次交互都
    只是重跑脚本主体（`import app` 被 sys.modules 缓存）。所以 main() 每次
    都会再调一次，保证新开的浏览器会话也能拿到完整的默认状态。
    """
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "stu_no" not in st.session_state:
        st.session_state.stu_no = ""
    if "df" not in st.session_state:
        st.session_state.df = None
    # PK 对手
    if "opponent_logged_in" not in st.session_state:
        st.session_state.opponent_logged_in = False
    if "opponent_stu" not in st.session_state:
        st.session_state.opponent_stu = ""
    if "opponent_df" not in st.session_state:
        st.session_state.opponent_df = None


init_session()


# ── 辅助函数 ──
def _prepare_df(df_raw):
    """给原始数据添加计算列"""
    df = df_raw[df_raw["amount"] < 0].copy()
    if df.empty:
        return df
    df["amount_yuan"] = df["amount"].abs() / 100
    df["hour"] = df["date"].dt.hour
    df["date_only"] = df["date"].dt.date
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["year_week"] = df["date"].dt.strftime("%Y-第%W周")
    df["weekday"] = df["date"].dt.strftime("%A")
    wd = {"Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
          "Thursday": "周四", "Friday": "周五", "Saturday": "周六", "Sunday": "周日"}
    df["周几"] = df["weekday"].map(wd)
    return df


def load_data_from_db(stu_no):
    """从数据库加载用户数据"""
    init_db()
    conn = get_connection()
    df = pd.read_sql(
        "SELECT date, amount, mer_name, balance, tx_name FROM transactions "
        "WHERE stu_no = ? ORDER BY date",
        conn, params=(stu_no,), parse_dates=["date"],
    )
    conn.close()
    return _prepare_df(df)


def sso_login(stu_no, password):
    """SSO 登录并拉取数据，返回结果 dict(ok/message/stats)"""
    from scraper.sso_login import sso_fetch_and_save
    with st.spinner(f"正在登录 {stu_no} ..."):
        return sso_fetch_and_save(stu_no, password)


# ── 侧边栏：登录 ──
def sidebar_login():
    st.sidebar.title("🍜 北航干饭指北")
    st.sidebar.caption("SSO 统一认证登录")

    if not st.session_state.logged_in:
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔐 登录")
        stu = st.sidebar.text_input("学号", key="login_stu", placeholder="请输入学号")
        pwd = st.sidebar.text_input("密码", type="password", key="login_pwd",
                                     placeholder="统一认证密码")
        if st.sidebar.button("🚀 登录", type="primary", use_container_width=True):
            if stu and pwd:
                res = sso_login(stu, pwd)
                if res.get("ok"):
                    st.session_state["login_msg"] = (
                        res.get("message", "")
                        if res.get("inserted")
                        else "登录成功（本次没有新记录）")
                    df = load_data_from_db(stu)
                    st.session_state.logged_in = True
                    st.session_state.stu_no = stu
                    st.session_state.df = df
                    st.rerun()
                else:
                    st.sidebar.error(res.get("message") or "登录失败，请检查学号和密码")
            else:
                st.sidebar.warning("请填写学号和密码")
    else:
        # 已登录状态
        st.sidebar.success(f"✅ 已登录")
        st.sidebar.caption(f"学号: {st.session_state.stu_no[:4]}****")
        if st.session_state.get("login_msg"):
            st.sidebar.caption(st.session_state["login_msg"])

        # 会话里没有 df（例如代码热重载后 session 残留）时，从数据库重新加载，
        # 否则会静默退回首页
        if st.session_state.df is None and st.session_state.stu_no:
            st.session_state.df = load_data_from_db(st.session_state.stu_no)

        if st.session_state.df is not None:
            days = st.session_state.df["date_only"].nunique()
            total = st.session_state.df["amount_yuan"].sum()
            st.sidebar.metric("干饭天数", f"{days} 天")
            st.sidebar.metric("总消费", f"¥{total:.0f}")

        if st.sidebar.button("🚪 退出", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.stu_no = ""
            st.session_state.df = None
            st.rerun()

    return st.session_state.logged_in, st.session_state.df


# ── 指标卡片 ──
def show_header(df):
    t, a, c, cn = df["amount_yuan"].sum(), df["amount_yuan"].mean(), len(df), df["mer_name"].nunique()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 总消费", f"¥{t:,.2f}")
    c2.metric("🍽️  干饭次数", f"{c} 次")
    c3.metric("📐 笔均", f"¥{a:.2f}")
    c4.metric("🏪 食堂", f"{cn} 个")


# ════════════════════════════════════════════════════════════
#  一、你真能吃！
# ════════════════════════════════════════════════════════════
def section_overview(df):
    st.header("💰 你真能吃！", divider="rainbow")
    t1, t2 = st.tabs(["📋 消费流水账", "📈 花钱如流水"])

    with t1:
        v = st.radio("维度", ["按日汇总", "按月汇总"], horizontal=True)
        if v == "按日汇总":
            g = df.groupby("date_only").agg(金额=("amount_yuan", "sum"), 次数=("amount_yuan", "count"), 笔均=("amount_yuan", "mean")).round(2)
            st.dataframe(g.sort_index(ascending=False), use_container_width=True,
                         column_config={"金额": st.column_config.NumberColumn(format="¥%.2f"),
                                        "笔均": st.column_config.NumberColumn(format="¥%.2f")})
        elif v == "按月汇总":
            g = df.groupby("month").agg(金额=("amount_yuan", "sum"), 次数=("amount_yuan", "count"),
                                         日均=("amount_yuan", lambda x: round(x.sum() / max(x.index.nunique(), 1), 2)))
            g.columns = ["金额(¥)", "次数", "日均(¥)"]
            st.dataframe(g.sort_index(ascending=False), use_container_width=True,
                         column_config={"金额(¥)": st.column_config.NumberColumn(format="¥%.2f"),
                                        "日均(¥)": st.column_config.NumberColumn(format="¥%.2f")})

    with t2:
        m = st.radio("趋势", ["每日", "每月"], horizontal=True, key="tr")
        if m == "每日":
            d = df.groupby("date_only")["amount_yuan"].sum().reset_index()
            d.columns = ["日期", "金额"]
            fig = px.line(d, x="日期", y="金额", markers=True, title="每日消费趋势")
            if len(d) >= 7:
                d["7日均线"] = d["金额"].rolling(7).mean()
                fig.add_scatter(x=d["日期"], y=d["7日均线"], mode="lines", name="7日均线",
                                line=dict(color="red", width=2, dash="dash"))
        else:
            d = df.groupby("month")["amount_yuan"].sum().reset_index()
            d.columns = ["月份", "金额"]
            fig = px.bar(d, x="月份", y="金额", color="金额", color_continuous_scale="Reds", title="每月消费趋势")
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════
#  二、喜欢您就来！
# ════════════════════════════════════════════════════════════
def section_canteen(df):
    st.header("🏪 喜欢您就来！", divider="orange")
    t1, t2 = st.tabs(["🥟 雨露均沾", "⚖️ 好吃就多吃"])

    with t1:
        cs = df.groupby("mer_name").agg(总消费=("amount_yuan", "sum"), 次数=("amount_yuan", "count")).sort_values("总消费", ascending=False).reset_index()
        c1, c2 = st.columns(2)
        with c1:
            fig = px.pie(cs, names="mer_name", values="总消费", hole=0.4, title="消费金额占比")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.pie(cs, names="mer_name", values="次数", hole=0.4, title="光顾次数占比")
            st.plotly_chart(fig, use_container_width=True)
        st.subheader("食堂月度消费变化")
        cm = df.groupby(["month", "mer_name"])["amount_yuan"].sum().reset_index()
        fig = px.line(cm, x="month", y="amount_yuan", color="mer_name", markers=True,
                      labels={"month": "", "amount_yuan": "¥"})
        fig.update_layout(height=380, hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

    with t2:
        ca = df.groupby("mer_name")["amount_yuan"].agg(["mean", "median", "count"]).round(2).sort_values("mean", ascending=False).reset_index()
        ca.columns = ["食堂", "平均(¥)", "中位数(¥)", "次数"]
        c1, c2 = st.columns([1.5, 1])
        with c1:
            fig = px.bar(ca, x="食堂", y="平均(¥)", color="平均(¥)", color_continuous_scale="OrRd",
                         text_auto=".2f", title="笔均消费对比")
            fig.update_layout(height=380, xaxis_tickangle=-30)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.box(df, x="mer_name", y="amount_yuan", color="mer_name", title="消费分布")
            fig.update_layout(height=380, showlegend=False, xaxis_tickangle=-30)
            st.plotly_chart(fig, use_container_width=True)
        ca["平均(¥)"] = ca["平均(¥)"].apply("¥{:.2f}".format)
        ca["中位数(¥)"] = ca["中位数(¥)"].apply("¥{:.2f}".format)
        st.dataframe(ca, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════
#  三、吃了吗您呐？
# ════════════════════════════════════════════════════════════
def section_timing(df):
    st.header("⏰ 吃了吗您呐？", divider="green")
    t1, t2 = st.tabs(["🕐 几时开饭", "🌅 三餐四季"])

    with t1:
        cafe = st.selectbox("食堂", sorted(df["mer_name"].unique()))
        cd = df[df["mer_name"] == cafe]
        if not cd.empty:
            h = cd.groupby("hour").size().reset_index(name="count")
            fig = px.bar(h, x="hour", y="count", color="count", color_continuous_scale="Viridis",
                         title=f"{cafe} 各时段消费次数")
            fig.update_layout(height=340)
            fig.update_xaxes(tickmode="linear", tick0=0, dtick=2)
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("食堂 x 时间 热力图")
        hm = df.groupby(["mer_name", "hour"]).size().reset_index(name="count")
        pv = hm.pivot_table(index="mer_name", columns="hour", values="count", fill_value=0)
        fig = px.imshow(pv, labels=dict(x="时", y="食堂", color="次"), color_continuous_scale="YlOrRd", aspect="auto")
        fig.update_layout(height=max(280, len(pv) * 35))
        st.plotly_chart(fig, use_container_width=True)

    with t2:
        bf = df[(df["hour"] >= 6) & (df["hour"] < 10)]
        lu = df[(df["hour"] >= 10) & (df["hour"] < 15)]
        di = df[(df["hour"] >= 17) & (df["hour"] < 20)]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🌅 早餐", len(bf))
        c2.metric("☀️ 午餐", len(lu))
        c3.metric("🌙 晚餐", len(di))
        c4.metric("🍪 其他", len(df) - len(bf) - len(lu) - len(di))

        mc = pd.DataFrame({
            "餐别": ["早餐", "午餐", "晚餐", "其他"],
            "金额": [bf["amount_yuan"].sum(), lu["amount_yuan"].sum(), di["amount_yuan"].sum(),
                     df[~((df["hour"] >= 6) & (df["hour"] < 10)) & ~((df["hour"] >= 10) & (df["hour"] < 15)) & ~((df["hour"] >= 17) & (df["hour"] < 20))]["amount_yuan"].sum()]
        })
        ca, cb = st.columns(2)
        with ca:
            fig = px.pie(mc, names="餐别", values="金额", hole=0.4, title="三餐金额占比")
            st.plotly_chart(fig, use_container_width=True)
        with cb:
            fig = px.bar(mc, x="餐别", y="金额", color="餐别", text_auto=".0f")
            fig.update_layout(showlegend=False, height=300)
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("每周三餐平均时间变化")
        wk = lambda d: d.groupby("year_week")["hour"].mean().reset_index()
        wa = pd.concat([
            wk(bf).assign(meal="早餐"),
            wk(lu).assign(meal="午餐"),
            wk(di).assign(meal="晚餐"),
        ])
        if not wa.empty:
            fig = px.line(wa, x="year_week", y="hour", color="meal", markers=True,
                          title="三餐平均时间", labels={"year_week": "", "hour": "时"})
            fig.update_layout(height=340, xaxis_tickangle=-45)
            fig.update_yaxes(tick0=6, dtick=1, range=[5, 21])
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("📅 一周消费热度")
        ws = df.groupby("周几")["amount_yuan"].sum().reset_index()
        fig = px.bar(ws, x="周几", y="amount_yuan", color="amount_yuan",
                     color_continuous_scale="Reds", title="一周各天消费总额",
                     category_orders={"周几": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]})
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════
#  四、是啊，吃什么？
# ════════════════════════════════════════════════════════════
def section_lucky(df):
    st.header("🎲 是啊，吃什么？", divider="red")
    st.caption("选择困难症救星")

    canteens = sorted(df["mer_name"].unique())
    exclude = st.multiselect("排除不想去的", options=canteens, default=[])
    avail = [c for c in canteens if c not in exclude]
    if not avail:
        st.warning("全部排除了")
        return

    mode = st.radio("模式", ["🎲 纯随机", "⚖️ 按偏好加权"], horizontal=True)

    if st.button("🎰 抽一个！", type="primary", use_container_width=True):
        w = None
        if mode.startswith("⚖️"):
            vc = df[df["mer_name"].isin(avail)]["mer_name"].value_counts()
            w = [vc.get(c, 1) for c in avail]
        chosen = random.choices(avail, weights=w, k=1)[0]
        cd = df[df["mer_name"] == chosen]
        st.balloons()
        st.success(f"### 🎉 今天去吃 **{chosen}** 吧！")
        c1, c2, c3 = st.columns(3)
        c1.metric("去过", f"{len(cd)} 次")
        c2.metric("平均", f"¥{cd['amount_yuan'].mean():.2f}")
        c3.metric("上次", cd["date"].max().strftime("%m-%d"))


# ════════════════════════════════════════════════════════════
#  五、PK 擂台
# ════════════════════════════════════════════════════════════
def section_pk(df_main, stu_main):
    st.header("⚔️ 干饭 PK 擂台", divider="violet")
    st.caption("叫上室友比一比，谁是干饭王？")

    # 对手登录区
    if not st.session_state.opponent_logged_in:
        with st.expander("➕ 添加对手（输入对方的学号和密码）", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                o_stu = st.text_input("对方学号", key="oppo_stu", placeholder="请输入")
            with col2:
                o_pwd = st.text_input("对方密码", type="password", key="oppo_pwd",
                                       placeholder="统一认证密码")
            if st.button("👤 加载对手数据", type="primary"):
                if o_stu and o_pwd:
                    res = sso_login(o_stu, o_pwd)
                    if res.get("ok"):
                        o_df = load_data_from_db(o_stu)
                        st.session_state.opponent_logged_in = True
                        st.session_state.opponent_stu = o_stu
                        st.session_state.opponent_df = o_df
                        st.rerun()
                    else:
                        st.error(res.get("message") or "对手登录失败，请检查学号和密码")
                else:
                    st.warning("请填写对方的学号和密码")
        return

    # 已有对手数据
    o_df = st.session_state.opponent_df
    o_stu = st.session_state.opponent_stu

    if o_df is None or o_df.empty:
        st.warning("对手暂无消费数据")
        return

    # 清除对手
    if st.button("🔄 清除对手", use_container_width=False):
        st.session_state.opponent_logged_in = False
        st.session_state.opponent_stu = ""
        st.session_state.opponent_df = None
        st.rerun()

    # ── 数据对比 ──
    s1 = {"学号": stu_main, "总消费": df_main["amount_yuan"].sum(),
          "次数": len(df_main), "食堂": df_main["mer_name"].nunique(),
          "笔均": df_main["amount_yuan"].mean(),
          "日均": df_main["amount_yuan"].sum() / max(df_main["date_only"].nunique(), 1)}
    s2 = {"学号": o_stu[:4] + "****", "总消费": o_df["amount_yuan"].sum(),
          "次数": len(o_df), "食堂": o_df["mer_name"].nunique(),
          "笔均": o_df["amount_yuan"].mean(),
          "日均": o_df["amount_yuan"].sum() / max(o_df["date_only"].nunique(), 1)}

    pk_df = pd.DataFrame([s1, s2]).set_index("学号")
    pk_df = pk_df.round(2).astype(str)  # 避免显示问题

    # 展示对比
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader(f"👤 {stu_main[:4]}****")
        st.metric("总消费", f"¥{s1['总消费']:,.0f}")
        st.metric("干饭次数", f"{s1['次数']} 次")
        st.metric("去过食堂", f"{s1['食堂']} 个")
    with col_b:
        st.subheader(f"👤 {o_stu[:4]}****")
        st.metric("总消费", f"¥{s2['总消费']:,.0f}")
        st.metric("干饭次数", f"{s2['次数']} 次")
        st.metric("去过食堂", f"{s2['食堂']} 个")

    # 雷达图
    st.subheader("📊 综合对比雷达图")
    cats = ["总消费", "次数", "食堂", "笔均", "日均"]
    vals1 = [s1["总消费"], s1["次数"], s1["食堂"], s1["笔均"], s1["日均"]]
    vals2 = [s2["总消费"], s2["次数"], s2["食堂"], s2["笔均"], s2["日均"]]
    max_vals = [max(a, b) for a, b in zip(vals1, vals2)]
    norm1 = [v / m * 100 if m > 0 else 0 for v, m in zip(vals1, max_vals)]
    norm2 = [v / m * 100 if m > 0 else 0 for v, m in zip(vals2, max_vals)]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=norm1 + [norm1[0]], theta=cats + [cats[0]],
                                   name=stu_main[:4] + "****", fill="toself"))
    fig.add_trace(go.Scatterpolar(r=norm2 + [norm2[0]], theta=cats + [cats[0]],
                                   name=o_stu[:4] + "****", fill="toself"))
    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])), height=400)
    st.plotly_chart(fig, use_container_width=True)

    # 各维度冠军
    st.subheader("🏆 各维度冠军")
    for i, cat in enumerate(cats):
        if vals1[i] > vals2[i]:
            st.success(f"**{cat}**: {stu_main[:4]}**** ({'¥' if cat in ['总消费','笔均','日均'] else ''}{vals1[i]:.1f}{'' if cat == '食堂' else ''})")
        elif vals2[i] > vals1[i]:
            st.success(f"**{cat}**: {o_stu[:4]}**** ({'¥' if cat in ['总消费','笔均','日均'] else ''}{vals2[i]:.1f}{'' if cat == '食堂' else ''})")
        else:
            st.info(f"**{cat}**: 平手！")


# ════════════════════════════════════════════════════════════
#  主页面
# ════════════════════════════════════════════════════════════
def main():
    # 每次重跑都补一次默认状态：新浏览器会话（模块已被缓存、不再执行模块级代码）
    # 否则会读到不存在的 st.session_state.logged_in 而报 AttributeError
    init_session()

    logged_in, df = sidebar_login()

    if not logged_in or df is None:
        st.title("🍜 北航干饭指北")
        st.markdown("""
        ### 👈 请在左侧登录
        使用 **北航统一认证** 学号和密码登录，即可查看你的食堂消费数据。

        ---
        **功能一览:**
        - 💰 **你真能吃！** — 消费流水 + 趋势分析
        - 🏪 **喜欢您就来！** — 食堂偏好 + 消费对比
        - ⏰ **吃了吗您呐？** — 用餐时间规律
        - 🎲 **是啊，吃什么？** — 随机食堂抽签
        - ⚔️ **PK 擂台** — 和室友比一比谁是干饭王
        """)
        return

    if df.empty:
        st.warning("暂无消费数据")
        return

    # ── 时间 / 食堂筛选 ──
    min_d, max_d = df["date_only"].min(), df["date_only"].max()
    dr = st.sidebar.date_input("📅 时间范围", value=(min_d, max_d),
                                min_value=min_d, max_value=max_d)
    sd = dr[0] if len(dr) == 2 else min_d
    ed = dr[1] if len(dr) == 2 else max_d
    df_f = df[(df["date_only"] >= sd) & (df["date_only"] <= ed)].copy()

    canteens = sorted(df_f["mer_name"].unique())
    sc = st.sidebar.multiselect("🏪 食堂", options=canteens, default=canteens)
    if sc:
        df_f = df_f[df_f["mer_name"].isin(sc)].copy()

    # ── 主界面 ──
    days = df_f["date_only"].nunique()
    st.title(f"🍜 干饭记录")
    st.markdown(f"<small>{min_d} ~ {max_d} ｜ {days} 天干饭日</small>", unsafe_allow_html=True)

    show_header(df_f)
    st.divider()

    tabs = st.tabs(["💰 你真能吃！", "🏪 喜欢您就来！", "⏰ 吃了吗您呐？",
                     "🎲 是啊，吃什么？", "⚔️ PK 擂台"])
    with tabs[0]:
        section_overview(df_f)
    with tabs[1]:
        section_canteen(df_f)
    with tabs[2]:
        section_timing(df_f)
    with tabs[3]:
        section_lucky(df_f)
    with tabs[4]:
        section_pk(df_f, st.session_state.stu_no)

    st.divider()
    st.caption(f"🍜 北航干饭指北 · 数据来源 pass.cc-pay.cn · {datetime.now():%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    main()
