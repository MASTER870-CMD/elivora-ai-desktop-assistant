import re
with open('ap copy.py', 'r', encoding='utf-8') as f:
    content = f.read()

m = re.search(r'(?s)CLOUD_HTML = r?(\"\"\"|\'\'\')(.*?)(\1)', content)
if m:
    print(f"Found it! Starts with: {m.group(0)[:50]} Ends with: {m.group(0)[-50:]}")
else:
    print("Not found with this regex.")
