"""app.py 数据变换逻辑冒烟测试（不依赖 Streamlit）。

直接照搬 app.py::_prepare_df 及其各 section 用到的 pandas 操作，
用合成数据跑一遍，用来提前发现 pandas 版本兼容问题。
"""

import sys
from datetime import datetime

import pandas as pd

FAIL = []


def check(name, fn):
    try:
        out = fn()
        print(f"  [OK]   {name}" + (f" -> {out}" if out is not None else ""))
    except Exception as e:  # noqa: BLE001
        FAIL.append((name, e))
        print(f"  [FAIL] {name}: {type(e).__name__}: {e}")


def make_raw_df(n=400):
    """构造与数据库读出来等价的原始 DataFrame（date 已 parse_dates）"""
    import random
    random.seed(7)
    canteens = ["学一食堂", "北区学生第三食堂", "学生第四食堂", "教工食堂", "沙河第一食堂"]
    rows = []
    base = datetime(2025, 3, 1)
    for i in range(n):
        d = base + pd.Timedelta(hours=i * 4.3)
        hour = random.choice([7, 8, 11, 12, 12, 17, 18, 18, 20])
        d = d.replace(hour=hour, minute=random.randint(0, 59))
        rows.append({
            "date": d,
            "amount": -random.randint(200, 2500),
            "mer_name": random.choice(canteens),
            "balance": random.randint(0, 200000),
            "tx_name": "持卡人消费",
        })
    rows.append({"date": base, "amount": 100000, "mer_name": "", "balance": 100000,
                 "tx_name": "航财通微信支付转账充值"})
    return pd.DataFrame(rows)


# ── 与 app.py 保持一致的 _prepare_df ──
def _prepare_df(df_raw):
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


def main():
    print(f"python {sys.version.split()[0]} | pandas {pd.__version__}")
    raw = make_raw_df()
    df = None

    def step_prepare():
        nonlocal df
        df = _prepare_df(raw)
        assert len(df) > 0
        return f"{len(df)} 行, 列={list(df.columns)}"
    check("_prepare_df 计算列", step_prepare)

    check("总览-按日汇总", lambda: df.groupby("date_only").agg(
        金额=("amount_yuan", "sum"), 次数=("amount_yuan", "count"),
        笔均=("amount_yuan", "mean")).round(2).sort_index(ascending=False).shape)
    check("总览-按月汇总", lambda: df.groupby("month").agg(
        金额=("amount_yuan", "sum"), 次数=("amount_yuan", "count"),
        日均=("amount_yuan", lambda x: round(x.sum() / max(x.index.nunique(), 1), 2))).shape)
    check("总览-每日趋势+7日均线",
          lambda: df.groupby("date_only")["amount_yuan"].sum().reset_index()
          .assign(ma=lambda d: d["amount_yuan"].rolling(7).mean()).shape)
    check("食堂-占比聚合", lambda: df.groupby("mer_name").agg(
        总消费=("amount_yuan", "sum"), 次数=("amount_yuan", "count")).sort_values("总消费").shape)
    check("食堂-月度变化", lambda: df.groupby(["month", "mer_name"])["amount_yuan"].sum().reset_index().shape)
    check("食堂-笔均/中位数", lambda: df.groupby("mer_name")["amount_yuan"]
          .agg(["mean", "median", "count"]).round(2).sort_values("mean", ascending=False).shape)
    check("食堂-箱线图数据", lambda: (df["mer_name"].nunique(), float(df["amount_yuan"].max())))
    check("时间-各时段次数", lambda: df.groupby("hour").size().reset_index(name="count").shape)
    check("时间-食堂x小时热力图", lambda: df.groupby(["mer_name", "hour"]).size()
          .reset_index(name="count").pivot_table(index="mer_name", columns="hour",
                                                 values="count", fill_value=0).shape)
    check("时间-三餐切分", lambda: (
        len(df[(df["hour"] >= 6) & (df["hour"] < 10)]),
        len(df[(df["hour"] >= 10) & (df["hour"] < 15)]),
        len(df[(df["hour"] >= 17) & (df["hour"] < 20)])))
    check("时间-每周三餐平均时间", lambda: pd.concat([
        d.groupby("year_week")["hour"].mean().reset_index().assign(meal=m)
        for d, m in [(df[(df["hour"] >= 6) & (df["hour"] < 10)], "早餐"),
                     (df[(df["hour"] >= 10) & (df["hour"] < 15)], "午餐"),
                     (df[(df["hour"] >= 17) & (df["hour"] < 20)], "晚餐")]]).shape)
    check("时间-一周热度", lambda: df.groupby("周几")["amount_yuan"].sum().reset_index().shape)
    check("抽签-加权权重", lambda: [int(df["mer_name"].value_counts().get(c, 1))
                                    for c in sorted(df["mer_name"].unique())])
    check("PK-指标口径", lambda: {
        "总消费": round(float(df["amount_yuan"].sum()), 2),
        "次数": len(df),
        "食堂": int(df["mer_name"].nunique()),
        "笔均": round(float(df["amount_yuan"].mean()), 2),
        "日均": round(float(df["amount_yuan"].sum() / max(df["date_only"].nunique(), 1)), 2)})
    check("PK-雷达图归一化", lambda: [
        round(v / m * 100, 1) for v, m in zip([1200, 300, 5, 20, 40], [1500, 300, 6, 22, 40])])

    print()
    if FAIL:
        print(f"[X] {len(FAIL)} 项失败:")
        for name, e in FAIL:
            print(f"    - {name}: {type(e).__name__}: {e}")
        return 1
    print("[+] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
