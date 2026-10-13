import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from order_suite.__main__ import cell, main, safe_name  # noqa: E402
from order_suite.core import normalize_phone, parse_money, parse_qty, process, read_table, supplier_batches  # noqa: E402

EX = os.path.join(ROOT, "examples")
CAT = "sku,name,supplier,price,cost\nA,Alpha,S1,100,60\nB,Beta,S2,\"1 250,50\",800\n"
HEAD = "order_id,customer_name,phone,city,address,sku,qty\n"


def run(orders, cat=CAT, **kw):
    _, o = read_table(HEAD + orders)
    _, c = read_table(cat)
    return process(o, c, **kw)


class ParseTests(unittest.TestCase):
    def test_phones(self):
        self.assertEqual(normalize_phone("050 000 00 01"), "+380500000001")
        self.assertEqual(normalize_phone("(050)000-00-01"), "+380500000001")
        self.assertEqual(normalize_phone("380500000001"), "+380500000001")
        self.assertEqual(normalize_phone("80500000001"), "+380500000001")
        self.assertEqual(normalize_phone("+49 30 1234567"), "+49301234567")
        for bad in ("12345", "", None, "+12", "05000000", "abc"):
            self.assertIsNone(normalize_phone(bad))

    def test_money(self):
        self.assertEqual(parse_money("1 250,50"), Decimal("1250.50"))
        self.assertEqual(parse_money("1.234,56"), Decimal("1234.56"))
        self.assertEqual(parse_money("1,234.56"), Decimal("1234.56"))
        self.assertEqual(parse_money("120 грн"), Decimal("120"))
        self.assertEqual(parse_money("0"), Decimal("0"))
        for bad in ("", "abc", "-5", None):
            self.assertIsNone(parse_money(bad))

    def test_qty(self):
        self.assertEqual(parse_qty("3"), 3)
        for bad in ("0", "-1", "1.5", "x", "", "10001"):
            self.assertIsNone(parse_qty(bad))

    def test_table_semicolon_bom_and_blank_lines(self):
        head, rows = read_table("﻿sku;name\nA;Alpha\n\n;;\nB;Beta\n")
        self.assertEqual(head, ["sku", "name"])
        self.assertEqual([(i, r["sku"]) for i, r in rows], [(2, "A"), (5, "B")])


class ProcessTests(unittest.TestCase):
    def test_good_order(self):
        res, _ = run("1,Ann,0500000001,Kyiv,St 1,A,2\n1,Ann,0500000001,Kyiv,St 1,B,1\n")
        o = res.orders["1"]
        self.assertTrue(o["ready"])
        self.assertEqual(o["total"], Decimal("1450.50"))
        self.assertEqual(o["phone"], "+380500000001")
        self.assertEqual(res.problems, [])

    def test_problems_have_line_numbers(self):
        res, _ = run("1,Ann,0500000001,Kyiv,St 1,A,2\n2,Bob,123,Kyiv,St 2,A,1\n3,Cy,0500000003,Kyiv,St 3,ZZZ,1\n")
        lines = {(l, m.split(":")[0]) for l, lv, m in res.problems}
        self.assertIn((3, "order 2"), lines)
        self.assertIn((4, "order 3"), lines)
        self.assertTrue(res.orders["1"]["ready"])
        self.assertFalse(res.orders["2"]["ready"])
        self.assertFalse(res.orders["3"]["ready"])

    def test_conflicting_customer_data_in_one_order(self):
        res, _ = run("1,Ann,0500000001,Kyiv,St 1,A,1\n1,Bob,0500000001,Kyiv,St 1,B,1\n")
        self.assertFalse(res.orders["1"]["ready"])
        self.assertTrue(any("differs" in m for _, _, m in res.problems))

    def test_repeated_sku_is_added_with_warning(self):
        res, _ = run("1,Ann,0500000001,Kyiv,St 1,A,1\n1,Ann,0500000001,Kyiv,St 1,A,2\n")
        self.assertEqual(res.orders["1"]["lines"], {"A": 3})
        self.assertTrue(any(lv == "warning" for _, lv, _ in res.problems))
        self.assertTrue(res.orders["1"]["ready"])

    def test_empty_order_id_and_missing_address(self):
        res, _ = run(",Ann,0500000001,Kyiv,St 1,A,1\n2,Bob,0500000002,,,A,1\n")
        self.assertNotIn("", res.orders)
        self.assertFalse(res.orders["2"]["ready"])
        res2, _ = run("2,Bob,0500000002,,,A,1\n", require_address=False)
        self.assertTrue(res2.orders["2"]["ready"])

    def test_bad_catalog_rows_are_reported(self):
        res, cat = run("1,Ann,0500000001,Kyiv,St 1,A,1\n", cat="sku,name,supplier,price\nA,Alpha,S1,100\nA,Dup,S1,5\nC,NoPrice,S1,abc\n")
        self.assertEqual(set(cat), {"A"})
        self.assertEqual(cat["A"]["price"], Decimal(100))
        self.assertEqual(len([p for p in res.problems if p[0] in (3, 4)]), 2)

    def test_split_between_suppliers(self):
        res, cat = run("1,Ann,0500000001,Kyiv,St 1,A,1\n1,Ann,0500000001,Kyiv,St 1,B,2\n")
        b = supplier_batches(res, cat)
        self.assertEqual(set(b), {"S1", "S2"})
        self.assertEqual(b["S2"][0][1], [("B", 2)])

    def test_orders_with_errors_never_reach_suppliers(self):
        res, cat = run("1,Ann,bad,Kyiv,St 1,A,1\n")
        self.assertEqual(supplier_batches(res, cat), {})


class CliTests(unittest.TestCase):
    def go(self, *extra):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        with redirect_stdout(io.StringIO()):
            code = main(["--orders", os.path.join(EX, "orders.csv"), "--catalog", os.path.join(EX, "catalog.csv"),
                         "--out", d.name] + list(extra))
        return d.name, code

    def read(self, d, name):
        with open(os.path.join(d, name), encoding="utf-8") as f:
            return f.read()

    def test_example_run(self):
        d, code = self.go()
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(d)), ["confirmations.txt", "orders_clean.csv", "report.txt",
                                                  "supplier_Supplier_A.txt", "supplier_Supplier_B.txt"])
        rep = self.read(d, "report.txt")
        self.assertIn("ready: 2", rep)
        self.assertIn("line 5 [error] order 1003", rep)
        self.assertIn("Cost of goods: 210", self.read(d, "supplier_Supplier_A.txt"))
        self.assertIn("Total: 1490.5 UAH", self.read(d, "confirmations.txt"))
        self.assertNotIn("1003", self.read(d, "confirmations.txt"))

    def test_strict_exit_code(self):
        _, code = self.go("--strict")
        self.assertEqual(code, 2)

    def test_formula_cells_are_neutralised(self):
        self.assertEqual(cell("=1+1"), "'=1+1")
        self.assertEqual(cell("@x"), "'@x")
        self.assertEqual(cell("+380500000001"), "+380500000001")
        self.assertEqual(cell("Ann"), "Ann")

    def test_missing_column_message(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "o.csv")
            with open(p, "w") as f:
                f.write("order_id,qty\n1,2\n")
            with self.assertRaises(SystemExit) as cm:
                main(["--orders", p, "--catalog", os.path.join(EX, "catalog.csv"), "--out", d])
            self.assertIn("missing columns", str(cm.exception))

    def test_safe_name(self):
        self.assertEqual(safe_name("../etc/x y"), "___etc_x_y")


if __name__ == "__main__":
    unittest.main()
