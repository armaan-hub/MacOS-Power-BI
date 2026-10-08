from datetime import date, timedelta
import unittest
from decimal import Decimal

from analytics_studio.measures import (
    evaluate_measures,
    _nextmonth_dates,
    _nextyear_dates,
    _parallelperiod_dates,
    _nextday_dates,
    _previousday_dates,
    _nextquarter_dates
)

class ExtendedTimeFilterTests(unittest.TestCase):
    def _relationship(self):
        return {
            "relationship_version": 1,
            "id": "calendar-orders",
            "from": "Calendar[Date]",
            "to": "Orders[OrderDate]",
            "from_table_id": "calendar-id",
            "from_column": "Date",
            "to_table_id": "orders-id",
            "to_column": "OrderDate",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }

    def test_extended_time_filters(self):
        calendar_rows = [
            {"Date": (date(2023, 1, 1) + timedelta(days=offset)).isoformat()}
            for offset in range(365 * 3) # Up to 2025
        ]
        
        order_rows = [
            {"OrderDate": "2023-05-15", "Amount": "10"}, # Previous year
            {"OrderDate": "2024-04-15", "Amount": "100"}, # Previous month
            {"OrderDate": "2024-05-14", "Amount": "5"},  # Previous day
            {"OrderDate": "2024-05-15", "Amount": "50"}, # Base
            {"OrderDate": "2024-05-16", "Amount": "10"}, # Next day
            {"OrderDate": "2024-06-15", "Amount": "200"}, # Next month
            {"OrderDate": "2024-08-15", "Amount": "300"}, # Next quarter
            {"OrderDate": "2025-05-15", "Amount": "400"}, # Next year
        ]
        
        # Base filter: just one day "2024-05-15"
        base_rows = [row for row in calendar_rows if row["Date"] == "2024-05-15"]
        
        table_context = [
            {
                "id": "calendar-id",
                "name": "Calendar",
                "headers": ["Date"],
                "rows": calendar_rows,
                "filter_rows": base_rows,
                "column_types": {"Date": "date"},
                "date_column": "Date",
            },
            {
                "id": "orders-id",
                "name": "Orders",
                "headers": ["OrderDate", "Amount"],
                "rows": order_rows,
                "filter_rows": order_rows,
                "column_types": {"OrderDate": "date", "Amount": "whole_number"},
            },
        ]
        
        expressions = [
            {"name": "Current", "expression": "SUM('Orders'[Amount])"},
            {"name": "Previous Day", "expression": "CALCULATE(SUM('Orders'[Amount]), PREVIOUSDAY('Calendar'[Date]))"},
            {"name": "Next Day", "expression": "CALCULATE(SUM('Orders'[Amount]), NEXTDAY('Calendar'[Date]))"},
            {"name": "Next Month", "expression": "CALCULATE(SUM('Orders'[Amount]), NEXTMONTH('Calendar'[Date]))"},
            {"name": "Next Quarter", "expression": "CALCULATE(SUM('Orders'[Amount]), NEXTQUARTER('Calendar'[Date]))"},
            {"name": "Next Year", "expression": "CALCULATE(SUM('Orders'[Amount]), NEXTYEAR('Calendar'[Date]))"},
            {"name": "Parallel Year +1", "expression": "CALCULATE(SUM('Orders'[Amount]), PARALLELPERIOD('Calendar'[Date], 1, YEAR))"},
        ]
        
        values = evaluate_measures(
            expressions,
            order_rows,
            ["OrderDate", "Amount"],
            "Orders",
            table_context=table_context,
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )
        
        self.assertEqual(values.get("Current"), Decimal("50"))
        self.assertEqual(values.get("Previous Day"), Decimal("5"))
        self.assertEqual(values.get("Next Day"), Decimal("10"))
        
        # Next Month: all of June 2024. Only have 2024-06-15 = 200
        self.assertEqual(values.get("Next Month"), Decimal("200"))
        
        # Next Quarter: all of Q3 2024 (July-Sep). Only have 2024-08-15 = 300
        self.assertEqual(values.get("Next Quarter"), Decimal("300"))
        
        # Next Year: all of 2025. Only have 2025-05-15 = 400
        self.assertEqual(values.get("Next Year"), Decimal("400"))
        
        # Parallel Period +1 Year: shifts to 2025-05-15, then returns full 2025 year. Same as Next Year here.
        self.assertEqual(values.get("Parallel Year +1"), Decimal("400"))

if __name__ == "__main__":
    unittest.main()
