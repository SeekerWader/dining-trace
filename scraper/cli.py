"""命令行入口"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="北航食堂消费记录爬虫")
    sub = parser.add_subparsers(dest="command")

    # sso
    p = sub.add_parser("sso", help="SSO 登录 + 拉取数据")
    p.add_argument("--stu-no", "-u", required=True, help="学号")
    p.add_argument("--password", "-p", default="", help="密码（不传则交互输入）")
    p.add_argument("--start", "-s", default=None)
    p.add_argument("--end", "-e", default=None)

    # stats
    p = sub.add_parser("stats", help="查看数据库中的用户统计")
    p.add_argument("--stu-no", "-u", default="", help="学号（不填则显示所有）")

    args = parser.parse_args()

    if args.command == "sso":
        from scraper.sso_login import sso_fetch_and_save
        password = args.password
        if not password:
            import getpass
            password = getpass.getpass(f"  [{args.stu_no}] 密码: ")
        res = sso_fetch_and_save(args.stu_no, password,
                                 start_date=args.start, end_date=args.end)
        if not res.get("ok"):
            _print(f"[!] {res.get('message', '失败')}")

    elif args.command == "stats":
        from scraper.database import init_db, get_statistics, get_date_range, get_transaction_count, get_users
        init_db()
        users = get_users()
        targets = [args.stu_no] if args.stu_no else users
        for stu in targets:
            if stu not in users:
                _print(f"[-] {stu} 无数据")
                continue
            s = get_statistics(stu_no=stu)
            f, l = get_date_range(stu_no=stu)
            c = get_transaction_count(stu_no=stu)
            _print(f"\n  [{stu}]  {f} ~ {l}")
            _print(f"  消费: {s['total_spent']/100:.2f} | "
                   f"充值: {s['total_recharge']/100:.2f} | "
                   f"{s['tx_count']} 次 | {s['canteen_count']} 食堂")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
