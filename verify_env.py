import sys
print("Python Executable:", sys.executable)
print("Python Version:", sys.version)

mods = ["fastapi", "uvicorn", "sqlalchemy", "pydantic", "curl_cffi", "numpy", "pandas", "scipy"]
for m in mods:
    try:
        mod = __import__(m)
        print(f"  {m}: {getattr(mod, '__version__', 'INSTALLED')}")
    except Exception as e:
        print(f"  {m}: ERROR {e}")
