# src/qae/__init__.py
"""
QAE (Quantum Amplitude Estimation) utilities for SpinQit + Triangulum.

This package implements:
- quadrature grids (left/right/midpoint) and Simpson-type combination,
- state preparation A for g(x)=sin^2(pi x) on [0,y] using 2 index qubits + 1 ancilla,
- reflections S_{psi0} (Z on ancilla) and S0 (reflection about |000> via X..CCZ..X),
- Grover operator iteration Q,
- MLAE-style execution (few k values) + classical MLE postprocessing.
"""

from .quadrature import grid_points, simpson_combine
from .state_prep import build_A_spec, apply_A_from_spec, apply_Adag_from_spec
from .reflections import apply_S_psi0, apply_S0
from .grover_op import apply_Q_iteration
from .postprocess import mle_amplitude, amplitude_to_integral_report
