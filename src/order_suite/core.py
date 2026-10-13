import csv
import io
import re
from decimal import Decimal, InvalidOperation

ORDER_COLS = ["order_id", "customer_name", "phone", "city", "address", "sku", "qty"]
CATALOG_COLS = ["sku", "name", "supplier", "price"]
CUSTOMER_FIELDS = ("customer_name", "phone", "city", "address")


def read_table(text):
    """CSV text -> list of (line_number, dict). Header is line 1. Delimiter , or ; is detected. Keys are lower-case."""
    text = text.lstrip("﻿")
    first = text.split("\n", 1)[0]
    delim = ";" if first.count(";") > first.count(",") else ","
    rd = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(rd)
    if not rows:
        return [], []
    head = [h.strip().lower() for h in rows[0]]
    out = []
    for i, r in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in r):
            continue
        out.append((i, {head[j]: (r[j].strip() if j < len(r) else "") for j in range(len(head))}))
    return head, out


def normalize_phone(s):
    """Ukrainian numbers -> +380XXXXXXXXX. Other numbers are accepted only with a leading + and 8-15 digits."""
    raw = (s or "").strip()
    d = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        return "+" + d if 8 <= len(d) <= 15 else None
    if len(d) == 10 and d.startswith("0"):
        return "+38" + d
    if len(d) == 12 and d.startswith("380"):
        return "+" + d
    if len(d) == 11 and d.startswith("80"):
        return "+3" + d
    return None


def parse_money(s):
    t = re.sub(r"[^\d,.\-]", "", (s or "").replace("\xa0", ""))
    if not t:
        return None
    if "," in t and "." in t:  # the last separator is the decimal one
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("," if dec == "." else ".", "").replace(dec, ".")
    else:
        t = t.replace(",", ".")
    try:
        v = Decimal(t)
    except InvalidOperation:
        return None
    return v if v >= 0 else None


def parse_qty(s):
    t = (s or "").strip()
    return int(t) if t.isdigit() and 0 < int(t) <= 10000 else None


class Result:
    def __init__(self):
        self.orders, self.problems = {}, []  # problems: (line, "error"|"warning", message)

    def add(self, line, level, msg):
        self.problems.append((line, level, msg))


def load_catalog(rows, res):
    cat = {}
    for line, r in rows:
        sku = r.get("sku", "")
        price = parse_money(r.get("price", ""))
        if not sku or not r.get("supplier") or price is None:
            res.add(line, "error", "catalog row needs sku, supplier and a readable price (row skipped)")
            continue
        if sku in cat:
            res.add(line, "warning", "duplicate sku %s in the catalog: the first row is used" % sku)
            continue
        cost = parse_money(r.get("cost", "")) if r.get("cost") else None
        cat[sku] = {"name": r.get("name") or sku, "supplier": r["supplier"], "price": price, "cost": cost}
    return cat


def process(order_rows, catalog_rows, require_address=True):
    res = Result()
    cat = load_catalog(catalog_rows, res)
    bad = set()
    for line, r in order_rows:
        oid = r.get("order_id", "")
        if not oid:
            res.add(line, "error", "order_id is empty (row skipped)")
            continue
        o = res.orders.setdefault(oid, {"id": oid, "lines": {}, "errors": [], "first_line": line, **{k: r.get(k, "") for k in CUSTOMER_FIELDS}})
        for k in CUSTOMER_FIELDS:
            if r.get(k) and o[k] and r[k] != o[k]:
                res.add(line, "error", "order %s: %s differs from the first row of the same order" % (oid, k))
                o["errors"].append("conflict in %s" % k)
            elif r.get(k) and not o[k]:
                o[k] = r[k]
        sku, qty = r.get("sku", ""), parse_qty(r.get("qty", ""))
        if qty is None:
            res.add(line, "error", "order %s: qty must be a whole number from 1 to 10000, got %r" % (oid, r.get("qty", "")))
            o["errors"].append("bad qty")
        if sku not in cat:
            res.add(line, "error", "order %s: sku %r is not in the catalog" % (oid, sku))
            o["errors"].append("unknown sku")
        if qty is not None and sku in cat:
            if sku in o["lines"]:
                res.add(line, "warning", "order %s: sku %s repeated, quantities added" % (oid, sku))
            o["lines"][sku] = o["lines"].get(sku, 0) + qty
    for oid, o in res.orders.items():
        ph = normalize_phone(o["phone"])
        if ph is None:
            res.add(o["first_line"], "error", "order %s: phone %r is not a valid number" % (oid, o["phone"]))
            o["errors"].append("bad phone")
        o["phone"] = ph or o["phone"]
        if not o["customer_name"]:
            res.add(o["first_line"], "error", "order %s: customer_name is empty" % oid)
            o["errors"].append("no name")
        if require_address and not (o["city"] and o["address"]):
            res.add(o["first_line"], "error", "order %s: city and address are required" % oid)
            o["errors"].append("no address")
        if not o["lines"]:
            o["errors"].append("no valid items")
        o["ready"] = not o["errors"]
        o["total"] = sum((cat[s]["price"] * q for s, q in o["lines"].items()), Decimal(0))
    return res, cat


def supplier_batches(res, cat):
    """Ready orders only, grouped by supplier -> {supplier: [(order, [(sku, qty)])]}."""
    out = {}
    for o in res.orders.values():
        if not o["ready"]:
            continue
        per = {}
        for sku, q in o["lines"].items():
            per.setdefault(cat[sku]["supplier"], []).append((sku, q))
        for sup, items in per.items():
            out.setdefault(sup, []).append((o, items))
    return out


def fmt(d):
    return ("%.2f" % d).rstrip("0").rstrip(".")


def supplier_text(sup, batch, cat, texts):
    lines, cost = [], Decimal(0)
    for o, items in batch:
        lines.append("#%s - %s, %s, %s, %s" % (o["id"], o["customer_name"], o["phone"], o["city"], o["address"]))
        for sku, q in items:
            lines.append("  %s %s x %d" % (sku, cat[sku]["name"], q))
            if cat[sku]["cost"] is not None:
                cost += cat[sku]["cost"] * q
    head = texts["supplier_head"].format(supplier=sup, count=len(batch))
    foot = texts["supplier_cost"].format(cost=fmt(cost)) if cost else ""
    return "\n".join([head] + lines + ([foot] if foot else []))


def customer_text(o, cat, texts, currency):
    lines = ["%s x %d" % (cat[s]["name"], q) for s, q in o["lines"].items()]
    return texts["customer"].format(order_id=o["id"], name=o["customer_name"], lines="\n".join(lines),
                                    total=fmt(o["total"]), currency=currency)
