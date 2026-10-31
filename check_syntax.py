import re

with open(r'c:\Projects\NSE dashboard\backend\app\static\index.html', 'r', encoding='utf-8') as f:
    text = f.read()

m = re.search(r'<script type="text/babel">(.*?)</script>', text, re.DOTALL)
if m:
    code = m.group(1)
    print("Found Babel script! Length:", len(code))
    
    # Check brace balance
    open_braces = code.count('{')
    close_braces = code.count('}')
    print(f"Open braces {{: {open_braces}, Close braces }}: {close_braces}")
    
    open_parens = code.count('(')
    close_parens = code.count(')')
    print(f"Open parens (: {open_parens}, Close parens ): {close_parens}")
    
    open_brackets = code.count('[')
    close_brackets = code.count(']')
    print(f"Open brackets [: {open_brackets}, Close brackets ]: {close_brackets}")
else:
    print("No babel script found!")
