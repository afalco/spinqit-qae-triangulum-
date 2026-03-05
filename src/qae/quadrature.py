# src/qae/quadrature.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal

Rule = Literal["left", "right", "midpoint"]


@dataclass(frozen=True)
class Grid:
    """Uniform grid on [0,y] with 2^n points, using a chosen quadrature sampling rule."""
    y: float
    n: int
    rule: Rule
    points: List[float]


def grid_points(y: float, n: int, rule: Rule = "midpoint") -> Grid:
    """
    Return sampling points x_i in [0,y] for i=0..2^n-1 under a simple quadrature rule.

    - left:     x_i = y * i / 2^n
    - right:    x_i = y * (i+1) / 2^n
    - midpoint: x_i = y * (i+1/2) / 2^n

    For Triangulum demos: n=2 (4 points).
    """
    if not (0.0 <= y <= 1.0):
        raise ValueError("y must be in [0,1].")
    if n < 1:
        raise ValueError("n must be >= 1.")
    m = 2**n

    pts: List[float] = []
    if rule == "left":
        pts = [y * (i / m) for i in range(m)]
    elif rule == "right":
        pts = [y * ((i + 1) / m) for i in range(m)]
    elif rule == "midpoint":
        pts = [y * ((i + 0.5) / m) for i in range(m)]
    else:
        raise ValueError(f"Unknown rule: {rule}")

    return Grid(y=y, n=n, rule=rule, points=pts)


def simpson_combine(I_left: float, I_mid: float, I_right: float) -> float:
    """
    Simpson-type combination from left/mid/right estimators:
        I_S ≈ (I_left + 4 I_mid + I_right)/6

    This is a purely classical post-processing step that can reduce quadrature bias
    without increasing qubit count (at the cost of 3 separate runs).
    """
    return (I_left + 4.0 * I_mid + I_right) / 6.0
