import argparse
import csv
import json
import os
import sys

from .core import (CATALOG_COLS, ORDER_COLS, customer_text, fmt, process, read_table, supplier_batches,
                   supplier_text)

DEFAULT_TEXTS = {
    "supplier_head": "Order for {supplier}: {count} order(s). Please confirm availability and the total.",
    "supplier_cost": "Cost of goods: {cost}",
    "customer": "Hello, {name}! Your order #{order_id} is accepted:\n{lines}\nTotal: {total} {currency}. We will contact you about delivery.",
}


def cell(v):
    """Text that starts with = + - @ would be run as a formula by Excel; make it plain text."""
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") and not v.startswith("+380") else v


def safe_name(s):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:60] or "supplier"


def read(path, need, what):
    with open(path, encoding="utf-8", newline="") as f:
        head, rows = read_table(f.read())
    miss = [c for c in need if c not in head]
    if miss:
        raise SystemExit("%s: missing columns: %s (found: %s)" % (what, ", ".join(miss), ", ".join(head)))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(prog="order_suite")
    ap.add_argument("--orders", required=True)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--config")
    ap.add_argument("--strict", action="store_true", help="exit with code 2 if any order has an error")
    a = ap.parse_args(argv)
    cfg = {}
    if a.config:
        with open(a.config, encoding="utf-8") as f:
            cfg = json.load(f)
    texts = dict(DEFAULT_TEXTS, **cfg.get("texts", {}))
    currency = cfg.get("currency", "UAH")
    res, cat = process(read(a.orders, ORDER_COLS, "orders"), read(a.catalog, CATALOG_COLS, "catalog"),
                       cfg.get("require_address", True))
    os.makedirs(a.out, exist_ok=True)
    batches = supplier_batches(res, cat)
    for sup, batch in batches.items():
        with open(os.path.join(a.out, "supplier_%s.txt" % safe_name(sup)), "w", encoding="utf-8") as f:
            f.write(supplier_text(sup, batch, cat, texts) + "\n")
    ready = [o for o in res.orders.values() if o["ready"]]
    with open(os.path.join(a.out, "confirmations.txt"), "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(customer_text(o, cat, texts, currency) for o in ready) + ("\n" if ready else ""))
    with open(os.path.join(a.out, "orders_clean.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "status", "customer_name", "phone", "city", "address", "items", "total", "problems"])
        for o in res.orders.values():
            items = "; ".join("%s x %d" % (s, q) for s, q in o["lines"].items())
            w.writerow([cell(v) for v in (o["id"], "ready" if o["ready"] else "needs attention", o["customer_name"],
                                          o["phone"], o["city"], o["address"], items, fmt(o["total"]),
                                          ", ".join(sorted(set(o["errors"]))))])
    errs = [p for p in res.problems if p[1] == "error"]
    with open(os.path.join(a.out, "report.txt"), "w", encoding="utf-8") as f:
        f.write("Orders: %d, ready: %d, need attention: %d\nSuppliers with orders: %d\n" % (
            len(res.orders), len(ready), len(res.orders) - len(ready), len(batches)))
        f.write("Problems (line numbers are lines of the input file, header is line 1):\n")
        for line, level, msg in sorted(res.problems):
            f.write("  line %d [%s] %s\n" % (line, level, msg))
        if not res.problems:
            f.write("  none\n")
    print("orders %d, ready %d, need attention %d, problems %d -> %s" % (
        len(res.orders), len(ready), len(res.orders) - len(ready), len(res.problems), a.out))
    return 2 if (a.strict and errs) else 0


if __name__ == "__main__":
    sys.exit(main())
