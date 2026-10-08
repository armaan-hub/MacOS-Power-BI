import unittest
from datetime import date, timedelta
from analytics_studio.measures import evaluate_measures

class CalculateAdvancedCombinationsTests(unittest.TestCase):
    def test_combined_boolean_and_dateadd_filters(self):
        calendar_start = date(2023, 1, 1)
        calendar_end = date(2024, 12, 31)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        
        # Currently selected: March 2024
        selected_dates = [
            row for row in calendar_rows
            if "2024-03-01" <= row["Date"] <= "2024-03-31"
        ]
        
        order_rows = [
            {"OrderDate": "2023-03-05", "Amount": "100", "Region": "East", "Status": "Shipped"},
            {"OrderDate": "2023-03-10", "Amount": "200", "Region": "East", "Status": "Pending"},
            {"OrderDate": "2023-03-15", "Amount": "300", "Region": "West", "Status": "Shipped"},
            {"OrderDate": "2024-03-05", "Amount": "1000", "Region": "East", "Status": "Shipped"},
        ]
        
        values = evaluate_measures(
            [{
                "name": "Prior year East shipped sales",
                "expression": (
                    "CALCULATE(SUM([Amount]), "
                    "DATEADD('Calendar'[Date], -1, YEAR), "
                    "[Region] = \"East\", "
                    "'Orders'[Status] = \"Shipped\")"
                ),
            }],
            order_rows,
            ["OrderDate", "Amount", "Region", "Status"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_dates,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region", "Status"],
                    "rows": order_rows,
                    "filter_rows": order_rows,
                    "filter_context_complete": True,
                    "filter_column_rows": {},
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[
                {
                    "relationship_version": 1,
                    "from_table_id": "orders-id",
                    "from_column": "OrderDate",
                    "to_table_id": "calendar-id",
                    "to_column": "Date",
                    "cardinality": "many_to_one",
                    "is_active": True,
                    "cross_filter_direction": "single",
                }
            ],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )
        
        # In March 2023 (prior year from March 2024):
        # East + Shipped: row with 100
        from decimal import Decimal
        print('CALENDAR FILTER ROWS:', [r['Date'] for r in values.get('__debug_calendar_rows', [])])
        print('ORDERS FILTER ROWS:', [r['OrderDate'] for r in values.get('__debug_orders_rows', [])])
        self.assertEqual(values["Prior year East shipped sales"], Decimal("100"))

if __name__ == "__main__":
    unittest.main()
