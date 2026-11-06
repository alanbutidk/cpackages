if __import__("sys").platform == "win32":
    import ctypes

    k32 = ctypes.windll.kernel32
    STD_OUTPUT_HANDLE = -11
    hStdout = k32.GetStdHandle(STD_OUTPUT_HANDLE)
    mode = ctypes.c_ulong()
    k32.GetConsoleMode(hStdout, ctypes.byref(mode))

    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    k32.SetConsoleMode(hStdout, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)

# Class code:


class Color:
    def __init__(self):
        self.RESET = "\033[0m"
        self.BOLD = "\033[1m"
        self.UNDERLINE = "\033[4m"
        self.RED = "\033[31m"
        self.GREEN = "\033[32m"
        self.YELLOW = "\033[33m"
        self.BLUE = "\033[34m"
        self.CYAN = "\033[36m"
        self.BG_RED = "\033[41m"
        self.BG_BLACK = "\033[40m"
        self.BG_GREEN = "\033[42m"
        self.BG_YELLOW = "\033[43m"
        self.BG_BLUE = "\033[44m"
        self.BG_MAGENTA = "\033[45m"
        self.BG_CYAN = "\033[46m"
        self.BG_WHITE = "\033[47m"
        self.BG_DEFAULT = "\033[49m"


if __name__ == "__main__":
    c = Color()
    print(f"{c.CYAN}{c.UNDERLINE}Hello{c.RESET}")
