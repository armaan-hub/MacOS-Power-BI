"""Power BI-verified answers for the financial functions in ``analytics_studio/dax_finance.py``.

Every expected value below is the answer Power BI Desktop 2.157.879.0 gave (``tools/parity/dax_battery_finance.json``
holds the saved battery; this file keeps representative cases per function, taken from that battery and from the probe
runs that fed it).  ``ERR`` means Power BI rejects the call at parse time (wrong argument count); a string is the exact
message Power BI raised at run time; ``BLANK`` is the BLANK result.
"""

from __future__ import annotations

from decimal import Decimal
import unittest

from analytics_studio import dax_ext, dax_finance
from analytics_studio.measures import MeasureError, evaluate_measures

ERR = "ERR"
BLANK = None

FUNCTIONS = (
    "PMT", "PV", "FV", "NPER", "RATE", "IPMT", "PPMT", "CUMIPMT", "CUMPRINC", "ISPMT", "SLN", "SYD", "DB", "DDB", "VDB",
    "EFFECT", "NOMINAL", "RRI", "PDURATION", "DOLLARDE", "DOLLARFR",
)

ARITIES = {
    "PMT": (3, 5), "PV": (3, 5), "FV": (3, 5), "NPER": (3, 5), "RATE": (3, 6), "IPMT": (4, 6), "PPMT": (4, 6),
    "CUMIPMT": (6, 6), "CUMPRINC": (6, 6), "ISPMT": (4, 4), "SLN": (3, 3), "SYD": (4, 4), "DB": (4, 5), "DDB": (4, 5),
    "VDB": (5, 7), "EFFECT": (2, 2), "NOMINAL": (2, 2), "RRI": (3, 3), "PDURATION": (3, 3), "DOLLARDE": (2, 2),
    "DOLLARFR": (2, 2),
}

