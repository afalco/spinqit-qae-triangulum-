# src/backends/simulator.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class SimulatorConfig:
    shots: int = 4096


class SimulatorBackend:
    """
    Thin wrapper around a SpinQit simulator backend.

    The exact simulator getter name can vary by SpinQit version.
    If `get_basic_simulator()` does not exist in your installation, replace it with
    the appropriate simulator constructor (e.g., statevector or qasm-style simulator).
    """

    def __init__(self, cfg: SimulatorConfig = SimulatorConfig()):
        self.cfg = cfg
        self._engine = self._make_engine()

    @staticmethod
    def _make_engine():
        from spinqit import get_basic_simulator  # type: ignore
        return get_basic_simulator()

    def run(self, circuit, shots: int = 4096) -> Dict[str, int]:
        engine = self._engine
        result = None

        # Try common invocation patterns
        try:
            result = engine.execute(circuit, shots=shots)
        except Exception:
            try:
                result = engine.run(circuit, shots=shots)
            except Exception as e:
                raise RuntimeError(
                    "Could not execute circuit on simulator backend. "
                    "Please adapt SimulatorBackend.run() to your SpinQit version."
                ) from e

        if isinstance(result, dict):
            return result
        if hasattr(result, "counts"):
            return result.counts
        if hasattr(result, "get_counts"):
            return result.get_counts()

        raise RuntimeError("Simulator backend returned an unsupported result type; please adapt counts extraction.")
