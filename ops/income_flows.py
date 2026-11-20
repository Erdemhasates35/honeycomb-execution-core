#!/usr/bin/env python3
"""Sapma sifir. Sponsor bahsisi ucreti silmez. Ag cagrisi yok."""
N = 1_000_000_000
FLASH = 0.0003

def two(edge, a, b, tip):
    return (N * (1 + edge) * (1 - a) * (1 - b) - tip - N) / N

def tri(rates, fee, tip):
    m = float(N)
    for r in rates:
        m *= r * (1 - fee)
    return (m - N * (1 + FLASH) - tip) / N

def ftwo(a, b):
    return two(0, a, b, 0) - FLASH

ROWS = [
    ("a1", two(0, 0.0025, 0.0025, 10_000)),
    ("a2", two(0, 0.0001, 0.0001, 10_000)),
    ("a3", tri((1, 1, 1), 0.0025, 10_000)),
    ("a4", tri((1.0002, 1.0002, 1.0002), 0.0025, 10_000)),
    ("a5", two(0.01, 0.0025, 0.0025, 10_000)),
    ("f1", ftwo(0.0025, 0.0025)),
    ("f2", tri((1, 1, 1), 0.0025, 0)),
    ("f3", (1 - 0.0025) - (1 + FLASH)),
    ("f4", ftwo(0.0001, 0.0001)),
    ("f5", ftwo(0.0025, 0.0025)),
    ("b1", (1 - 0.0002) ** 2 - 1),
    ("b2", (1 - 0.0005) ** 2 - 1),
    ("b3", (1 - 0.0005) ** 2 - 1),
    ("b4", (1 - 0.0004) ** 3 - 1),
    ("b5", -0.0002),
]

def main():
    best = max((r for r in ROWS if r[0] != "a5"), key=lambda r: r[1])
    print("BEST", best[0], round(best[1] * 100, 4))
    print("SUM", round(sum(r[1] for r in ROWS) * 100, 4))
    for i, n in ROWS:
        print(i, round(n * 100, 4))

if __name__ == "__main__":
    main()
