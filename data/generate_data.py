"""Data Generation Script for Sales Analytics Database

Generates:
- dim_customer (1,500 rows, with non-unique customer names)
- dim_product (400 rows, shared sub-categories across categories, Unit_Price list price)
- dim_date (61 rows covering 2026-10-01 to 2026-11-30)
- fact_sales (45,000 rows, every customer and product appears, strict financial formulas)
- Creates required indexes on foreign keys
- Includes data traps:
  * Non-unique customer names (e.g. multiple "John Smith"s)
  * Sub_Category shared across multiple Categories ('Luxury', 'Premium', 'Basic')
  * Shared column names across tables: Customer_ID, Product_ID, Date_ID, Unit_Price
"""

import os
import random
import sqlite3
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


def round_cur(val) -> float:
    return float(Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

# Set fixed random seed for 100% reproducibility
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

DATA_DIR = Path(__file__).resolve().parent
DB_PATH = DATA_DIR / "sales.db"

NUM_CUSTOMERS = 1500
NUM_PRODUCTS = 400
NUM_SALES = 45000

START_DATE = date(2026, 10, 1)
END_DATE = date(2026, 11, 30)

CATEGORIES = ["Electronics", "Furniture", "Office Supplies", "Apparel", "Home & Kitchen"]
SUB_CATEGORIES = ["Luxury", "Premium", "Basic"] # Shared tier across categories

BRANDS = [
    "Apex", "Nova", "Zenith", "Quantum", "Vanguard",
    "Pinnacle", "Starlight", "Hyperion", "Aurora", "Titan",
    "Nexus", "Olympus", "Aura", "Solstice", "Eclipse"
]

SEGMENTS = ["Consumer", "Corporate", "Enterprise", "Small Business"]

CITIES_STATES = [
    ("New York", "NY"), ("Los Angeles", "CA"), ("Chicago", "IL"), ("Houston", "TX"),
    ("Phoenix", "AZ"), ("Philadelphia", "PA"), ("San Antonio", "TX"), ("San Diego", "CA"),
    ("Dallas", "TX"), ("San Jose", "CA"), ("Austin", "TX"), ("Jacksonville", "FL"),
    ("Fort Worth", "TX"), ("Columbus", "OH"), ("Charlotte", "NC"), ("San Francisco", "CA"),
    ("Indianapolis", "IN"), ("Seattle", "WA"), ("Denver", "CO"), ("Washington", "DC"),
    ("Boston", "MA"), ("El Paso", "TX"), ("Nashville", "TN"), ("Detroit", "MI"),
    ("Portland", "OR"), ("Las Vegas", "NV"), ("Atlanta", "GA"), ("Miami", "FL")
]

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
    "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker"
]

# Intentionally force duplicate names for trap questions
SHARED_NAMES = [
    "John Smith", "David Miller", "Michael Brown", "Sarah Johnson",
    "James Williams", "Emily Davis", "Robert Jones", "Jessica Garcia"
]


