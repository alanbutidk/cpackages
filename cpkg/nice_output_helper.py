"""
nice_output helper. Styles output for CPackages
Why this:

- CPackage relies on it for install out, upgrade out etc.
- Fully built with the Python Standard Library
"""

from .utils.bar import ProgressBars
from .utils.color import Color


class NiceOutputs:
    def __init__(self):
        self.c = Color()
        self.bars = ProgressBars()

    def install_output(
        self,
        pkg_name: str = "",
    ):
        print(f"{self.c.CYAN}Installing package {pkg_name}!{self.c.RESET}")

    def installed_output(self, pkg_name: str, version: str):
        print(
            f"{self.c.GREEN}{self.c.BOLD}Installed {pkg_name} {version}.{self.c.RESET}"
        )

    def already_output(self, pkg_name: str, version: str):
        print(f"{self.c.CYAN}{pkg_name} {version} is already installed.{self.c.RESET}")

    def remove_output(self, pkg_name: str):
        print(f"{self.c.GREEN}Removed {pkg_name}.{self.c.RESET}")

    def progress(self, done: int, total: int):
        self.bars.normal_bar(done, total)
        if done >= total:
            print()

    def table(self, rows: list[tuple[str, ...]], headers: tuple[str, ...]):
        data = [headers] + rows
        widths = [max(len(str(r[i])) for r in data) for i in range(len(headers))]
        for n, row in enumerate(data):
            line = "  ".join(str(v).ljust(widths[i]) for i, v in enumerate(row))
            if n == 0:
                line = f"{self.c.BOLD}{line}{self.c.RESET}"
            print(line)
