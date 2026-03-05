# src/qae/mlae.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from .grover_op import apply_Q_iteration
from .state_prep import ASpec, build_A_spec, apply_A_from_spec


@dataclass(frozen=True)
class RunResult:
    """
    Container for a single MLAE run over a list of k values.
    """
    y: float
    rule: str
    ks: Tuple[int, ...]
    shots: int
    counts_per_k: Tuple[Dict[str, int], ...]  # bitstring -> count
    p_hat: Tuple[float, ...]                  # empirical Pr(ancilla=1) per k


def _extract_ancilla_1_prob(counts: Dict[str, int], ancilla_bit_index_from_right: int) -> float:
    """
    Extract Pr(ancilla=1) from measurement counts.

    IMPORTANT:
      Bitstring ordering (endianness) may differ across SpinQit backends.
      `ancilla_bit_index_from_right` is the position of the ancilla bit when counting
      from the rightmost character of the returned bitstring:
        0 = rightmost bit, 1 = second from right, etc.

      For a 3-qubit register with ancilla qubit index=2, a common default is 2,
      but you should calibrate this if results look inconsistent.
    """
    total = sum(counts.values())
    if total <= 0:
        return 0.0

    ones = 0
    for bitstr, c in counts.items():
        s = bitstr.replace("0b", "").strip()
        if len(s) < ancilla_bit_index_from_right + 1:
            s = s.zfill(ancilla_bit_index_from_right + 1)
        anc_bit = s[-1 - ancilla_bit_index_from_right]
        if anc_bit == "1":
            ones += c

    return ones / total


def build_circuit_for_k(spec: ASpec, k: int):
    """
    Construct a SpinQit circuit for a given amplification index k:
        circuit = Q^k A |000>
    Then append measurement.

    Returns a SpinQit Circuit instance.
    """
    from spinqit import Circuit  # type: ignore

    circ = Circuit()

    # Allocate 3 qubits explicitly (Triangulum: 2 index + 1 ancilla)
    try:
        circ.allocateQubits(3)
    except Exception:
        # Some SpinQit versions may not throw; keep best-effort.
        pass

    # Prepare A|000>
    apply_A_from_spec(circ, spec)

    # Apply Q^k
    for _ in range(int(k)):
        apply_Q_iteration(circ, spec)

    # Measure (API varies across versions; try common names)
    try:
        circ.measure_all()
    except Exception:
        try:
            circ.measure(range(3))
        except Exception:
            # If your SpinQit uses a different measurement call, adapt here.
            pass

    return circ


def run_mlae(
    backend,
    y: float,
    ks: Sequence[int] = (0, 1, 2),
    rule: str = "midpoint",
    shots: int = 4096,
    ancilla_qubit: int = 2,
    index_qubits: Sequence[int] = (0, 1),
    ancilla_bit_index_from_right: int = 2,
) -> RunResult:
    """
    Execute MLAE-style runs for each k in `ks` on the provided backend wrapper.

    The `backend` object must expose:
        run(circuit, shots=...) -> counts
    where counts is a dict: {bitstring: count}, or a result object containing such counts.

    Parameters:
      - y: integral upper limit in [0,1]
      - rule: 'left' | 'right' | 'midpoint'
      - ks: list of amplification indices
      - shots: number of shots per circuit
      - ancilla_bit_index_from_right: how to locate ancilla bit in returned bitstrings
    """
    spec = build_A_spec(
        y=y,
        n_index_qubits=len(index_qubits),
        rule=rule,  # type: ignore
        index_qubits=index_qubits,
        ancilla=ancilla_qubit,
    )

    counts_list: List[Dict[str, int]] = []
    p_list: List[float] = []

    for k in ks:
        circ = build_circuit_for_k(spec, int(k))
        result = backend.run(circ, shots=shots)

        # Normalize result -> dict counts
        if isinstance(result, dict):
            counts = result
        elif hasattr(result, "counts"):
            counts = result.counts
        elif hasattr(result, "get_counts"):
            counts = result.get_counts()
        else:
            raise RuntimeError(
                "Backend returned an unsupported result type. "
                "Please adapt backend.run() to return dict counts or a compatible object."
            )

        counts_list.append(counts)
        p_list.append(_extract_ancilla_1_prob(counts, ancilla_bit_index_from_right))

    return RunResult(
        y=float(y),
        rule=str(rule),
        ks=tuple(int(k) for k in ks),
        shots=int(shots),
        counts_per_k=tuple(counts_list),
        p_hat=tuple(p_list),
    )
