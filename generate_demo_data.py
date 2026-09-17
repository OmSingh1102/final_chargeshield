"""Generate realistic demo data: 1,000 orders + 12 chargebacks.

Run once:  python generate_demo_data.py
Outputs:   static/orders_1000.csv, static/chargebacks_12.csv
"""

import csv
import random
import string
from datetime import datetime, timedelta

random.seed(42)

# ── Product Pool (40 sample products) ─────────────────────────────────────

PRODUCTS = [
    # Existing 10 from IngestionDemo
    {"id": "PROD-A1", "name": "Wireless Noise-Cancelling Headphones", "category": "Electronics", "price": 59.99, "return_days": 30},
    {"id": "PROD-A2", "name": "Smart Watch Ultra Pro", "category": "Electronics", "price": 245.00, "return_days": 30},
    {"id": "PROD-A3", "name": "LED Desk Lamp with USB Charger", "category": "Home", "price": 34.99, "return_days": 30},
    {"id": "PROD-A4", "name": "65-inch 4K Smart TV", "category": "Electronics", "price": 899.99, "return_days": 15},
    {"id": "PROD-A5", "name": "Espresso Machine Pro 3000", "category": "Home", "price": 349.99, "return_days": 30},
    {"id": "PROD-A6", "name": "Electric Standing Desk Frame", "category": "Home", "price": 289.00, "return_days": 30},
    {"id": "PROD-A7", "name": "Portable Bluetooth Speaker", "category": "Electronics", "price": 39.99, "return_days": 30},
    {"id": "PROD-B1", "name": "Silicone Phone Case - Galaxy S24", "category": "Electronics", "price": 14.99, "return_days": 14},
    {"id": "PROD-B2", "name": "Robot Vacuum Cleaner X500", "category": "Home", "price": 445.50, "return_days": 30},
    {"id": "PROD-B3", "name": "15g Nail Glue Press-On Kit", "category": "Beauty", "price": 12.99, "return_days": 0},
    # 30 new products
    {"id": "PROD-C01", "name": "Vitamin C Brightening Serum", "category": "Beauty", "price": 18.99, "return_days": 30},
    {"id": "PROD-C02", "name": "Velvet Matte Lip Kit (6-pack)", "category": "Beauty", "price": 24.99, "return_days": 14},
    {"id": "PROD-C03", "name": "LED Ring Light 12-inch", "category": "Electronics", "price": 29.99, "return_days": 30},
    {"id": "PROD-C04", "name": "Resistance Bands Set (5-pack)", "category": "Sports", "price": 16.99, "return_days": 30},
    {"id": "PROD-C05", "name": "Yoga Mat Non-Slip 6mm", "category": "Sports", "price": 22.99, "return_days": 30},
    {"id": "PROD-C06", "name": "Stainless Steel Water Bottle 32oz", "category": "Sports", "price": 19.99, "return_days": 30},
    {"id": "PROD-C07", "name": "Mini Portable Projector HD", "category": "Electronics", "price": 149.99, "return_days": 30},
    {"id": "PROD-C08", "name": "Aesthetic LED Strip Lights 50ft", "category": "Home", "price": 15.99, "return_days": 14},
    {"id": "PROD-C09", "name": "Cloud Slides Pillow Slippers", "category": "Fashion", "price": 19.99, "return_days": 30},
    {"id": "PROD-C10", "name": "Oversized Canvas Tote Bag", "category": "Fashion", "price": 14.99, "return_days": 30},
    {"id": "PROD-C11", "name": "Retro Polarized Sunglasses", "category": "Fashion", "price": 12.99, "return_days": 14},
    {"id": "PROD-C12", "name": "Aromatherapy Essential Oil Diffuser", "category": "Home", "price": 27.99, "return_days": 30},
    {"id": "PROD-C13", "name": "Electric Milk Frother Handheld", "category": "Home", "price": 11.99, "return_days": 30},
    {"id": "PROD-C14", "name": "Pop Fidget Toy Mega Pack", "category": "Toys", "price": 9.99, "return_days": 0},
    {"id": "PROD-C15", "name": "Magnetic Phone Mount for Car", "category": "Electronics", "price": 13.99, "return_days": 30},
    {"id": "PROD-C16", "name": "Hair Straightener Brush 2-in-1", "category": "Beauty", "price": 34.99, "return_days": 30},
    {"id": "PROD-C17", "name": "Wireless Earbuds with Charging Case", "category": "Electronics", "price": 27.99, "return_days": 30},
    {"id": "PROD-C18", "name": "Acne Patch Hydrocolloid (96ct)", "category": "Beauty", "price": 8.99, "return_days": 0},
    {"id": "PROD-C19", "name": "Portable Blender USB Rechargeable", "category": "Home", "price": 24.99, "return_days": 30},
    {"id": "PROD-C20", "name": "Sunset Lamp Projector", "category": "Home", "price": 19.99, "return_days": 14},
    {"id": "PROD-C21", "name": "Ice Roller for Face & Eyes", "category": "Beauty", "price": 7.99, "return_days": 0},
    {"id": "PROD-C22", "name": "Heated Blanket USB Throw", "category": "Home", "price": 39.99, "return_days": 30},
    {"id": "PROD-C23", "name": "Running Shoes Lightweight Mesh", "category": "Sports", "price": 44.99, "return_days": 30},
    {"id": "PROD-C24", "name": "Crossbody Sling Bag Nylon", "category": "Fashion", "price": 16.99, "return_days": 30},
    {"id": "PROD-C25", "name": "Smart Plug WiFi 4-Pack", "category": "Electronics", "price": 22.99, "return_days": 30},
    {"id": "PROD-C26", "name": "Cat Tree Tower 54-inch", "category": "Toys", "price": 59.99, "return_days": 30},
    {"id": "PROD-C27", "name": "Silicone Kitchen Utensil Set (12pc)", "category": "Home", "price": 24.99, "return_days": 30},
    {"id": "PROD-C28", "name": "Gel Nail Polish Kit UV Lamp", "category": "Beauty", "price": 32.99, "return_days": 14},
    {"id": "PROD-C29", "name": "Adjustable Dumbbell Set 25lb", "category": "Sports", "price": 79.99, "return_days": 30},
    {"id": "PROD-C30", "name": "Bucket Hat Reversible Cotton", "category": "Fashion", "price": 11.99, "return_days": 14},
]

