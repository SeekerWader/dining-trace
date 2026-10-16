"""
校园卡消费记录 - 一键抓取（Dining Trace / 干饭指北）

用法:
  python fetch_data.py --stu-no 学号     SSO 自动登录拉取数据
  python fetch_data.py --stats           查看本地已有数据统计

首次使用会自动安装依赖: pip install requests streamlit plotly pandas
"""

import sys
import os


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--stats" in args:
        from scraper.database import init_db, get_statistics, get_date_range
        from scraper.database import get_transaction_count, get_users
        init_db()
        users = get_users()
        if not users:
            _print("[-] 数据库中无数据，请先用 --stu-no 拉取")
        else:
            stu = ""
            if "--stu-no" in args:
                idx = args.index("--stu-no")
                if idx + 1 < len(args):
                    stu = args[idx + 1]
            targets = [stu] if stu else users
            for s in targets:
                if s not in users:
                    continue
                st = get_statistics(stu_no=s)
                f, l = get_date_range(stu_no=s)
                c = get_transaction_count(stu_no=s)
                _print(f"\n  [{s}]  {f} ~ {l}")
                _print(f"  消费: {st['total_spent']/100:.2f} 元 | "
                       f"充值: {st['total_recharge']/100:.2f} 元 | "
                       f"{st['tx_count']} 次 | {st['canteen_count']} 食堂")
        sys.exit(0)

    if "--stu-no" in args:
        idx = args.index("--stu-no")
        if idx + 1 >= len(args):
            _print("[!] 请提供学号，如 --stu-no 你的学号")
            sys.exit(1)
        stu_no = args[idx + 1]

        from scraper.sso_login import sso_fetch_and_save
        password = ""
        if "--password" in args:
            p_idx = args.index("--password")
            if p_idx + 1 < len(args):
                password = args[p_idx + 1]
        if not password:
            import getpass
            password = getpass.getpass(f"  [{stu_no}] 密码: ")

        result = sso_fetch_and_save(stu_no, password)
        if result.get("ok"):
            _print("\n[+] 完成！启动可视化面板:")
            _print("    streamlit run app.py")
            sys.exit(0)
        _print(f"\n[!] {result.get('message', '失败')}")
        sys.exit(1)

    _print(__doc__)
