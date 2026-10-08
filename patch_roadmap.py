with open("POWER_BI_FUNCTIONALITY_ROADMAP.md", "r") as f:
    text = f.read()

text = text.replace("6.5.6.3.15 Same-call Boolean and time-intelligence filter combinations<br/>Active", "6.5.6.3.15 Same-call Boolean and time-intelligence filter combinations<br/>1 test / 376 full; combined evaluator passed")
text = text.replace("6.5.6.3.16 Other time-intelligence filter expressions<br/>Queued", "6.5.6.3.16 Other time-intelligence filter expressions<br/>Active")

with open("POWER_BI_FUNCTIONALITY_ROADMAP.md", "w") as f:
    f.write(text)

with open("POWER_BI_FUNCTIONALITY_PROGRESS.md", "r") as f:
    text2 = f.read()

text2 = text2.replace("373 passed and 231 subtests passed", "376 passed and 229 subtests passed")
text2 = text2.replace("373 passed, 231 subtests passed", "376 passed, 229 subtests passed")
text2 = text2.replace("Same-call Boolean and time-intelligence filter combinations is the next active", "Other time-intelligence filter expressions is the next active")
text2 = text2.replace("Same-call Boolean and time-intelligence filter combinations** in the local DAX evaluator, as marked active", "Other time-intelligence filter expressions** in the local DAX evaluator, as marked active")

with open("POWER_BI_FUNCTIONALITY_PROGRESS.md", "w") as f:
    f.write(text2)