# ── Geography Pool ──────────────────────────────────────────────────────────────

CITIES = [
    ("Austin", "TX"), ("Los Angeles", "CA"), ("Miami", "FL"), ("New York", "NY"),
    ("Chicago", "IL"), ("Houston", "TX"), ("Phoenix", "AZ"), ("San Diego", "CA"),
    ("Dallas", "TX"), ("Seattle", "WA"), ("Denver", "CO"), ("Atlanta", "GA"),
    ("Portland", "OR"), ("Nashville", "TN"), ("Charlotte", "NC"), ("Tampa", "FL"),
    ("Las Vegas", "NV"), ("Minneapolis", "MN"), ("San Antonio", "TX"), ("Columbus", "OH"),
    ("Indianapolis", "IN"), ("San Jose", "CA"), ("Jacksonville", "FL"), ("Memphis", "TN"),
    ("Oklahoma City", "OK"), ("Louisville", "KY"), ("Richmond", "VA"), ("Milwaukee", "WI"),
    ("Raleigh", "NC"), ("Salt Lake City", "UT"),
]

CARRIERS = ["UPS", "FedEx", "USPS", "Veho", "DHL"]
PROCESSORS = ["Adyen", "Stripe", "Braintree", "Worldpay"]

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Christopher", "Karen", "Daniel", "Lisa", "Matthew", "Nancy",
    "Anthony", "Betty", "Mark", "Margaret", "Steven", "Sandra", "Andrew", "Ashley",
    "Paul", "Dorothy", "Emily", "Brian", "Samantha", "Kevin", "Rachel", "Olivia",
]

EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "icloud.com", "hotmail.com"]

