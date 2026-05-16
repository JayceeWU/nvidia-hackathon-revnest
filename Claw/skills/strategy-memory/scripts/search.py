from __future__ import annotations

import argparse
import json

from strategy_memory import search_strategy_memory


def main() -> None:
    parser = argparse.ArgumentParser(description="Search RevNest strategy memory.")
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(search_strategy_memory(args.query, args.top_k), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
