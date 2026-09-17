import os
import csv as _csv


class ChargebackCaseLoader:
    """Loads raw chargeback dispute data from CSV files.
    Parses orders and chargebacks, links them by order_id."""

    @classmethod
    def load_orders(cls, csv_path=None):
        """Load the orders CSV into a list of dicts."""
        if csv_path is None:
            static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")
            csv_path = os.path.join(static_dir, "orders_1000.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            return list(_csv.DictReader(f))

    @classmethod
    def load_chargebacks(cls, csv_path=None):
        """Load the chargebacks CSV into a list of dicts."""
        if csv_path is None:
            static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")
            csv_path = os.path.join(static_dir, "chargebacks_12.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            return list(_csv.DictReader(f))

    @classmethod
    def load(cls):
        """Load and link orders + chargebacks."""
        orders = cls.load_orders()
        chargebacks = cls.load_chargebacks()
        orders_by_id = {o["order_id"]: o for o in orders}
        return orders, chargebacks, orders_by_id
