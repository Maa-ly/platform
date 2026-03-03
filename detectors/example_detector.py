#!/usr/bin/env python3
"""Example detector that returns no findings.

Replace this with your scanner / LLM pipeline.
"""

import json


def main() -> None:
    # Contract: print a JSON list of finding objects to stdout.
    # Returning an empty list means no findings in this scan.
    print(json.dumps([]))


if __name__ == "__main__":
    main()
