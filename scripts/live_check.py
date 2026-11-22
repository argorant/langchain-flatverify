"""Live smoke test against the real API. Skips unless FLATVERIFY_API_KEY is set.

Run with: uv run python scripts/live_check.py
"""

import os
import sys

from langchain_flatverify import FlatverifyToolkit


def main() -> int:
    """Run one single check and one bulk check."""
    if not os.environ.get("FLATVERIFY_API_KEY"):
        print("FLATVERIFY_API_KEY is not set, skipping the live check.")
        return 0
    verify, bulk, _ = FlatverifyToolkit().get_tools()
    print(verify.invoke({"email": "maya.chen@amazon.com"}))
    print(bulk.invoke({"emails": ["j.ortiz@salesforce.com", "info@shopify.com"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
