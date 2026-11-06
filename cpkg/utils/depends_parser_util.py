import re
from pathlib import Path


class DependsParser:
    def __init__(self, file: str | Path | None = None):
        self.file = Path(file) if isinstance(file, str) else file
        self.pattern = re.compile(
            r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(==|!=|<=|>=|~=|<|>)?\s*([\w.*+!-]*)"
        )

    def parse_line(self, line: str):
        """Parse one `name[op version]` spec. Returns (name, op, version) or None."""
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            return None
        match = self.pattern.match(line)
        if not match:
            return None
        name, op, vs = match.groups()
        return (name, op or "", vs or "")

    def parse(self):
        if self.file is None:
            return []
        results = []
        for line in self.file.read_text().splitlines():
            parsed = self.parse_line(line)
            if parsed:
                results.append(parsed)
        return results