# ── Date Range ──────────────────────────────────────────────────────────────────

START_DATE = datetime(2026, 6, 1)
END_DATE = datetime(2026, 7, 10)
DATE_RANGE_DAYS = (END_DATE - START_DATE).days


def rand_date(start=START_DATE, days=DATE_RANGE_DAYS):
    d = start + timedelta(days=random.randint(0, days))
    h, m = random.randint(0, 23), random.randint(0, 59)
    return d.replace(hour=h, minute=m, second=0)


def rand_order_id(dt):
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"TTS-ORD-{dt.strftime('%Y%m%d')}-{suffix}"


def rand_card_last4():
    return f"{random.randint(1000, 9999)}"


def rand_ip():
    return f"{random.randint(20, 220)}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}"


def redact_email(name):
    domain = random.choice(EMAIL_DOMAINS)
    n = name.lower()
    if len(n) <= 2:
        return f"{n}***@{domain}"
    return f"{n[0]}***{n[-1]}@{domain}"


# ── Generate 1,000 Orders ──────────────────────────────────────────────────────

def generate_orders(n=1000):
    # Create ~700 unique customers, some repeat buyers
    num_customers = 700
    customer_ids = [f"CUST-{i:04d}" for i in range(1, num_customers + 1)]

    # Weight distribution: most customers buy once, some buy 2-5 times
    customer_pool = []
    for cid in customer_ids:
        r = random.random()
        if r < 0.60:
            repeats = 1
        elif r < 0.82:
            repeats = 2
        elif r < 0.92:
            repeats = 3
        elif r < 0.97:
            repeats = 4
        else:
            repeats = random.randint(5, 8)
        customer_pool.extend([cid] * repeats)

    random.shuffle(customer_pool)
    # Trim or extend to exactly n
    while len(customer_pool) < n:
        customer_pool.append(random.choice(customer_ids))
    customer_pool = customer_pool[:n]

    orders = []
    for i in range(n):
        product = random.choice(PRODUCTS)
        city, state = random.choice(CITIES)
        dt = rand_date()

        qty_roll = random.random()
        if qty_roll < 0.60:
            qty = 1
        elif qty_roll < 0.85:
            qty = 2
        elif qty_roll < 0.95:
            qty = 3
        else:
            qty = random.randint(4, 6)

        amount = round(product["price"] * qty, 2)

        pay_roll = random.random()
        if pay_roll < 0.55:
            payment_method = "Visa"
        elif pay_roll < 0.90:
            payment_method = "Mastercard"
        else:
            payment_method = random.choice(["Visa", "Mastercard"])

        stat_roll = random.random()
        if stat_roll < 0.85:
            payment_status = "Completed"
        elif stat_roll < 0.93:
            payment_status = "Refunded"
        elif stat_roll < 0.98:
            payment_status = "Pending"
        else:
            payment_status = "Failed"

        ff_roll = random.random()
        if ff_roll < 0.70:
            fulfillment = "Delivered"
        elif ff_roll < 0.82:
            fulfillment = "Shipped"
        elif ff_roll < 0.92:
            fulfillment = "Processing"
        elif ff_roll < 0.97:
            fulfillment = "Cancelled"
        else:
            fulfillment = "Returned"

        carrier = random.choice(CARRIERS) if fulfillment in ("Delivered", "Shipped", "Returned") else ""
        tracking = ""
        if carrier:
            if carrier == "UPS":
                tracking = f"1Z999AA1{random.randint(1000000000, 9999999999)}"
            elif carrier == "FedEx":
                tracking = f"{random.randint(100000000000, 999999999999)}"
            elif carrier == "USPS":
                tracking = f"9400111899{random.randint(100000, 999999)}"
            elif carrier == "Veho":
                tracking = f"VH{random.randint(100000000, 999999999)}"
            elif carrier == "DHL":
                tracking = f"JD{random.randint(10000000000, 99999999999)}"

        delivery_date = ""
        delivery_signed = ""
        if fulfillment == "Delivered":
            dd = dt + timedelta(days=random.randint(3, 7))
            delivery_date = dd.strftime("%Y-%m-%d")
            delivery_signed = "Yes" if random.random() < 0.60 else "No"
        elif fulfillment == "Returned":
            dd = dt + timedelta(days=random.randint(3, 7))
            delivery_date = dd.strftime("%Y-%m-%d")
            delivery_signed = "Yes" if random.random() < 0.40 else "No"

        avs_cvv = "Pass" if random.random() < 0.90 else "Fail"

        name = random.choice(FIRST_NAMES)

        orders.append({
            "order_id": rand_order_id(dt),
            "customer_id": customer_pool[i],
            "order_date": dt.strftime("%Y-%m-%d"),
            "product_name": product["name"],
            "product_category": product["category"],
            "product_id": product["id"],
            "quantity": qty,
            "unit_price": product["price"],
            "order_amount": amount,
            "payment_method": payment_method,
            "card_last_four": rand_card_last4(),
            "payment_status": payment_status,
            "fulfillment_status": fulfillment,
            "shipping_carrier": carrier,
            "tracking_number": tracking,
            "delivery_date": delivery_date,
            "delivery_signed": delivery_signed,
            "customer_email": redact_email(name),
            "customer_city": city,
            "customer_state": state,
            "return_policy_days": product["return_days"],
            "avs_cvv_match": avs_cvv,
            "customer_ip": rand_ip(),
        })

    return orders


