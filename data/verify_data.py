"""Data Verification Script for sales.db

Validates:
1. Row counts across all 4 tables
2. No orphan foreign keys in fact_sales
3. Full coverage: Every customer and every product has at least one sale
4. Mathematical formula integrity (Discount, Tax, Sales, Cost ratio 50-85%, Profit)
5. Trap conditions:
   - Duplicate customer names exist
   - Sub_Category shared across multiple Categories
   - Common column names across tables (Customer_ID, Product_ID, Date_ID, Unit_Price)
6. Index existence
"""

import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
DB_PATH = DATA_DIR / "sales.db"


def run_verification():
    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} does not exist. Run generate_data.py first.")
        return False

    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    cursor = conn.cursor()
    all_passed = True
    report = []

    report.append("==================================================")
    report.append("          SALES DATABASE VERIFICATION REPORT       ")
    report.append("==================================================")

    # 1. Row counts
    counts = {}
    for table in ["dim_customer", "dim_product", "dim_date", "fact_sales"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        cnt = cursor.fetchone()[0]
        counts[table] = cnt
        report.append(f"Table {table:<15}: {cnt:>6} rows")

    if counts["dim_customer"] < 1000 or counts["dim_customer"] > 2500:
        report.append("  [FAIL] dim_customer row count out of required range (1000-2500)")
        all_passed = False
    if counts["dim_product"] < 300 or counts["dim_product"] > 750:
        report.append("  [FAIL] dim_product row count out of required range (300-750)")
        all_passed = False
    if counts["dim_date"] < 61:
        report.append("  [FAIL] dim_date row count < 61 days")
        all_passed = False
    if counts["fact_sales"] < 30000 or counts["fact_sales"] > 100000:
        report.append("  [FAIL] fact_sales row count out of required range (30000-100000)")
        all_passed = False

    # 2. Orphan keys check
    report.append("\n--- Referential Integrity Check (No Orphan Keys) ---")
    cursor.execute("""
        SELECT COUNT(*) FROM fact_sales f 
        LEFT JOIN dim_customer c ON f.Customer_ID = c.Customer_ID 
        WHERE c.Customer_ID IS NULL
    """)
    orphan_cust = cursor.fetchone()[0]
    report.append(f"Orphan Customer IDs in fact_sales: {orphan_cust}")
    if orphan_cust > 0:
        all_passed = False

    cursor.execute("""
        SELECT COUNT(*) FROM fact_sales f 
        LEFT JOIN dim_product p ON f.Product_ID = p.Product_ID 
        WHERE p.Product_ID IS NULL
    """)
    orphan_prod = cursor.fetchone()[0]
    report.append(f"Orphan Product IDs in fact_sales: {orphan_prod}")
    if orphan_prod > 0:
        all_passed = False

    cursor.execute("""
        SELECT COUNT(*) FROM fact_sales f 
        LEFT JOIN dim_date d ON f.Date_ID = d.Date_ID 
        WHERE d.Date_ID IS NULL
    """)
    orphan_date = cursor.fetchone()[0]
    report.append(f"Orphan Date IDs in fact_sales: {orphan_date}")
    if orphan_date > 0:
        all_passed = False

    # 3. Coverage check: Every customer and product in at least one sale
    report.append("\n--- Coverage Check ---")
    cursor.execute("""
        SELECT COUNT(*) FROM dim_customer c 
        LEFT JOIN fact_sales f ON c.Customer_ID = f.Customer_ID 
        WHERE f.Transaction_ID IS NULL
    """)
    unsold_cust = cursor.fetchone()[0]
    report.append(f"Customers without any sales: {unsold_cust}")
    if unsold_cust > 0:
        all_passed = False

    cursor.execute("""
        SELECT COUNT(*) FROM dim_product p 
        LEFT JOIN fact_sales f ON p.Product_ID = f.Product_ID 
        WHERE f.Transaction_ID IS NULL
    """)
    unsold_prod = cursor.fetchone()[0]
    report.append(f"Products without any sales: {unsold_prod}")
    if unsold_prod > 0:
        all_passed = False

    # 4. Formula integrity
    report.append("\n--- Formula Integrity Check ---")
    cursor.execute("""
        SELECT COUNT(*) FROM fact_sales
        WHERE ABS(Discount_Amount - ROUND(Quantity * Unit_Price * Discount_Percent / 100.0, 2)) > 0.015
    """)
    bad_disc = cursor.fetchone()[0]
    report.append(f"Violations in Discount_Amount formula: {bad_disc}")
    if bad_disc > 0:
        all_passed = False

    cursor.execute("""
        SELECT COUNT(*) FROM fact_sales
        WHERE ABS(Tax_Amount - ROUND((Quantity * Unit_Price - Discount_Amount) * Tax_Percent / 100.0, 2)) > 0.015
    """)
    bad_tax = cursor.fetchone()[0]
    report.append(f"Violations in Tax_Amount formula: {bad_tax}")
    if bad_tax > 0:
        all_passed = False

    cursor.execute("""
        SELECT COUNT(*) FROM fact_sales
        WHERE ABS(Sales_Amount - ROUND(Quantity * Unit_Price - Discount_Amount + Tax_Amount, 2)) > 0.015
    """)
    bad_sales = cursor.fetchone()[0]
    report.append(f"Violations in Sales_Amount formula: {bad_sales}")
    if bad_sales > 0:
        all_passed = False

    cursor.execute("""
        SELECT COUNT(*) FROM fact_sales
        WHERE Cost_Amount < ROUND((Quantity * Unit_Price - Discount_Amount) * 0.499, 2)
           OR Cost_Amount > ROUND((Quantity * Unit_Price - Discount_Amount) * 0.851, 2)
    """)
    bad_cost = cursor.fetchone()[0]
    report.append(f"Violations in Cost_Amount ratio (50% to 85%): {bad_cost}")
    if bad_cost > 0:
        all_passed = False

    cursor.execute("""
        SELECT COUNT(*) FROM fact_sales
        WHERE ABS(Profit_Amount - ROUND(Sales_Amount - Cost_Amount - Tax_Amount, 2)) > 0.015
    """)
    bad_profit = cursor.fetchone()[0]
    report.append(f"Violations in Profit_Amount formula: {bad_profit}")
    if bad_profit > 0:
        all_passed = False

    # 5. Trap features check
    report.append("\n--- Trap Features Check ---")
    cursor.execute("""
        SELECT Customer_Name, COUNT(*) FROM dim_customer
        GROUP BY Customer_Name
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC
        LIMIT 5
    """)
    dupe_names = cursor.fetchall()
    report.append(f"Duplicate Customer Names verified: {len(dupe_names)} top samples: {dupe_names}")
    if len(dupe_names) == 0:
        report.append("  [FAIL] No duplicate customer names found!")
        all_passed = False

    cursor.execute("""
        SELECT Sub_Category, COUNT(DISTINCT Category) FROM dim_product
        GROUP BY Sub_Category
    """)
    sub_cat_dist = cursor.fetchall()
    report.append(f"Sub_Category multi-category presence: {sub_cat_dist}")
    for sc, cat_cnt in sub_cat_dist:
        if cat_cnt < 2:
            report.append(f"  [FAIL] Sub_Category {sc} is in only {cat_cnt} category!")
            all_passed = False

    # Check shared column names
    shared_cols = ["Customer_ID", "Product_ID", "Date_ID", "Unit_Price"]
    for col in shared_cols:
        cursor.execute(f"SELECT COUNT(*) FROM pragma_table_info('fact_sales') WHERE name='{col}'")
        in_fact = cursor.fetchone()[0]
        # Check other tables
        in_dims = 0
        for dt in ["dim_customer", "dim_product", "dim_date"]:
            cursor.execute(f"SELECT COUNT(*) FROM pragma_table_info('{dt}') WHERE name='{col}'")
            in_dims += cursor.fetchone()[0]
        report.append(f"Column '{col}' present in fact_sales: {in_fact > 0}, present in dim tables: {in_dims > 0}")
        if not (in_fact > 0 and in_dims > 0):
            all_passed = False

    # 6. Indexes
    report.append("\n--- Index Verification ---")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='fact_sales'")
    indexes = [row[0] for row in cursor.fetchall()]
    report.append(f"Indexes on fact_sales: {indexes}")
    expected_indexes = ["idx_fact_sales_customer", "idx_fact_sales_product", "idx_fact_sales_date"]
    for ei in expected_indexes:
        if ei not in indexes:
            report.append(f"  [FAIL] Missing index: {ei}")
            all_passed = False

    report.append("\n==================================================")
    report.append(f"OVERALL STATUS: {'PASSED (ALL CHECKS SUCCEEDED)' if all_passed else 'FAILED'}")
    report.append("==================================================")

    conn.close()
    full_report_text = "\n".join(report)
    print(full_report_text)
    return all_passed, full_report_text


if __name__ == "__main__":
    run_verification()
