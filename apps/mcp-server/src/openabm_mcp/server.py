from __future__ import annotations

import json

from openabm_mcp.tools import all_tool_definitions


def main() -> None:
    print(json.dumps({"tools": all_tool_definitions()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