# ── Generate 12 Chargebacks ─────────────────────────────────────────────────────

CHARGEBACK_SCENARIOS = [
    # (reason_code, reason_desc, required_fulfillment, required_avs, required_signed)
    # 13.1 x3 — Merchandise Not Received
    ("13.1", "Merchandise Not Received", "Delivered", "Pass", "Yes"),     # AI: signed delivery
    ("13.1", "Merchandise Not Received", "Delivered", "Pass", "Yes"),     # AI: signed delivery
    ("13.1", "Merchandise Not Received", "Shipped", "Pass", ""),          # Human: in transit
    # 10.4 x2 — Fraud CNP
    ("10.4", "Fraud - Card Not Present", "Delivered", "Pass", "Yes"),     # AI: AVS pass + repeat buyer
    ("10.4", "Fraud - Card Not Present", "Delivered", "Fail", "No"),      # Human: AVS fail
    # 13.3 x2 — Not as Described
    ("13.3", "Not as Described / Defective", "Delivered", "Pass", "Yes"), # Human: always human
    ("13.3", "Not as Described / Defective", "Delivered", "Pass", "No"),  # Human: always human
    # 13.6 x1 — Credit Not Processed
    ("13.6", "Credit Not Processed", "Delivered", "Pass", "Yes"),         # Human: needs refund verification
    # 13.7 x1 — Cancelled Merchandise
    ("13.7", "Cancelled Merchandise/Services", "Delivered", "Pass", "Yes"), # AI: delivered + signed
    # 12.5 x1 — Incorrect Amount
    ("12.5", "Incorrect Amount", "Delivered", "Pass", "No"),              # AI: AVS pass + repeat buyer (will need repeat cust)
    # 11.3 x1 — No Authorization
    ("11.3", "No Authorization", "Processing", "Fail", ""),               # Human: not shipped + AVS fail
    # 13.2 x1 — Cancelled Recurring
    ("13.2", "Cancelled Recurring Transaction", "Delivered", "Pass", "Yes"), # AI: delivered + signed
]


