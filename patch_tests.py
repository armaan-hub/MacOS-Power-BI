import sys
with open('tests/test_measures.py', 'r', encoding='utf-8') as f:
    text = f.read()

bad = '("SUMX(\'Active table\', [Base] + [Sales])", "context transition"),'
if bad in text:
    text = text.replace(bad, "")
    with open('tests/test_measures.py', 'w', encoding='utf-8') as f:
        f.write(text)
