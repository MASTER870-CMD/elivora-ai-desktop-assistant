import re
with open('ap copy.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find all ALL_CAPS = """ or ''' blocks
for m in re.finditer(r'([A-Z_]+) = r?(\"\"\"|\'\'\')', content):
    var_name = m.group(1)
    start = m.end()
    quote = m.group(2)
    end = content.find(quote, start)
    print(f"Variable: {var_name}, length: {end - start}")
