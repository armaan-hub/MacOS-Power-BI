"""Iteration 136: Task 46 big-rounding-36.

Whole powers beyond 2^53 are square-and-multiply in IEEE doubles (measured on saved Power BI answers), and INT, CEILING, FLOOR,
MROUND and QUOTIENT read such a double as the engine reads any double beyond 2^53. The expected texts are Power BI answers.
"""
import unittest

from tools import dax_oracle_diff as dax


class BigRoundingPowerTests(unittest.TestCase):
    def assert_power_bi(self, expression: str, expected: str) -> None:
        self.assertTrue(dax.same(expected, dax.local(expression)), f"{expression}: local {dax.local(expression)} Power BI {expected}")

    def test_int_of_power_squared_in_doubles(self) -> None:
        self.assert_power_bi('INT(1.5^100)&"z"', "406561177535215296z")
        self.assert_power_bi('INT(13^17)&"z"', "8650415919381339136z")
        self.assert_power_bi('INT(2.5^45)&"z"', "807793566946316160z")

    def test_int_of_power_plus_one(self) -> None:
        self.assert_power_bi('INT(3^34+1)&"z"', "16677181699666568z")
        self.assert_power_bi('INT(POWER(1.5,100)+1)&"z"', "406561177535215296z")

    def test_ceiling_and_floor_of_power(self) -> None:
        self.assert_power_bi('CEILING(POWER(3,35),2048)&"z"', "50031545098999808z")
        self.assert_power_bi('FLOOR(7^19+1,8)&"z"', "11398895185373120z")

    def test_mround_of_product_of_power(self) -> None:
        self.assert_power_bi('MROUND(POWER(1.5,98)*3,3)&"z"', "542081570046953600z")

    def test_product_with_a_power_is_one_double(self) -> None:
        # measured on live Power BI: the product is a double multiplication, not a Decimal one of the power's shortest digits
        self.assert_power_bi('3^67*3&"z"', "2.78128389443694E+32z")
        self.assert_power_bi('1.1^67*1.1&"z"', "652.683435371441z")
        self.assert_power_bi('2^109*13&"z"', "8.43748239511909E+33z")
        self.assert_power_bi('5*9^75&"z"', "1.84994242517563E+72z")
        self.assert_power_bi('7^31*7*7&"z"', "7.73099371970745E+27z")


if __name__ == "__main__":
    unittest.main()