def create_schema(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS fact_sales")
    cursor.execute("DROP TABLE IF EXISTS dim_customer")
    cursor.execute("DROP TABLE IF EXISTS dim_product")
    cursor.execute("DROP TABLE IF EXISTS dim_date")

    cursor.execute("""
    CREATE TABLE dim_customer (
        Customer_ID INTEGER PRIMARY KEY,
        Customer_Name TEXT NOT NULL,
        Email TEXT NOT NULL,
        City TEXT NOT NULL,
        State TEXT NOT NULL,
        Customer_Segment TEXT NOT NULL,
        Customer_Age INTEGER NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE dim_product (
        Product_ID INTEGER PRIMARY KEY,
        Product_Name TEXT NOT NULL,
        Category TEXT NOT NULL,
        Sub_Category TEXT NOT NULL,
        Brand TEXT NOT NULL,
        Unit_Price REAL NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE dim_date (
        Date_ID INTEGER PRIMARY KEY,
        Date TEXT NOT NULL,
        Year INTEGER NOT NULL,
        Quarter INTEGER NOT NULL,
        Month INTEGER NOT NULL,
        Month_Name TEXT NOT NULL,
        Week INTEGER NOT NULL,
        Day INTEGER NOT NULL,
        Day_Name TEXT NOT NULL,
        Is_Weekend INTEGER NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE fact_sales (
        Transaction_ID INTEGER PRIMARY KEY,
        Date_ID INTEGER NOT NULL,
        Customer_ID INTEGER NOT NULL,
        Product_ID INTEGER NOT NULL,
        Quantity INTEGER NOT NULL,
        Unit_Price REAL NOT NULL,
        Discount_Percent REAL NOT NULL,
        Discount_Amount REAL NOT NULL,
        Tax_Percent REAL NOT NULL,
        Tax_Amount REAL NOT NULL,
        Sales_Amount REAL NOT NULL,
        Cost_Amount REAL NOT NULL,
        Profit_Amount REAL NOT NULL,
        FOREIGN KEY (Date_ID) REFERENCES dim_date(Date_ID),
        FOREIGN KEY (Customer_ID) REFERENCES dim_customer(Customer_ID),
        FOREIGN KEY (Product_ID) REFERENCES dim_product(Product_ID)
    )
    """)
    conn.commit()


def generate_dim_date(conn: sqlite3.Connection):
    cursor = conn.cursor()
    curr_date = START_DATE
    date_rows = []
    
    while curr_date <= END_DATE:
        date_id = int(curr_date.strftime("%Y%m%d"))
        date_str = curr_date.strftime("%Y-%m-%d")
        year = curr_date.year
        quarter = (curr_date.month - 1) // 3 + 1
        month = curr_date.month
        month_name = curr_date.strftime("%B")
        week = int(curr_date.strftime("%W"))
        day = curr_date.day
        day_name = curr_date.strftime("%A")
        is_weekend = 1 if curr_date.weekday() >= 5 else 0

        date_rows.append((
            date_id, date_str, year, quarter, month, month_name, week, day, day_name, is_weekend
        ))
        curr_date += timedelta(days=1)

    cursor.executemany("""
    INSERT INTO dim_date (
        Date_ID, Date, Year, Quarter, Month, Month_Name, Week, Day, Day_Name, Is_Weekend
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, date_rows)
    conn.commit()
    print(f"Generated {len(date_rows)} dates in dim_date ({START_DATE} to {END_DATE}).")
    return [r[0] for r in date_rows]


def generate_dim_customer(conn: sqlite3.Connection):
    cursor = conn.cursor()
    customer_rows = []
    
    # Reserve first ~30 customers with duplicated names for trap questions
    name_pool = list(SHARED_NAMES) * 4 # Duplicate names
    while len(name_pool) < NUM_CUSTOMERS:
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        name_pool.append(f"{first} {last}")
    
    random.shuffle(name_pool)
    
    for cust_id in range(1, NUM_CUSTOMERS + 1):
        name = name_pool[cust_id - 1]
        clean_name = name.lower().replace(" ", ".")
        email = f"{clean_name}{cust_id}@example.com"
        city, state = random.choice(CITIES_STATES)
        segment = random.choice(SEGMENTS)
        age = random.randint(18, 75)
        
        customer_rows.append((
            cust_id, name, email, city, state, segment, age
        ))

    cursor.executemany("""
    INSERT INTO dim_customer (
        Customer_ID, Customer_Name, Email, City, State, Customer_Segment, Customer_Age
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, customer_rows)
    conn.commit()
    print(f"Generated {len(customer_rows)} customers in dim_customer (with trap duplicate names).")
    return [r[0] for r in customer_rows]


def generate_dim_product(conn: sqlite3.Connection):
    cursor = conn.cursor()
    product_rows = []
    
    # Ensure every category has every sub-category tier
    base_names = [
        "Pro Book", "Ultra Phone", "Smart TV", "Noise-Cancelling Headphones", "Gaming Console",
        "Ergonomic Chair", "Executive Desk", "Filing Cabinet", "Conference Table", "Bookshelf",
        "Gel Pen Pack", "Heavy-Duty Stapler", "Laser Paper Ream", "Dry Erase Board", "Desk Organizer",
        "Cotton Hoodie", "Tailored Suit", "Silk Tie", "Running Shoes", "Leather Jacket",
        "Espresso Machine", "Blender 3000", "Air Fryer Deluxe", "Chef Knife Set", "Cast Iron Skillet"
    ]

    for prod_id in range(1, NUM_PRODUCTS + 1):
        category = CATEGORIES[(prod_id - 1) % len(CATEGORIES)]
        sub_category = SUB_CATEGORIES[(prod_id - 1) % len(SUB_CATEGORIES)]
        brand = BRANDS[(prod_id - 1) % len(BRANDS)]
        base = base_names[(prod_id - 1) % len(base_names)]
        prod_name = f"{brand} {sub_category} {base} #{prod_id}"
        
        # Unit price based on tier
        if sub_category == "Luxury":
            unit_price = round(random.uniform(400.0, 1500.0), 2)
        elif sub_category == "Premium":
            unit_price = round(random.uniform(150.0, 450.0), 2)
        else: # Basic
            unit_price = round(random.uniform(15.0, 160.0), 2)
            
        product_rows.append((
            prod_id, prod_name, category, sub_category, brand, unit_price
        ))

    cursor.executemany("""
    INSERT INTO dim_product (
        Product_ID, Product_Name, Category, Sub_Category, Brand, Unit_Price
    ) VALUES (?, ?, ?, ?, ?, ?)
    """, product_rows)
    conn.commit()
    print(f"Generated {len(product_rows)} products in dim_product (shared sub-categories across categories).")
    return product_rows


def generate_fact_sales(conn: sqlite3.Connection, date_ids, customer_ids, product_rows):
    cursor = conn.cursor()
    sales_rows = []
    prod_dict = {p[0]: p[5] for p in product_rows} # Product_ID -> Unit_Price list price
    prod_ids = list(prod_dict.keys())

    # Guarantee: Every customer appears at least once
    # Guarantee: Every product appears at least once
    transaction_id = 1
    
    # 1. First assign each customer at least 1 transaction
    for cid in customer_ids:
        pid = random.choice(prod_ids)
        did = random.choice(date_ids)
        base_price = prod_dict[pid]
        # Sale price can vary slightly around list price (-5% to +5%)
        unit_price = round(base_price * random.uniform(0.95, 1.05), 2)
        qty = random.randint(1, 10)
        disc_pct = random.choice([0.0, 5.0, 10.0, 15.0, 20.0, 25.0])
        disc_amt = round_cur(Decimal(qty) * Decimal(str(unit_price)) * Decimal(str(disc_pct)) / Decimal(100))
        tax_pct = random.choice([0.0, 5.0, 7.5, 8.25, 10.0])
        tax_amt = round_cur((Decimal(qty) * Decimal(str(unit_price)) - Decimal(str(disc_amt))) * Decimal(str(tax_pct)) / Decimal(100))
        sales_amt = round_cur(Decimal(qty) * Decimal(str(unit_price)) - Decimal(str(disc_amt)) + Decimal(str(tax_amt)))
        
        cost_ratio = round(random.uniform(0.50, 0.85), 4)
        cost_amt = round_cur((Decimal(qty) * Decimal(str(unit_price)) - Decimal(str(disc_amt))) * Decimal(str(cost_ratio)))
        profit_amt = round_cur(Decimal(str(sales_amt)) - Decimal(str(cost_amt)) - Decimal(str(tax_amt)))
        
        sales_rows.append((
            transaction_id, did, cid, pid, qty, unit_price,
            disc_pct, disc_amt, tax_pct, tax_amt, sales_amt, cost_amt, profit_amt
        ))
        transaction_id += 1

    # 2. Assign any unpicked products to make sure EVERY product is sold
    picked_pids = {r[3] for r in sales_rows}
    unpicked_pids = set(prod_ids) - picked_pids
    for pid in unpicked_pids:
        cid = random.choice(customer_ids)
        did = random.choice(date_ids)
        base_price = prod_dict[pid]
        unit_price = round(base_price * random.uniform(0.95, 1.05), 2)
        qty = random.randint(1, 10)
        disc_pct = random.choice([0.0, 5.0, 10.0, 15.0, 20.0])
        disc_amt = round_cur(Decimal(qty) * Decimal(str(unit_price)) * Decimal(str(disc_pct)) / Decimal(100))
        tax_pct = random.choice([0.0, 5.0, 8.0, 10.0])
        tax_amt = round_cur((Decimal(qty) * Decimal(str(unit_price)) - Decimal(str(disc_amt))) * Decimal(str(tax_pct)) / Decimal(100))
        sales_amt = round_cur(Decimal(qty) * Decimal(str(unit_price)) - Decimal(str(disc_amt)) + Decimal(str(tax_amt)))
        
        cost_ratio = round(random.uniform(0.50, 0.85), 4)
        cost_amt = round_cur((Decimal(qty) * Decimal(str(unit_price)) - Decimal(str(disc_amt))) * Decimal(str(cost_ratio)))
        profit_amt = round_cur(Decimal(str(sales_amt)) - Decimal(str(cost_amt)) - Decimal(str(tax_amt)))
        
        sales_rows.append((
            transaction_id, did, cid, pid, qty, unit_price,
            disc_pct, disc_amt, tax_pct, tax_amt, sales_amt, cost_amt, profit_amt
        ))
        transaction_id += 1

    # 3. Fill the rest up to NUM_SALES
    remaining = NUM_SALES - len(sales_rows)
    for _ in range(remaining):
        cid = random.choice(customer_ids)
        pid = random.choice(prod_ids)
        did = random.choice(date_ids)
        base_price = prod_dict[pid]
        unit_price = round(base_price * random.uniform(0.95, 1.05), 2)
        qty = random.randint(1, 15)
        disc_pct = random.choice([0.0, 0.0, 5.0, 10.0, 15.0, 20.0, 30.0])
        disc_amt = round_cur(Decimal(qty) * Decimal(str(unit_price)) * Decimal(str(disc_pct)) / Decimal(100))
        tax_pct = random.choice([0.0, 5.0, 6.0, 7.5, 8.25, 9.0, 10.0])
        tax_amt = round_cur((Decimal(qty) * Decimal(str(unit_price)) - Decimal(str(disc_amt))) * Decimal(str(tax_pct)) / Decimal(100))
        sales_amt = round_cur(Decimal(qty) * Decimal(str(unit_price)) - Decimal(str(disc_amt)) + Decimal(str(tax_amt)))
        
        cost_ratio = round(random.uniform(0.50, 0.85), 4)
        cost_amt = round_cur((Decimal(qty) * Decimal(str(unit_price)) - Decimal(str(disc_amt))) * Decimal(str(cost_ratio)))
        profit_amt = round_cur(Decimal(str(sales_amt)) - Decimal(str(cost_amt)) - Decimal(str(tax_amt)))
        
        sales_rows.append((
            transaction_id, did, cid, pid, qty, unit_price,
            disc_pct, disc_amt, tax_pct, tax_amt, sales_amt, cost_amt, profit_amt
        ))
        transaction_id += 1

    cursor.executemany("""
    INSERT INTO fact_sales (
        Transaction_ID, Date_ID, Customer_ID, Product_ID, Quantity, Unit_Price,
        Discount_Percent, Discount_Amount, Tax_Percent, Tax_Amount,
        Sales_Amount, Cost_Amount, Profit_Amount
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sales_rows)
    conn.commit()
    print(f"Generated {len(sales_rows)} transactions in fact_sales.")


def create_indexes(conn: sqlite3.Connection):
    cursor = conn.cursor()
    print("Creating indexes on fact_sales foreign keys...")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fact_sales_customer ON fact_sales(Customer_ID);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fact_sales_product ON fact_sales(Product_ID);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fact_sales_date ON fact_sales(Date_ID);")
    conn.commit()
    print("Indexes created successfully.")


def build_database():
    os.makedirs(DATA_DIR, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        print(f"Building SQLite database at: {DB_PATH}")
        create_schema(conn)
        date_ids = generate_dim_date(conn)
        cust_ids = generate_dim_customer(conn)
        prod_rows = generate_dim_product(conn)
        generate_fact_sales(conn, date_ids, cust_ids, prod_rows)
        create_indexes(conn)
        print("Database creation complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    build_database()
