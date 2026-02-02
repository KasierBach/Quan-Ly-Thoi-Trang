
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from app.database import CaseInsensitiveRecord

# Test 1: Exact key
r = CaseInsensitiveRecord({'id': 123})
print(f"Test 1 (id): {r.get('id')}")

# Test 2: Case variation
r = CaseInsensitiveRecord({'CustomerID': 456})
print(f"Test 2 (customerid): {r.get('customerid')}")
print(f"Test 2 (id): {r.get('id')}")

# Test 3: Mixed case in dict
r = CaseInsensitiveRecord({'Id': 789})
print(f"Test 3 (id): {r.get('id')}")
