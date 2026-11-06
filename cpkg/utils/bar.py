"""
bar submodule for cpkg. Provide progress-bars of many kinds.
Copyright (c) 2026 Alan. All Rights Reserved.
"""

from sys import stdout
from time import sleep, time


class ProgressBars:
    def __init__(self):
        self.block_full_char = chr(9608)

    def normal_bar(self, iter: int, total: int, len: int = 30):
        perc = int(100 * (iter / float(total)))
        filled_len = int(len * iter // total)

        bar = self.block_full_char * filled_len + "-" * (len - filled_len)
        stdout.write(f"\r|{bar}| {perc}% complete")
        stdout.flush()

    def linear_spinner_bar(self, duration_sec: int = 5):
        wid = 15
        dot_c = 3
        start = time()

        while time() - start < duration_sec:
            for i in range(wid + dot_c):
                track = [" "] * wid
                for d in range(dot_c):
                    pos = i - d
                    if 0 <= pos < wid:
                        track[pos] = "."
                frame = "".join(track)
                stdout.write(f"\r   [{frame}]   ")
                stdout.flush()
                if i < 3 or i > wid - 2:
                    sleep(0.08)
                else:
                    sleep(0.04)
        stdout.write(f"\r{' ' * (wid + 10)}\n")

    def cylon_bar(self, duration: int = 5):
        wid = 20
        start = time()

        while time() - start < duration:
            for pos in range(wid):
                bar = ["-"] * wid
                bar[pos] = self.block_full_char
                stdout.write(f"\r[{''.join(bar)}]")
                stdout.flush()
                sleep(0.04)

            for pos in range(wid - 1, -1, -1):
                bar = ["-"] * wid
                bar[pos] = self.block_full_char
                stdout.write(f"\r[{''.join(bar)}]")
                stdout.flush()
                sleep(0.04)


if __name__ == "__main__":
    t = ProgressBars()
    total_steps = 50
    for i in range(total_steps + 1):
        t.normal_bar(i, total_steps)
        sleep(0.05)
    print()

    t.linear_spinner_bar()
    t.cylon_bar()
    print()
