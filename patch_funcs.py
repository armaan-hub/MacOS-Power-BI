with open("analytics_studio/measures.py", "r") as f:
    text = f.read()

old_func = """    "PREVIOUSYEAR", "PREVIOUSQUARTER", "PREVIOUSMONTH",
    "DATEADD", "SAMEPERIODLASTYEAR", "CALCULATE", "KEEPFILTERS", "FILTER","""

new_func = """    "PREVIOUSYEAR", "PREVIOUSQUARTER", "PREVIOUSMONTH", "PREVIOUSDAY",
    "NEXTYEAR", "NEXTQUARTER", "NEXTMONTH", "NEXTDAY",
    "PARALLELPERIOD",
    "DATEADD", "SAMEPERIODLASTYEAR", "CALCULATE", "KEEPFILTERS", "FILTER","""
text = text.replace(old_func, new_func)

old_time = """    "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER",
    "PREVIOUSMONTH", "DATESYTD", "DATESQTD", "DATESMTD", "DATESBETWEEN",
    "DATESINPERIOD",
}"""

new_time = """    "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER",
    "PREVIOUSMONTH", "PREVIOUSDAY", "NEXTYEAR", "NEXTQUARTER", "NEXTMONTH", "NEXTDAY",
    "PARALLELPERIOD",
    "DATESYTD", "DATESQTD", "DATESMTD", "DATESBETWEEN",
    "DATESINPERIOD",
}"""
text = text.replace(old_time, new_time)

with open("analytics_studio/measures.py", "w") as f:
    f.write(text)
