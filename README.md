# order-automation-suite

Turns a shop's order export (CSV) into **checked orders, one message per supplier, and a confirmation text per customer**, with a row-by-row problem report. Python standard library only, runs locally, no internet, no accounts.

## What it does
- Reads `orders.csv` (one row per item) and `catalog.csv` (sku, name, supplier, price, optional cost). Comma or semicolon, UTF-8 (with or without BOM).
- Rows with the same `order_id` form one order. Checks, with the **line number of the input file** for every problem:
  - phone: Ukrainian numbers (`050 000 00 01`, `380…`, `80…`) become `+380XXXXXXXXX`; other numbers are accepted only with a leading `+`;
  - `qty` is a whole number from 1 to 10000; the `sku` exists in the catalog; name, city and address are present (address can be made optional);
  - customer data that differs between rows of one order is reported, not silently merged; a repeated sku in one order is added up with a warning; prices like `1 250,50` or `1.234,56` are read correctly.
- Only **orders without errors** are sent on: grouped by supplier into `supplier_<name>.txt` (customer delivery details, items, and your cost of goods if the catalog has a `cost` column) and into `confirmations.txt` for the customers.
- Orders with errors are listed in `orders_clean.csv` as "needs attention" and in `report.txt`. Nothing is guessed or fixed silently.
- Cells in the output CSV that would be run as a formula by Excel (start with `=`, `+`, `-`, `@`) are made plain text.

## Quick start
```bash
PYTHONPATH=src python3 -m order_suite --orders examples/orders.csv --catalog examples/catalog.csv --out out
# optional: --config examples/config.example.json (texts, currency, require_address), --strict (exit code 2 if any order has an error)
```
Tests: `python3 -m unittest discover -s tests` (no internet).

Required columns: orders `order_id, customer_name, phone, city, address, sku, qty`; catalog `sku, name, supplier, price` (+ optional `cost`). The examples use fake people and numbers.

## Limits (read this)
- It **prepares texts and tables; it does not send anything**. Sending to a supplier or customer (Telegram, e-mail, Nova Poshta) is your step.
- One currency, no discounts, delivery fees, stock levels or tax. Totals are price × quantity only.
- Phone rules are built for Ukrainian numbers; other countries only with `+` and 8–15 digits, without checking the real numbering plan.
- The catalog must already hold your sku codes; matching of free-text product names to sku is a different tool.
- Texts are fixed templates (`texts` in the config), one language per run.
- Run it on a copy of your export; it never changes the input files.

MIT license.

---

# order-automation-suite (українською)

Перетворює експорт замовлень магазину (CSV) на перевірені замовлення, повідомлення для кожного постачальника та підтвердження для клієнтів, зі звітом про проблеми з номерами рядків. Лише стандартна бібліотека Python, працює локально.

**Запуск:** `PYTHONPATH=src python3 -m order_suite --orders orders.csv --catalog catalog.csv --out out`. Телефони приводяться до `+380…`, замовлення з помилками не потрапляють до постачальників, а виносяться у `report.txt`.

**Важливо:** програма нічого не надсилає, лише готує тексти й таблиці; одна валюта, без знижок і доставки; перевірка телефонів розрахована на українські номери.
