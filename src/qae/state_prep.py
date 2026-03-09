#src/qae/state_prep.py
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Literal, Sequence, Tuple

from .quadrature import Rule, grid_points

GFunc = Literal[
    "sin2_pi",
    "x",
    "x2",
    "sqrt_x",
    "exp_minus_x",
    "parabola",
]


@dataclass(frozen=True)
class ASpec:
    index_qubits: Tuple[int, ...]
    ancilla: int
    patterns: Tuple[Tuple[Tuple[int, ...], float], ...]


def _clip01(v: float) -> float:
    return min(max(v, 0.0), 1.0)


def _g_value(x: float, gfunc: GFunc) -> float:
    if gfunc == "sin2_pi":
        return math.sin(math.pi * x) ** 2
    if gfunc == "x":
        return x
    if gfunc == "x2":
        return x**2
    if gfunc == "sqrt_x":
        return math.sqrt(x)
    if gfunc == "exp_minus_x":
        return math.exp(-x)
    if gfunc == "parabola":
        return 4.0 * x * (1.0 - x)
    raise ValueError(f"Unknown gfunc: {gfunc}")


def exact_integral(y: float, gfunc: GFunc) -> float | None:
    if gfunc == "sin2_pi":
        return 0.5 * y - math.sin(2.0 * math.pi * y) / (4.0 * math.pi)
    if gfunc == "x":
        return 0.5 * y**2
    if gfunc == "x2":
        return y**3 / 3.0
    if gfunc == "sqrt_x":
        return (2.0 / 3.0) * y ** 1.5
    if gfunc == "exp_minus_x":
        return 1.0 - math.exp(-y)
    if gfunc == "parabola":
        return 2.0 * y**2 - (4.0 / 3.0) * y**3
    return None


def build_A_spec(
    y: float,
    n_index_qubits: int = 2,
    rule: Rule = "midpoint",
    gfunc: GFunc = "sin2_pi",
    index_qubits: Sequence[int] = (0, 1),
    ancilla: int = 2,
) -> ASpec:
    if len(index_qubits) != n_index_qubits:
        raise ValueError("index_qubits length must match n_index_qubits.")
    grid = grid_points(y=y, n=n_index_qubits, rule=rule)
    m = 2**n_index_qubits

    patterns: List[Tuple[Tuple[int, ...], float]] = []
    for i in range(m):
        bits = tuple((i >> (n_index_qubits - 1 - b)) & 1 for b in range(n_index_qubits))
        x_i = grid.points[i]

        if gfunc == "sin2_pi":
            theta = 2.0 * math.pi * x_i
        else:
            gx = _clip01(_g_value(x_i, gfunc))
            theta = 2.0 * math.asin(math.sqrt(gx))

        patterns.append((bits, theta))

    return ASpec(index_qubits=tuple(index_qubits), ancilla=ancilla, patterns=tuple(patterns))


def _get_gates():
    from spinqit import H, X, Ry  # type: ignore
    from spinqit.primitive import MultiControlledGateBuilder  # type: ignore
    return H, X, Ry, MultiControlledGateBuilder


def _extract_affine_angles_for_two_controls(spec: ASpec, tol: float = 1e-9):
    if len(spec.index_qubits) != 2 or len(spec.patterns) != 4:
        return None

    angle_map = {bits: theta for bits, theta in spec.patterns}
    required = [(0, 0), (0, 1), (1, 0), (1, 1)]
    if any(bits not in angle_map for bits in required):
        return None

    t00 = angle_map[(0, 0)]
    t01 = angle_map[(0, 1)]
    t10 = angle_map[(1, 0)]
    t11 = angle_map[(1, 1)]

    c0 = t00
    c1 = t10 - t00
    c2 = t01 - t00

    if abs((c0 + c1 + c2) - t11) > tol:
        return None

    return c0, c1, c2


def is_affine_hardware_friendly(spec: ASpec, tol: float = 1e-9) -> bool:
    return _extract_affine_angles_for_two_controls(spec, tol=tol) is not None


def _apply_single_controlled_ry(circuit, control: int, target: int, theta: float):
    if abs(theta) < 1e-12:
        return

    H, X, Ry, MultiControlledGateBuilder = _get_gates()
    c_ry = MultiControlledGateBuilder(1, Ry, [theta]).to_gate()
    circuit << (c_ry, (control, target))


def _apply_controlled_ry_on_pattern(
    circuit,
    controls: Sequence[int],
    ancilla: int,
    theta: float,
    bits: Tuple[int, ...],
):
    H, X, Ry, MultiControlledGateBuilder = _get_gates()

    flipped = []
    for q, b in zip(controls, bits):
        if b == 0:
            circuit << (X, q)
            flipped.append(q)

    mc_ry = MultiControlledGateBuilder(len(controls), Ry, [theta]).to_gate()
    qubits = tuple(list(controls) + [ancilla])
    circuit << (mc_ry, qubits)

    for q in flipped:
        circuit << (X, q)


def apply_A_from_spec(circuit, spec: ASpec):
    H, X, Ry, MultiControlledGateBuilder = _get_gates()

    for q in spec.index_qubits:
        circuit << (H, q)

    affine = _extract_affine_angles_for_two_controls(spec)
    if affine is not None:
        c0, c1, c2 = affine
        q0, q1 = spec.index_qubits
        a = spec.ancilla

        if abs(c0) > 1e-12:
            circuit << (Ry, a, c0)
        _apply_single_controlled_ry(circuit, q0, a, c1)
        _apply_single_controlled_ry(circuit, q1, a, c2)
        return

    for bits, theta in spec.patterns:
        _apply_controlled_ry_on_pattern(circuit, spec.index_qubits, spec.ancilla, theta, bits)


def apply_Adag_from_spec(circuit, spec: ASpec):
    H, X, Ry, MultiControlledGateBuilder = _get_gates()

    affine = _extract_affine_angles_for_two_controls(spec)
    if affine is not None:
        c0, c1, c2 = affine
        q0, q1 = spec.index_qubits
        a = spec.ancilla

        _apply_single_controlled_ry(circuit, q1, a, -c2)
        _apply_single_controlled_ry(circuit, q0, a, -c1)
        if abs(c0) > 1e-12:
            circuit << (Ry, a, -c0)

        for q in spec.index_qubits:
            circuit << (H, q)
        return

    for bits, theta in reversed(spec.patterns):
        _apply_controlled_ry_on_pattern(circuit, spec.index_qubits, spec.ancilla, -theta, bits)

    for q in spec.index_qubits:
        circuit << (H, q)