import sys
import unittest
from pathlib import Path

# Make the collector module importable from the repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "collector"))

from collector import extract_object_and_pattern


class TestExtractObjectAndPattern(unittest.TestCase):

    def test_insert_select_identifies_insert_target(self):
        query = """
            INSERT INTO orders (customer_id)
            SELECT customer_id
            FROM generate_series(1, 5) AS s(customer_id);
        """

        obj, pattern, query_type = extract_object_and_pattern(query)

        self.assertEqual(obj, "orders")
        self.assertEqual(query_type, "INSERT")

    def test_update_identifies_target_table(self):
        query = "UPDATE products SET price = 100 WHERE id = 1"

        obj, pattern, query_type = extract_object_and_pattern(query)

        self.assertEqual(obj, "products")
        self.assertEqual(query_type, "UPDATE")

    def test_delete_identifies_target_table(self):
        query = "DELETE FROM orders WHERE id = 5"

        obj, pattern, query_type = extract_object_and_pattern(query)

        self.assertEqual(obj, "orders")
        self.assertEqual(query_type, "DELETE")

    def test_select_identifies_source_table(self):
        query = "SELECT * FROM customers WHERE id = 10"

        obj, pattern, query_type = extract_object_and_pattern(query)

        self.assertEqual(obj, "customers")
        self.assertEqual(query_type, "SELECT")

    def test_join_is_recognized(self):
        query = """
            SELECT *
            FROM customers c
            JOIN orders o ON c.id = o.customer_id
        """

        obj, pattern, query_type = extract_object_and_pattern(query)

        self.assertEqual(obj, "customers")
        self.assertEqual(pattern, "join")
        self.assertEqual(query_type, "SELECT")


if __name__ == "__main__":
    unittest.main()