def generate_chargebacks(orders):
    # Find orders matching each scenario's requirements
    chargebacks = []
    used_indices = set()

    # Pre-compute per-customer order counts for repeat buyer identification
    from collections import Counter
    cust_counts = Counter(o["customer_id"] for o in orders)

    for idx, (rc, desc, req_ff, req_avs, req_signed) in enumerate(CHARGEBACK_SCENARIOS):
        # Find a matching order
        candidates = []
        for i, o in enumerate(orders):
            if i in used_indices:
                continue
            if o["payment_status"] != "Completed":
                continue
            if o["fulfillment_status"] != req_ff:
                continue
            if o["avs_cvv_match"] != req_avs:
                continue
            if req_signed and o["delivery_signed"] != req_signed:
                continue
            # For AI triage rules that need repeat buyers (10.4 with Pass, 12.5 with Pass)
            if rc in ("10.4", "12.5") and req_avs == "Pass":
                if cust_counts[o["customer_id"]] < 5:
                    continue
            candidates.append(i)

        if not candidates:
            # Relax constraints — just match fulfillment
            for i, o in enumerate(orders):
                if i in used_indices and o["payment_status"] == "Completed":
                    continue
                if o["fulfillment_status"] == req_ff:
                    candidates.append(i)
            if not candidates:
                candidates = [i for i in range(len(orders)) if i not in used_indices]

        chosen_idx = random.choice(candidates[:20])  # pick from top matches
        used_indices.add(chosen_idx)
        order = orders[chosen_idx]

        tx_date = datetime.strptime(order["order_date"], "%Y-%m-%d")
        tx_date = tx_date.replace(hour=random.randint(8, 22), minute=random.randint(0, 59))
        dispute_date = tx_date + timedelta(days=random.randint(7, 30))

        arn = f"7492683027100250{tx_date.strftime('%m%d')}{idx + 1:03d}"
        processor = random.choice(PROCESSORS)

        chargebacks.append({
            "dispute_ref": f"DSP-20260710-{idx + 1:03d}",
            "payment_ref": f"PAY-{order['order_date'].replace('-', '')}-{order['card_last_four']}",
            "order_id": order["order_id"],
            "reason_code": rc,
            "reason_description": desc,
            "card_scheme": order["payment_method"],
            "card_last_four": order["card_last_four"],
            "disputed_amount": order["order_amount"],
            "transaction_date": tx_date.strftime("%Y-%m-%d %H:%M:%S"),
            "dispute_date": dispute_date.strftime("%Y-%m-%d %H:%M:%S"),
            "arn": arn,
            "processor": processor,
        })

    return chargebacks


# ── Write CSVs ──────────────────────────────────────────────────────────────────

ORDER_COLUMNS = [
    "order_id", "customer_id", "order_date", "product_name", "product_category",
    "product_id", "quantity", "unit_price", "order_amount", "payment_method",
    "card_last_four", "payment_status", "fulfillment_status", "shipping_carrier",
    "tracking_number", "delivery_date", "delivery_signed", "customer_email",
    "customer_city", "customer_state", "return_policy_days", "avs_cvv_match",
    "customer_ip",
]

CB_COLUMNS = [
    "dispute_ref", "payment_ref", "order_id", "reason_code", "reason_description",
    "card_scheme", "card_last_four", "disputed_amount", "transaction_date",
    "dispute_date", "arn", "processor",
]


def main():
    import os
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

    orders = generate_orders(1000)
    chargebacks = generate_chargebacks(orders)

    orders_path = os.path.join(static_dir, "orders_1000.csv")
    with open(orders_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ORDER_COLUMNS)
        writer.writeheader()
        writer.writerows(orders)

    cb_path = os.path.join(static_dir, "chargebacks_12.csv")
    with open(cb_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CB_COLUMNS)
        writer.writeheader()
        writer.writerows(chargebacks)

    print(f"Generated {len(orders)} orders -> {orders_path}")
    print(f"Generated {len(chargebacks)} chargebacks -> {cb_path}")

    # Quick summary
    from collections import Counter
    ff_counts = Counter(o["fulfillment_status"] for o in orders)
    pay_counts = Counter(o["payment_status"] for o in orders)
    print(f"\nFulfillment: {dict(ff_counts)}")
    print(f"Payment: {dict(pay_counts)}")
    print(f"\nChargeback reason codes:")
    for cb in chargebacks:
        print(f"  {cb['dispute_ref']} | {cb['reason_code']} {cb['reason_description'][:30]} | {cb['order_id']} | ${cb['disputed_amount']}")


if __name__ == "__main__":
    main()