CASES = [
    # PMT
    ('PMT(0.0000001, 10, -1000)', '100.000055000008'),
    ('PMT(0.1177, 60, 28205.72, 49245.8, 0)', '-3331.31698387205'),
    ('PMT(0.05, 100000, -1000)', '50'),
    ('PMT(0.1652, 1, -44937.31, 0, 1)', '44937.31'),
    ('PMT(0.0816, 10, -25885.26, 0, 0)', '3885.55278656375'),
    ('PMT(1E-12, 10, 1000)', '-100.00000000055'),
    ('PMT(0.0278, 15, 48279.05, 0, 0)', '-3980.09051772027'),
    ('PMT(0.1, 1, 100, 100, 1)', '-190.909090909091'),
    ('PMT(0.05, 0, BLANK())', "An argument of function 'PMT' has the wrong data type or the result is too large or too small."),
    ('PMT(0.05, 0, -1000)', "An argument of function 'PMT' has the wrong data type or the result is too large or too small."),
    ('PMT(-1, 10, -1000)', "An argument of function 'PMT' has the wrong data type or the result is too large or too small."),
    ('PMT(0.05, 10, -1000, "")', "Cannot convert value '' of type Text to type Number."),
    ('PMT(0.05, 10, "abc")', "Cannot convert value 'abc' of type Text to type Number."),
    ('PMT(0.05, 10, -1000, 0, 1E19)', 'The result of a conversion or arithmetic operation is either too large or too small.'),
    ('PMT(0.05, 10, BLANK(), BLANK())', BLANK),
    ('PMT(BLANK(), 10, BLANK())', BLANK),
    ('PMT(BLANK(), 10, -1000)', '100'),
    ('PMT(0.05, 10, -1000, BLANK())', '129.504574965457'),
    ('PMT("0.05", "10", "-1000")', '129.504574965457'),
    ('PMT(0.05, 10, -1000, 0, "1")', '123.337690443292'),
    ('PMT(0.05, 10, -1000, 0, TRUE())', '123.337690443292'),
    ('PMT(TRUE(), 10, -1000)', '1000.97751710655'),
    ('PMT(1,2,3,4,5,6)', ERR),
    # PV
    ('PV(0.0915, 24, 47150.62, -32252.6, 1)', '-489724.209698433'),
    ('PV(0.05, 10, -1000, 0, 2)', '8107.82167564405'),
    ('PV(-2, 10, -1000)', '0'),
    ('PV(0.1365, 36, -20284.77, 0, 1)', '167204.17488941'),
    ('PV(1E-10, 7, -1)', '7.0000005742826'),
    ('PV(0.1734, 36, -18295.81, 0, 0)', '105178.554964206'),
    ('PV(1E-8, 360, -1000)', '359999.346407639'),
    ('PV(0.000001, 123456, -1)', '116139.415182706'),
    ('PV(-1, 0, -1000)', "An argument of function 'PV' has the wrong data type or the result is too large or too small."),
    ('PV(0.05, 100000, -1000)', "An argument of function 'PV' has the wrong data type or the result is too large or too small."),
    ('PV(-1, 10, -1000)', "Division by zero has occurred when evaluating function 'PV'."),
    ('PV(-1, 1, BLANK())', "Division by zero has occurred when evaluating function 'PV'."),
    ('PV(0.05, 10, -1000, 0, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('PV(0.05, 10, "abc")', "Cannot convert value 'abc' of type Text to type Number."),
    ('PV(0.05, 10, BLANK())', BLANK),
    ('PV(0.05, 0, BLANK())', BLANK),
    ('PV(0.05, BLANK(), -1000)', '0'),
    ('PV(BLANK(), 10, -1000)', '10000'),
    ('PV(0.05, 10, -1000, "500")', '7414.77830241443'),
    ('PV("0.05", "10", "-1000")', '7721.73492918481'),
    ('PV(0.05, 10, TRUE())', '-7.72173492918481'),
    ('PV(0.05, 10, -1000, 0, TRUE())', '8107.82167564405'),
    ('PV(1,2)', ERR),
    # FV
    ('FV(-1.01, 2, -1000)', '990'),
    ('FV(0.05, 10, -1000, 500, 0)', '11763.4452221601'),
    ('FV(0.05, 10, -1000, 0, 1.5)', '13206.7871623263'),
    ('FV(1E-8, 360.5, -1000)', '360500.645801842'),
    ('FV(0, 10, -1000, 500, 1)', '9500'),
    ('FV(1E-9, 100, 5000, -100, 1)', '-499900.062954423'),
    ('FV(1E-12, 2147483648, -1)', '2149982444.51459'),
    ('FV(0.05, 0, -1000)', '0'),
    ('FV(0.05, 1E10, -1000)', "An argument of function 'FV' has the wrong data type or the result is too large or too small."),
    ('FV(-1, 0, -1000)', "An argument of function 'FV' has the wrong data type or the result is too large or too small."),
    ('FV(0.05, 100000, -1000)', "An argument of function 'FV' has the wrong data type or the result is too large or too small."),
    ('FV(-1, -1, -1000)', "Division by zero has occurred when evaluating function 'FV'."),
    ('FV(-1, -2, -1000)', "Division by zero has occurred when evaluating function 'FV'."),
    ('FV(0.05, 10, "abc")', "Cannot convert value 'abc' of type Text to type Number."),
    ('FV(0.05, 10, -1000, 0, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('FV(-1, 1, BLANK())', BLANK),
    ('FV(BLANK(), BLANK(), BLANK())', BLANK),
    ('FV(0.05, 10, BLANK(), 500)', '-814.447313388721'),
    ('FV(BLANK(), 10, -1000)', '10000'),
    ('FV(0.05, 10, -1000, 0, "1")', '13206.7871623263'),
    ('FV("0.05", "10", "-1000")', '12577.8925355488'),
    ('FV(0.05, 10, TRUE())', '-12.5778925355488'),
    ('FV(0.05, 10, -1000, 0, TRUE())', '13206.7871623263'),
    ('FV(1,2)', ERR),
    # NPER
    ('NPER(0.05, -100, 1000, 2000)', '28.4133981657809'),
    ('NPER(0.05, -100, 1000, 1000)', '22.517085305411'),
    ('NPER(0.05, -100, 1999)', '155.787597540085'),
    ('NPER(1E-15, -100, 1000)', '8.99999999999996'),
    ('NPER(0.05, -50.0001, 1000)', '268.955138822643'),
    ('NPER(0.05, -100, 1000, -1000)', '0'),
    ('NPER(0.05, -100, 1000, 500, 1)', '17.6306286290802'),
    ('NPER(0, -100, 1000, 500, 1)', '15'),
    ('NPER(0.1586, -78.68, 249531.9, -322.53, 1)', "An argument of function 'NPER' has the wrong data type or the result is too large or too small."),
    ('NPER(TRUE(), -100, 1000)', "An argument of function 'NPER' has the wrong data type or the result is too large or too small."),
    ('NPER(-1.5, -100, 1000)', "An argument of function 'NPER' has the wrong data type or the result is too large or too small."),
    ('NPER(1E-300, -100, 1000)', "Division by zero has occurred when evaluating function 'NPER'."),
    ('NPER(0, 0, 1000)', "Division by zero has occurred when evaluating function 'NPER'."),
    ('NPER(0.05, -100, 1000, 0, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('NPER(0.05, -100, "abc")', "Cannot convert value 'abc' of type Text to type Number."),
    ('NPER(0.05, -100, BLANK())', BLANK),
    ('NPER(0.05, -100, BLANK(), BLANK())', BLANK),
    ('NPER(BLANK(), -100, 1000)', '10'),
    ('NPER(0.05, -100, 1000, BLANK())', '14.2066990828905'),
    ('NPER("0.05", "-100", "1000")', '14.2066990828905'),
    ('NPER(0.05, -100, 1000, 0, "1")', '13.2532278981381'),
    ('NPER(0.05, -100, 1000, 0, TRUE())', '13.2532278981381'),
    ('NPER(1,2)', ERR),
    # RATE
    ('RATE(10, -100, 800, 0, 0, 0.0428)', '0.042774978035111'),
    ('RATE(1, 100, -100)', '-7.50733680629903E-09'),
    ('RATE(2, -1, 1E12)', '-0.9999989999995'),
    ('RATE(3, 10, -30, 0)', '-4.04265581552065E-09'),
    ('RATE(2, 0, -100, 121)', '0.1'),
    ('RATE(2, 1, -1, 0)', '0.618033988749895'),
    ('RATE(10, -100, 800, 0, 0, 0.04277)', '0.0427749780351111'),
    ('RATE(25, -563.59, 151433.1, 128.8, 1)', '-0.143286612926802'),
    ('RATE(2, -1, 1.1E14)', "An argument of function 'RATE' has the wrong data type or the result is too large or too small."),
    ('RATE(30, 100, -1)', "An argument of function 'RATE' has the wrong data type or the result is too large or too small."),
    ('RATE(0, -100, 800)', "An argument of function 'RATE' has the wrong data type or the result is too large or too small."),
    ('RATE(10, -100, "abc")', "Cannot convert value 'abc' of type Text to type Number."),
    ('RATE(10, -100, 800, 0, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('RATE(10, BLANK(), 100, -200)', '0.0717734625363799'),
    ('RATE(10, -100, 800, 0, 0, BLANK())', '0.0427749780346815'),
    ('RATE(10, -100, 800, 0, 0, "0.1")', '0.042774978035587'),
    ('RATE("10", "-100", "800")', '0.042774978035587'),
    ('RATE(10, -100, 800, 0, 0, TRUE())', '0.0427749780351117'),
    ('RATE(TRUE(), 0, -100, 110)', '0.1'),
    ('RATE(1,2)', ERR),
    ('RATE(10, -100, 800, 0, 0, -1)', "An argument of function 'RATE' has the wrong data type or has an invalid value."),
    # IPMT
    ('IPMT(0, 5, 10, -1000, 500, 1)', '0'),
    ('IPMT(0.233, 151, 360, 26443.4, 0, 0)', '-6161.3122'),
    ('IPMT(0.05, 5, 5, -1000)', '10.9987999108699'),
    ('IPMT(1E-10, 5, 10, -1000)', '6.0000000012E-08'),
    ('IPMT(0.1992, 3, 15, -47333.75, 0, 1)', '7620.98912094873'),
    ('IPMT(0.1953, 9, 15.5, -11346.97, 24329.07, 1)', '2305.37931124197'),
    ('IPMT(0.1586, 2, 6, -48552.44, 29377.85, 1)', '6352.90136257269'),
    ('IPMT(-0.5, 3, 10.5, -1000, 500, 0)', '-312.370435412626'),
    ('IPMT(0.05, -1, 10, -1000)', "An argument of function 'IPMT' has the wrong data type or the result is too large or too small."),
    ('IPMT(0, 0, 10, -1000)', "An argument of function 'IPMT' has the wrong data type or the result is too large or too small."),
    ('IPMT(0.05, 0, 10, -1000)', "An argument of function 'IPMT' has the wrong data type or the result is too large or too small."),
    ('IPMT(0.05, 1, 10, -1000, 0, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('IPMT(0.05, 1, 10, "abc")', "Cannot convert value 'abc' of type Text to type Number."),
    ('IPMT(0.05, 1, 10, BLANK())', BLANK),
    ('IPMT(0.05, 1, 10, BLANK(), BLANK())', BLANK),
    ('IPMT(0.05, 1, 10, -1000, 0, BLANK())', '50'),
    ('IPMT(0.05, 2, 10, BLANK(), 0, 1)', '0'),
    ('IPMT("0.05", "1", "10", "-1000")', '50'),
    ('IPMT(0.05, TRUE(), 10, -1000)', '50'),
    ('IPMT(TRUE(), 1, 10, -1000)', '1000'),
    ('IPMT(1,2,3)', ERR),
    # PPMT
    ('PPMT(1E-15, 5, 10, -1000)', '100'),
    ('PPMT(0.05, 10.5, 10, -1000, 500, 1)', '60.1826305504562'),
    ('PPMT(0.0915, 9, 24, -35940.61, -32252.6, 1)', '1604.77103122283'),
    ('PPMT(0.1586, 2, 6, -48552.44, 29377.85, 1)', '2143.41403104215'),
    ('PPMT(0.005, 100, 360, -200000, 0, 1)', '324.599318121221'),
    ('PPMT(0.05, 10.999999999, 10, -1000)', '129.504574959138'),
    ('PPMT(0.05, 5, 5, -1000, 100)', '197.978398395658'),
    ('PPMT(0.0104, 12, 24, -27505.59, -46764.78, 1)', '3039.14278136109'),
    ('PPMT(0.05, 0.5, 10, -1000)', "An argument of function 'PPMT' has the wrong data type or the result is too large or too small."),
    ('PPMT(0.05, -1, 10, -1000)', "An argument of function 'PPMT' has the wrong data type or the result is too large or too small."),
    ('PPMT(0.05, 0, 10, -1000)', "An argument of function 'PPMT' has the wrong data type or the result is too large or too small."),
    ('PPMT(0.05, 1, 10, -1000, 0, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('PPMT(0.05, 1, 10, "abc")', "Cannot convert value 'abc' of type Text to type Number."),
    ('PPMT(0.05, 1, 10, BLANK())', BLANK),
    ('PPMT(0.05, 1, 10, BLANK(), BLANK())', BLANK),
    ('PPMT(BLANK(), 1, 10, -1000)', '100'),
    ('PPMT(0.05, 1, 10, -1000, BLANK())', '79.5045749654567'),
    ('PPMT("0.05", "1", "10", "-1000")', '79.5045749654567'),
    ('PPMT(0.05, TRUE(), 10, -1000)', '79.5045749654567'),
    ('PPMT(TRUE(), 1, 10, -1000)', '0.977517106549365'),
    ('PPMT(1,2,3)', ERR),
    # CUMIPMT
    ('CUMIPMT(0.05, 10, 1000, 1, 5.5, 0)', '-236.244262682834'),
    ('CUMIPMT(0.05, 10, 1000, 1, 10, 0.5)', '-233.376904432921'),
    ('CUMIPMT(0.05, 10, 1000, 1.9, 5.9, 0)', '-186.244262682833'),
    ('CUMIPMT(0.05, 10, 1000, 0.99999, 3, 0)', '-137.875552317768'),
    ('CUMIPMT(10, 10, 1000, 1, 10, 0)', '-99000.0000038554'),
    ('CUMIPMT(100, 10, 1000, 1, 10, 1)', '-8900.9900990099'),
    ('CUMIPMT(0.005, 360, 200000, 13, 24, 1)', '-11723.0915705455'),
    ('CUMIPMT(0.233, 360, 26443.4, 206, 331, 0)', '-776264.469334373'),
    ('CUMIPMT(0.05, 10.5, 1000, 1, 10.5, 0)', "An argument of function 'CUMIPMT' has the wrong data type or the result is too large or too small."),
    ('CUMIPMT(0.05, 5.5, 1000, 6, 6, 0)', "An argument of function 'CUMIPMT' has the wrong data type or the result is too large or too small."),
    ('CUMIPMT(0.05, 0, 1000, 1, 10, 0)', "An argument of function 'CUMIPMT' has the wrong data type or the result is too large or too small."),
    ('CUMIPMT(0.05, 10, 1000, 1, 10, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('CUMIPMT(0.05, 10, "abc", 1, 10, 0)', "Cannot convert value 'abc' of type Text to type Number."),
    ('CUMIPMT(0.05, 10, 1000, 1, 10, 9223372036854775808)', 'The result of a conversion or arithmetic operation is either too large or too small.'),
    ('CUMIPMT(0.05, 10, 1000, 1, 10, BLANK())', '-295.045749654567'),
    ('CUMIPMT(0.05, 10, 1000, 1, 10, "1")', '-233.376904432921'),
    ('CUMIPMT("0.05", "10", "1000", "1", "10", "0")', '-295.045749654567'),
    ('CUMIPMT(0.05, 10, 1000, 1, 10, TRUE())', '-233.376904432921'),
    ('CUMIPMT(TRUE(), 10, 1000, 1, 10, 0)', '-9009.77517106549'),
    ('CUMIPMT(1,2,3,4,5)', ERR),
    # CUMPRINC
    ('CUMPRINC(0.1586, 6, 48552.44, 3, 6, 1)', '-31794.2996677665'),
    ('CUMPRINC(0.05, 10, 1000, 1, 10, 0.5)', '-1000'),
    ('CUMPRINC(0.05, 10.9, 1000, 1, 10, 0)', '-895.842266687652'),
    ('CUMPRINC(1E-300, 10, 1000, 2, 5, 1)', '-400'),
    ('CUMPRINC(0.05, 5.5, 1000, 1, 5, 1)', '-902.47863808338'),
    ('CUMPRINC(0.1734, 36, 6605.15, 34, 36, 0)', '-2524.81730947551'),
    ('CUMPRINC(0.05, 10, 1000, 1, 1.0001, 1)', '-123.337690443292'),
    ('CUMPRINC(1E-10, 10, 1000, 1, 10, 0)', '-1000'),
    ('CUMPRINC(0.05, 5, 1000, 5.0000001, 5.5, 0)', "An argument of function 'CUMPRINC' has the wrong data type or the result is too large or too small."),
    ('CUMPRINC(0.05, 10, 1000, 1, 10, -0.5)', "An argument of function 'CUMPRINC' has the wrong data type or the result is too large or too small."),
    ('CUMPRINC(0.05, 10, 1000, 0, 5, 0)', "An argument of function 'CUMPRINC' has the wrong data type or the result is too large or too small."),
    ('CUMPRINC(0.05, 10, 1000, "a", 3, 0)', "Cannot convert value 'a' of type Text to type Integer."),
    ('CUMPRINC(0.05, 10, "abc", 1, 10, 0)', "Cannot convert value 'abc' of type Text to type Number."),
    ('CUMPRINC(0.05, 10, 1000, 1, 10, BLANK())', '-1000'),
    ('CUMPRINC(0.05, 10, 1000, 1, 10, "1")', '-1000'),
    ('CUMPRINC("0.05", "10", "1000", "1", "10", "0")', '-1000'),
    ('CUMPRINC(TRUE(), 10, 1000, 1, 10, 0)', '-1000'),
    ('CUMPRINC(0.05, 10, 1000, 1, 10, TRUE())', '-1000'),
    ('CUMPRINC(1,2,3,4,5,6,7)', ERR),
    # ISPMT
    ('ISPMT(0.05, 5, 10, -1000)', '25'),
    ('ISPMT(0.1734, 19, 36, 6605.15)', '-540.851699166667'),
    ('ISPMT(0.05, 7, 3, 1000)', '66.6666666666667'),
    ('ISPMT(0.05, 0.1, 10, 1000)', '-49.5'),
    ('ISPMT(0.05, 5, 1E10, 1000)', '-49.999999975'),
    ('ISPMT(0.05, 5, 1E-10, 1000)', '2499999999950'),
    ('ISPMT(0.05, 5, 3, 1000.5)', '33.35'),
    ('ISPMT(0.0439, 20, 48, -47523.97)', '1217.00966508333'),
    ('ISPMT(0.05, 5, BLANK(), 0)', "Division by zero has occurred when evaluating function 'ISPMT'."),
    ('ISPMT(0.05, 0, 0, 1000)', "Division by zero has occurred when evaluating function 'ISPMT'."),
    ('ISPMT(0.05, 5, 10, "abc")', "Cannot convert value 'abc' of type Text to type Number."),
    ('ISPMT(0.05, 5, 10, BLANK())', BLANK),
    ('ISPMT(BLANK(), 5, 10, 1000)', '0'),
    ('ISPMT(0.05, BLANK(), 10, 1000)', '-50'),
    ('ISPMT("0.05", "5", "10", "1000")', '-25'),
    ('ISPMT(TRUE(), 5, 10, 1000)', '-500'),
    ('ISPMT(0.05, TRUE(), 10, 1000)', '-45'),
    ('ISPMT(1,2,3)', ERR),
    # SLN
    ('SLN(65618.4, 21817.41, 4)', '10950.2475'),
    ('SLN(40504.6, 12979.34, 20)', '1376.263'),
    ('SLN(10000, 1000, -5)', '-1800'),
    ('SLN(10000, -1000, 5)', '2200'),
    ('SLN(0, 0, 5)', '0'),
    ('SLN(10000.55, 1000.25, 7.5)', '1200.04'),
    ('SLN(10000, 10000, 5)', '0'),
    ('SLN(225113.9, 16219.53, 5)', '41778.874'),
    ('SLN(10000, 1000, 0)', "Division by zero has occurred when evaluating function 'SLN'."),
    ('SLN(10000, 1000, BLANK())', "Division by zero has occurred when evaluating function 'SLN'."),
    ('SLN(10000, 1000, "x")', "Cannot convert value 'x' of type Text to type Number."),
    ('SLN(BLANK(), BLANK(), 5)', '0'),
    ('SLN(BLANK(), 1000, 5)', '-200'),
    ('SLN("10000", "1000", "5")', '1800'),
    ('SLN(10000, 1000, TRUE())', '9000'),
    ('SLN(TRUE(), 0, 1)', '1'),
    ('SLN(1,2)', ERR),
    # SYD
    ('SYD(459426.69999999995, 145679.08, 3, 2)', '104582.54'),
    ('SYD(10000, 12000, 5, 1)', '-666.666666666667'),
    ('SYD(40504.6, 12979.34, 20, 9)', '1572.872'),
    ('SYD(10000, 1000, 5, 2)', '2400'),
    ('SYD(10000, 1000, 1, 1)', '9000'),
    ('SYD(10000, 1000, 5, 1)', '3000'),
    ('SYD(246616.6, 78114.57, 4, 1)', '67400.812'),
    ('SYD(33899.899999999994, 11316.17, 6, 2)', '5377.07857142857'),
    ('SYD(10000, 1000, BLANK(), 1)', "An argument of function 'SYD' has the wrong data type or the result is too large or too small."),
    ('SYD(10000, 1000, 5, BLANK())', "An argument of function 'SYD' has the wrong data type or the result is too large or too small."),
    ('SYD(10000, -1000, 5, 1)', "An argument of function 'SYD' has the wrong data type or the result is too large or too small."),
    ('SYD(10000, 1000, 5, "x")', "Cannot convert value 'x' of type Text to type Number."),
    ('SYD(10000, BLANK(), 5, 1)', '3333.33333333333'),
    ('SYD(BLANK(), 1000, 5, 1)', '-333.333333333333'),
    ('SYD("10000", "1000", "5", "1")', '3000'),
    ('SYD(10000, 1000, 5, TRUE())', '3000'),
    ('SYD(TRUE(), 0, 1, 1)', '1'),
    ('SYD(1,2,3)', ERR),
    # DB
    ('DB(1000000, 2000000, 6, 1)', '-122000'),
    ('DB(65618.4, 21817.41, 4, 5, 2)', '5530.73167371953'),
    ('DB(1000000, 100000, 1E9, 1E9)', '0'),
    ('DB(27574.899999999998, 7789.47, 8, 9, 1)', '1207.72209787527'),
    ('DB(1000000, 100000, 1E6, 1E6)', '0'),
    ('DB(1000000, 100000, 6, 1, 6.5)', '186083.333333333'),
    ('DB(1000000, 100000, 6, 1, 0.5)', '26583.3333333333'),
    ('DB(1000000, 100000, 6.1, 6, 12)', '47703.4980519073'),
    ('DB(1000000, 100000, 6, 0, 7)', "An argument of function 'DB' has the wrong data type or the result is too large or too small."),
    ('DB(1000000, 100000, -6, 1)', "An argument of function 'DB' has the wrong data type or the result is too large or too small."),
    ('DB(1000000, 100000, 6, 8, 7)', "An argument of function 'DB' has the wrong data type or the result is too large or too small."),
    ('DB(1000000, 100000, 6, 1, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('DB(1000000, 100000, 6, 1, 1E19)', 'The result of a conversion or arithmetic operation is either too large or too small.'),
    ('DB(BLANK(), 100000, 6, 1)', '0'),
    ('DB(1000000, BLANK(), 6, 1)', '1000000'),
    ('DB("1000000", "100000", "6", "1", "7")', '186083.333333333'),
    ('DB(1000000, 100000, 6, 1, TRUE())', '26583.3333333333'),
    ('DB(1000000, 100000, 6, TRUE())', '319000'),
    ('DB(1,2,3)', ERR),
    # DDB
    ('DDB(2400, 300, 10.5, 1)', '457.142857142857'),
    ('DDB(2400, 300, 3, 3, 3)', '0'),
    ('DDB(2400, 300, 10, 4, 10)', '0'),
    ('DDB(2400, 300, 10, 10, 3)', '0'),
    ('DDB(2400, 300, 10, 1, 10.01)', '2100'),
    ('DDB(40504.6, 12979.34, 20, 17, 2.5)', '0'),
    ('DDB(2400, 300, 10, 9.5)', '22.1225472000003'),
    ('DDB(2400, 300, 10, 1, 3)', '720'),
    ('DDB(-2400, -300, 10, 1)', "An argument of function 'DDB' has the wrong data type or the result is too large or too small."),
    ('DDB(2400, 300, 10.6, 11)', "An argument of function 'DDB' has the wrong data type or the result is too large or too small."),
    ('DDB(2400, 300, 10, 1, BLANK())', "An argument of function 'DDB' has the wrong data type or the result is too large or too small."),
    ('DDB(2400, 300, 10, 1, "x")', "Cannot convert value 'x' of type Text to type Number."),
    ('DDB(2400, BLANK(), 10, 1)', '480'),
    ('DDB(BLANK(), 300, 10, 1)', '0'),
    ('DDB("2400", "300", "10", "1", "2")', '480'),
    ('DDB(2400, 300, 10, TRUE())', '480'),
    ('DDB(2400, 300, 10, 1, TRUE())', '240'),
    ('DDB(1,2,3)', ERR),
    # VDB
    ('VDB(2400, 300, 3, 1.5, 2.5, 2)', '233.333333333333'),
    ('VDB(2400, 300, 5, 0.75, 3.75, 2)', '1317.12'),
    ('VDB(2400, 300, 10, 5.4, 5.6, 10, FALSE())', '0'),
    ('VDB(2400, 300, 10, 3, 10, 1)', '1438.5'),
    ('VDB(2400, 300, 10, 0, 7, 1)', '1483.5'),
    ('VDB(2400, 300, 10, 0, 6.5, 2)', '1833.76896'),
    ('VDB(2400, 300, 10, 5, 7.5, 10, FALSE())', '0'),
    ('VDB(2400, 300, 10, 7, 9, 10, FALSE())', '0'),
    ('VDB(2400, 300, 10, 0, 10, -1)', "An argument of function 'VDB' has the wrong data type or the result is too large or too small."),
    ('VDB(2400, 300, 10, 5, 3)', "An argument of function 'VDB' has the wrong data type or the result is too large or too small."),
    ('VDB(2400, 300, 10, -1, 3)', "An argument of function 'VDB' has the wrong data type or the result is too large or too small."),
    ('VDB(2400, 300, 10, 0, 10, 2, "x")', "Cannot convert value 'x' of type Text to type True/False."),
    ('VDB(2400, 300, 10, 6, 10, 1.5, "x")', "Cannot convert value 'x' of type Text to type True/False."),
    ('VDB(2400, 300, 10, 0, 10, BLANK())', '2100'),
    ('VDB(2400, 300, 10, 0, 10, 2, BLANK())', '2100'),
    ('VDB(2400, 300, 10, 6, 10, 1.5, "1")', '432.660267082265'),
    ('VDB(2400, 300, 10, 0, 10, 2, "1")', '2100'),
    ('VDB(TRUE(), 0, 1, 0, 1)', '1'),
    ('VDB(2400, 300, 5, 3.5, 4.5, 2, TRUE())', '109.2'),
    ('VDB(1,2,3,4)', ERR),
    # EFFECT
    ('EFFECT(0.05, 12)', '0.0511618978817334'),
    ('EFFECT(0.05, 1E18)', '0'),
    ('EFFECT(0.0549, 2)', '0.0556535025'),
    ('EFFECT(0.0585, 12)', '0.0600943016544195'),
    ('EFFECT(0.05, 4294967296)', '0.0512712968897862'),
    ('EFFECT(0.2372, 12)', '0.26476472341398'),
    ('EFFECT(0.05, 1E10)', '0.0512711007250206'),
    ('EFFECT(0.05, 0.5)', '0.05'),
    ('EFFECT(-2, 12)', "An argument of function 'EFFECT' has the wrong data type or the result is too large or too small."),
    ('EFFECT(BLANK(), 12)', "An argument of function 'EFFECT' has the wrong data type or the result is too large or too small."),
    ('EFFECT(-0.5, 12)', "An argument of function 'EFFECT' has the wrong data type or the result is too large or too small."),
    ('EFFECT(0.05, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('EFFECT("x", 12)', "Cannot convert value 'x' of type Text to type Number."),
    ('EFFECT(0.05, 1E300)', 'The result of a conversion or arithmetic operation is either too large or too small.'),
    ('EFFECT("0.05", "12")', '0.0511618978817334'),
    ('EFFECT(TRUE(), 12)', '1.61303529022468'),
    ('EFFECT(0.05, TRUE())', '0.05'),
    ('EFFECT(1)', ERR),
    # NOMINAL
    ('NOMINAL(0.1212, 52)', '0.114525471629499'),
    ('NOMINAL(1E-300, 12)', '0'),
    ('NOMINAL(0.2168, 12)', '0.19783757752246'),
    ('NOMINAL(0.05, 2147483648)', '0.0487899780273438'),
    ('NOMINAL(0.05, 0.9999)', '0.05'),
    ('NOMINAL(0.05, 4294967297)', '0.0487899780387036'),
    ('NOMINAL(0.05, 12)', '0.0488894854037776'),
    ('NOMINAL(0.033, 365)', '0.032468634178151'),
    ('NOMINAL(0.05, 0)', "An argument of function 'NOMINAL' has the wrong data type or the result is too large or too small."),
    ('NOMINAL(-2, 12)', "An argument of function 'NOMINAL' has the wrong data type or the result is too large or too small."),
    ('NOMINAL(0.05, -1)', "An argument of function 'NOMINAL' has the wrong data type or the result is too large or too small."),
    ('NOMINAL(0.05, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('NOMINAL("x", 12)', "Cannot convert value 'x' of type Text to type Number."),
    ('NOMINAL(0.05, 1E19)', 'The result of a conversion or arithmetic operation is either too large or too small.'),
    ('NOMINAL("0.05", "12")', '0.0488894854037776'),
    ('NOMINAL(TRUE(), 12)', '0.713557132311544'),
    ('NOMINAL(0.05, TRUE())', '0.05'),
    ('NOMINAL(1,2,3)', ERR),
    # RRI
    ('RRI(7, 1000, 3)', '-0.563897324915776'),
    ('RRI(10, 0, 0)', '0'),
    ('RRI(10, 1E-300, 2E-300)', '0.0717734625362931'),
    ('RRI(2.5, 1000, 2000)', '0.319507910772894'),
    ('RRI(3, 1000, 2000)', '0.259921049894873'),
    ('RRI(5, 33759.29, 36537.88)', '0.0159445576154598'),
    ('RRI(2, 12915.91, 1121.87)', '-0.705280574273108'),
    ('RRI(10, 1000, 0)', '-1'),
    ('RRI(BLANK(), 1000, 2000)', "An argument of function 'RRI' has the wrong data type or the result is too large or too small."),
    ('RRI(10, -1000, 2000)', "An argument of function 'RRI' has the wrong data type or the result is too large or too small."),
    ('RRI(10, 1000, -2000)', "An argument of function 'RRI' has the wrong data type or the result is too large or too small."),
    ('RRI(10, 1000, "x")', "Cannot convert value 'x' of type Text to type Number."),
    ('RRI(10, 1000, BLANK())', '-1'),
    ('RRI("10", "1000", "2000")', '0.0717734625362931'),
    ('RRI(TRUE(), 1000, 2000)', '1'),
    ('RRI(10, TRUE(), 2)', '0.0717734625362931'),
    ('RRI(1,2)', ERR),
    # PDURATION
    ('PDURATION(0.1984, 49121.21, 43900.81)', '-0.620806681897859'),
    ('PDURATION(0.5, 1, 100)', '11.3577471745351'),
    ('PDURATION(0.2037, 8194.86, 12158.13)', '2.1277812397003'),
    ('PDURATION(0.0991, 18927.9, 17976.36)', '-0.545862576345371'),
    ('PDURATION(1E-15, 1000, 2000)', '624331476816536'),
    ('PDURATION(0.025, 2000, 1999.9999999)', '-2.02489728270047E-09'),
    ('PDURATION(0.025, 2000, 2200)', '3.85986616262266'),
    ('PDURATION(0.0612, 41322.02, 40474.83)', '-0.348739236483507'),
    ('PDURATION(0.025, 0, 0)', "An argument of function 'PDURATION' has the wrong data type or the result is too large or too small."),
    ('PDURATION(-1.5, 1000, 2000)', "An argument of function 'PDURATION' has the wrong data type or the result is too large or too small."),
    ('PDURATION(0.025, BLANK(), 2000)', "An argument of function 'PDURATION' has the wrong data type or the result is too large or too small."),
    ('PDURATION(1E-300, 1000, 2000)', "Division by zero has occurred when evaluating function 'PDURATION'."),
    ('PDURATION(0.025, 2000, "x")', "Cannot convert value 'x' of type Text to type Number."),
    ('PDURATION("0.025", "2000", "2200")', '3.85986616262266'),
    ('PDURATION(0.025, TRUE(), 2)', '28.0710345259387'),
    ('PDURATION(0.025, 1000, TRUE())', '-279.749874732807'),
    ('PDURATION(1,2)', ERR),
    # DOLLARDE
    ('DOLLARDE(1.10, 8)', '1.125'),
    ('DOLLARDE(2.25, 4)', '2.625'),
    ('DOLLARDE(47.07, 8)', '47.0875'),
    ('DOLLARDE(1.1, 4)', '1.25'),
    ('DOLLARDE(1.02, 9E18)', '1.02222222222222'),
    ('DOLLARDE(44.54, 32)', '45.6875'),
    ('DOLLARDE(1.5, 2)', '3.5'),
    ('DOLLARDE(1.02, 7.5)', '1.025'),
    ('DOLLARDE(1.02, -16)', "An argument of function 'DOLLARDE' has the wrong data type or the result is too large or too small."),
    ('DOLLARDE(1.02, 0)', "Division by zero has occurred when evaluating function 'DOLLARDE'."),
    ('DOLLARDE(1.02, BLANK())', "Division by zero has occurred when evaluating function 'DOLLARDE'."),
    ('DOLLARDE(1.02, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('DOLLARDE(1.02, 9.3E18)', 'The result of a conversion or arithmetic operation is either too large or too small.'),
    ('DOLLARDE(BLANK(), 16)', BLANK),
    ('DOLLARDE("1.02", "16")', '1.125'),
    ('DOLLARDE(1.02, TRUE())', '1.02'),
    ('DOLLARDE(TRUE(), 16)', '1'),
    ('DOLLARDE(1)', ERR),
    # DOLLARFR
    ('DOLLARFR(1.02, 1)', '1.02'),
    ('DOLLARFR(1.17, 16)', '1.0272'),
    ('DOLLARFR(1.2, 3)', '1.06'),
    ('DOLLARFR(123456.12, 32)', '123456.0384'),
    ('DOLLARFR(94.4681, 32)', '94.149792'),
    ('DOLLARFR(1.12345, 100000)', '1.12345'),
    ('DOLLARFR(1.5, 2)', '1.1'),
    ('DOLLARFR(1.02, 7.5)', '1.016'),
    ('DOLLARFR(1.02, -16)', "An argument of function 'DOLLARFR' has the wrong data type or the result is too large or too small."),
    ('DOLLARFR(1.02, 0)', "Division by zero has occurred when evaluating function 'DOLLARFR'."),
    ('DOLLARFR(1.02, BLANK())', "Division by zero has occurred when evaluating function 'DOLLARFR'."),
    ('DOLLARFR(1.02, "x")', "Cannot convert value 'x' of type Text to type Integer."),
    ('DOLLARFR(1.02, 9.3E18)', 'The result of a conversion or arithmetic operation is either too large or too small.'),
    ('DOLLARFR(BLANK(), 16)', BLANK),
    ('DOLLARFR("1.02", "16")', '1.0032'),
    ('DOLLARFR(TRUE(), 16)', '1'),
    ('DOLLARFR(1.02, TRUE())', '1.02'),
    ('DOLLARFR(1,2,3)', ERR),
]


def is_number(text: str) -> bool:
    try:
        Decimal(text)
    except ArithmeticError:
        return False
    return True


def evaluate(expression: str) -> object:
    return evaluate_measures(
        [{"name": "M", "expression": expression}], [{"A": "1"}], ["A"], "T", measure_names=["M"]
    )["M"]


class DaxFinanceTests(unittest.TestCase):
    def test_registered_with_the_function_registry(self) -> None:
        self.assertEqual(set(dax_finance.ARITY), set(FUNCTIONS))
        for name, arity in ARITIES.items():
            self.assertEqual(dax_finance.ARITY[name], arity)
            self.assertEqual(dax_ext.ARITY[name], arity)

    def test_power_bi_answers(self) -> None:
        for expression, expected in CASES:
            with self.subTest(expression=expression):
                if expected == ERR:
                    with self.assertRaises(MeasureError):
                        evaluate(expression)
                elif expected is BLANK:
                    self.assertIsNone(evaluate(expression))
                elif not is_number(expected):
                    with self.assertRaises(MeasureError) as raised:
                        evaluate(expression)
                    self.assertEqual(str(raised.exception), expected)
                else:
                    value = evaluate(expression)
                    self.assertIsInstance(value, Decimal)
                    expected_number = Decimal(expected)
                    self.assertLessEqual(
                        abs(value - expected_number), Decimal("1e-9") * max(Decimal(1), abs(expected_number))
                    )

    def test_pv_and_fv_keep_power_bi_floating_point_behaviour(self) -> None:
        # a naive (1+r)^n - 1 loses most digits at tiny rates; Power BI shows exactly that, so does the app
        for expression, expected in [
            ("PV(1E-15, 10, -1000)", "11102.2302462514"), ("FV(1E-15, 10, -1000)", "11102.2302462516"),
            ("PV(1E-8, 360, -1000)", "359999.346407639"), ("FV(1E-8, 360, -1000)", "360000.642407599"),
        ]:
            with self.subTest(expression=expression):
                self.assertLessEqual(abs(evaluate(expression) - Decimal(expected)), Decimal("1e-9") * Decimal(expected))

    def test_rate_gives_up_exactly_where_power_bi_does(self) -> None:
        # Newton-like convergence only works for guesses within ~150 secant steps of the root
        self.assertIsNotNone(evaluate("RATE(10, -100, 800, 0, 0, 1510000)"))
        with self.assertRaises(MeasureError):
            evaluate("RATE(10, -100, 800, 0, 0, 1520000)")
        with self.assertRaises(MeasureError) as invalid:
            evaluate("RATE(10, -100, 800, 0, 0, -1)")
        self.assertIn("has an invalid value", str(invalid.exception))

    def test_cumulative_functions_match_the_period_by_period_sum(self) -> None:
        for rate, nper, pv, start, end, kind in [
            ("0.05", 10, 1000, 1, 10, 0), ("0.05", 10, 1000, 2, 5, 1), ("0.005", 360, 200000, 13, 24, 1),
            ("0.05", 10, 1000, 1, 1, 1), ("0.07", 12, 5000, 3, 9, 0),
        ]:
            with self.subTest(rate=rate, start=start, end=end, kind=kind):
                interest = sum(
                    evaluate(f"IPMT({rate}, {k}, {nper}, {-pv}, 0, {kind})") for k in range(start, end + 1)
                )
                principal = sum(
                    evaluate(f"PPMT({rate}, {k}, {nper}, {-pv}, 0, {kind})") for k in range(start, end + 1)
                )
                self.assertAlmostEqual(float(evaluate(f"CUMIPMT({rate}, {nper}, {pv}, {start}, {end}, {kind})")), float(-interest), places=7)
                self.assertAlmostEqual(float(evaluate(f"CUMPRINC({rate}, {nper}, {pv}, {start}, {end}, {kind})")), float(-principal), places=7)


if __name__ == "__main__":
    unittest.main()
