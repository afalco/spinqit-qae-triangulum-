# calibrate_bit_order.py
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Optional


TEST_CASES = [
    {"name": "none", "flips": []},
    {"name": "x_q0", "flips": [0]},
    {"name": "x_q1", "flips": [1]},
    {"name": "x_q2", "flips": [2]},
    {"name": "x_q0_q1", "flips": [0, 1]},
    {"name": "x_q0_q2", "flips": [0, 2]},
    {"name": "x_q1_q2", "flips": [1, 2]},
    {"name": "x_q0_q1_q2", "flips": [0, 1, 2]},
]

STATES = [format(i, "03b") for i in range(8)]

NMR_MAX_TRIES = 4
NMR_BASE_SLEEP = 2.0
NMR_JITTER = 0.25
COOLDOWN_S = 1.0
EPS_TAIL = 1e-3


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Standalone 3-qubit bit-order calibration for SpinQit simulator or Triangulum."
    )
    p.add_argument(
        "--backend",
        type=str,
        choices=["sim", "triangulum"],
        required=True,
        help="Backend to use: sim or triangulum.",
    )
    p.add_argument("--shots", type=int, default=256, help="Shots per test circuit.")
    p.add_argument("--outdir", type=str, default="bit_order_calibration", help="Output directory.")
    p.add_argument(
        "--probe-only",
        action="store_true",
        help="Only probe the backend API and exit without running circuits.",
    )

    p.add_argument("--ip", type=str, default=None, help="Triangulum IP.")
    p.add_argument("--port", type=int, default=55444, help="Triangulum port.")
    p.add_argument("--account", type=str, default=None, help="Triangulum account.")
    p.add_argument("--password", type=str, default=None, help="Triangulum password.")
    p.add_argument("--task-prefix", type=str, default="bit_order_calib", help="Triangulum task prefix.")
    return p.parse_args()


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def clean_bitstring(s: str) -> str:
    return s.replace("0b", "").strip()


def normalize_distribution(d: dict[str, float]) -> dict[str, float]:
    out = {s: float(d.get(s, 0.0)) for s in STATES}
    total = sum(out.values())
    if total <= 0:
        return {s: 0.0 for s in STATES}
    return {s: out[s] / total for s in STATES}


def dominant_bitstring(dist: dict[str, float]) -> str:
    if not dist:
        return ""
    return max(dist.items(), key=lambda kv: kv[1])[0]


def expected_bitstring_q0q1q2(flips: list[int]) -> str:
    bits = ["0", "0", "0"]
    for q in flips:
        bits[q] = "1"
    return "".join(bits)


def expected_bitstring_q2q1q0(flips: list[int]) -> str:
    return expected_bitstring_q0q1q2(flips)[::-1]


def add_identity_safe_tail(circ, q) -> None:
    from spinqit import Ry  # type: ignore

    circ << (Ry, q[0], EPS_TAIL)
    circ << (Ry, q[0], -EPS_TAIL)


def build_circuit(flips: list[int], ensure_nmr_attrs: bool = False):
    from spinqit import Circuit, X  # type: ignore

    circ = Circuit()
    q = circ.allocateQubits(3)

    for qi in flips:
        circ << (X, q[qi])

    if ensure_nmr_attrs:
        add_identity_safe_tail(circ, q)

    return circ


def public_attrs(obj: Any) -> list[str]:
    return [name for name in dir(obj) if not name.startswith("_")]


def compile_circuit(circ):
    from spinqit import get_compiler  # type: ignore

    comp = get_compiler("native")
    return comp.compile(circ, 0)


def make_backend(args: argparse.Namespace):
    if args.backend == "sim":
        from spinqit import BasicSimulatorConfig, get_basic_simulator  # type: ignore

        eng = get_basic_simulator()
        cfg = BasicSimulatorConfig()
        cfg.configure_shots(int(args.shots))
        return eng, cfg

    from spinqit import NMRConfig, get_nmr  # type: ignore

    if not args.ip or not args.account or not args.password:
        raise SystemExit("For --backend triangulum you must provide --ip, --account, and --password.")

    eng = get_nmr()
    cfg = NMRConfig()
    cfg.configure_ip(args.ip)
    cfg.configure_port(int(args.port))
    cfg.configure_account(args.account, args.password)
    cfg.configure_task(args.task_prefix, "3-qubit bit-order calibration")
    cfg.configure_shots(int(args.shots))
    return eng, cfg


def probe_backend_api(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {"backend": args.backend}

    if args.backend == "sim":
        from spinqit import BasicSimulatorConfig, get_basic_simulator, get_compiler  # type: ignore

        eng = get_basic_simulator()
        comp = get_compiler("native")
        cfg = BasicSimulatorConfig()

        payload["engine_type"] = str(type(eng))
        payload["engine_public_attrs"] = public_attrs(eng)
        payload["compiler_type"] = str(type(comp))
        payload["compiler_public_attrs"] = public_attrs(comp)
        payload["sim_config_type"] = str(type(cfg))
        payload["sim_config_public_attrs"] = public_attrs(cfg)

    else:
        from spinqit import NMRConfig, get_compiler, get_nmr  # type: ignore

        eng = get_nmr()
        comp = get_compiler("native")
        cfg = NMRConfig()

        payload["engine_type"] = str(type(eng))
        payload["engine_public_attrs"] = public_attrs(eng)
        payload["compiler_type"] = str(type(comp))
        payload["compiler_public_attrs"] = public_attrs(comp)
        payload["config_type"] = str(type(cfg))
        payload["config_public_attrs"] = public_attrs(cfg)

    return payload


def print_probe(payload: dict[str, Any]) -> None:
    print("=== BACKEND PROBE ===")
    print("backend:", payload.get("backend"))
    print("engine_type:", payload.get("engine_type"))
    print("engine_public_attrs:")
    for name in payload.get("engine_public_attrs", []):
        print(" ", name)

    if "compiler_type" in payload:
        print("compiler_type:", payload.get("compiler_type"))
        print("compiler_public_attrs:")
        for name in payload.get("compiler_public_attrs", []):
            print(" ", name)

    if "sim_config_type" in payload:
        print("sim_config_type:", payload.get("sim_config_type"))
        print("sim_config_public_attrs:")
        for name in payload.get("sim_config_public_attrs", []):
            print(" ", name)

    if "config_type" in payload:
        print("config_type:", payload.get("config_type"))
        print("config_public_attrs:")
        for name in payload.get("config_public_attrs", []):
            print(" ", name)


def extract_distribution(result: Any) -> dict[str, float]:
    out = getattr(result, "probabilities", None) or getattr(result, "counts", None)
    if out is None or len(out) == 0:
        raise RuntimeError("Backend returned empty probabilities/counts.")
    return normalize_distribution({str(k): float(out.get(k, 0.0)) for k in STATES})


def run_circuit_sim(engine, conf, circ) -> dict[str, float]:
    exe = compile_circuit(circ)
    res = engine.execute(exe, conf)
    return extract_distribution(res)


def run_circuit_nmr(engine, conf, circ, name: str) -> dict[str, float]:
    exe = compile_circuit(circ)

    last_err: Optional[Exception] = None
    for attempt in range(1, NMR_MAX_TRIES + 1):
        try:
            conf.configure_task(name, name)
            res = engine.execute(exe, conf)
            dist = extract_distribution(res)
            if COOLDOWN_S > 0:
                time.sleep(COOLDOWN_S)
            return dist
        except Exception as e:
            last_err = e
            sleep_s = NMR_BASE_SLEEP * (2 ** (attempt - 1))
            sleep_s *= 1.0 + random.uniform(-NMR_JITTER, NMR_JITTER)
            sleep_s = max(0.5, sleep_s)
            print(f"[NMR] attempt {attempt}/{NMR_MAX_TRIES} failed for '{name}': {e}")
            if attempt < NMR_MAX_TRIES:
                print(f"[NMR] sleeping {sleep_s:.2f}s then retrying...")
                time.sleep(sleep_s)

    raise RuntimeError(f"NMR job '{name}' failed after {NMR_MAX_TRIES} attempts. Last error: {last_err}")


def infer_order(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {r["test_name"]: r for r in rows}
    needed = ["x_q0", "x_q1", "x_q2"]

    if not all(name in by_name for name in needed):
        return {"reported_order": "undetermined", "reason": "Missing single-flip tests."}

    dom_q0 = clean_bitstring(by_name["x_q0"]["dominant_bitstring"]).zfill(3)
    dom_q1 = clean_bitstring(by_name["x_q1"]["dominant_bitstring"]).zfill(3)
    dom_q2 = clean_bitstring(by_name["x_q2"]["dominant_bitstring"]).zfill(3)

    if dom_q0 == "100" and dom_q1 == "010" and dom_q2 == "001":
        return {"reported_order": "q0q1q2", "reason": "Single-flip tests match q0q1q2 ordering."}

    if dom_q0 == "001" and dom_q1 == "010" and dom_q2 == "100":
        return {"reported_order": "q2q1q0", "reason": "Single-flip tests match q2q1q0 ordering."}

    return {
        "reported_order": "undetermined",
        "reason": (
            f"Observed single-flip dominant strings: "
            f"x_q0={dom_q0}, x_q1={dom_q1}, x_q2={dom_q2}. "
            "This does not match a pure q0q1q2 or q2q1q0 convention."
        ),
    }


def write_csv(path: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        with open(path, "w", encoding="utf-8", newline="") as f:
            pass
        return

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    ensure_dir(args.outdir)

    if args.probe_only:
        payload = probe_backend_api(args)
        print_probe(payload)
        out_json = os.path.join(args.outdir, f"probe_{args.backend}_{utc_stamp()}.json")
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"[OK] Wrote probe: {out_json}")
        return

    engine, conf = make_backend(args)

    rows: list[dict[str, Any]] = []
    full_payload: dict[str, Any] = {
        "backend": args.backend,
        "shots": args.shots,
        "timestamp_utc": utc_stamp(),
        "tests": [],
    }

    for case in TEST_CASES:
        circ = build_circuit(
            case["flips"],
            ensure_nmr_attrs=(args.backend == "triangulum"),
        )

        if args.backend == "sim":
            dist = run_circuit_sim(engine, conf, circ)
        else:
            dist = run_circuit_nmr(engine, conf, circ, name=f"{args.task_prefix}_{case['name']}")

        dom = dominant_bitstring(dist)
        expected_a = expected_bitstring_q0q1q2(case["flips"])
        expected_b = expected_bitstring_q2q1q0(case["flips"])

        row = {
            "test_name": case["name"],
            "flips": ",".join(str(q) for q in case["flips"]),
            "expected_if_q0q1q2": expected_a,
            "expected_if_q2q1q0": expected_b,
            "dominant_bitstring": clean_bitstring(dom),
            "shots": args.shots,
            "match_q0q1q2": clean_bitstring(dom).zfill(3) == expected_a,
            "match_q2q1q0": clean_bitstring(dom).zfill(3) == expected_b,
        }
        rows.append(row)

        full_payload["tests"].append(
            {
                "test_name": case["name"],
                "flips": case["flips"],
                "expected_if_q0q1q2": expected_a,
                "expected_if_q2q1q0": expected_b,
                "dominant_bitstring": clean_bitstring(dom),
                "distribution": dist,
            }
        )

    inference = infer_order(rows)
    full_payload["inference"] = inference

    stamp = utc_stamp()
    base = f"bit_order_{args.backend}_{stamp}"
    out_json = os.path.join(args.outdir, f"{base}.json")
    out_csv = os.path.join(args.outdir, f"{base}.csv")

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(full_payload, f, indent=2)

    write_csv(out_csv, rows)

    print("[OK] Wrote:")
    print(f"  {out_json}")
    print(f"  {out_csv}")
    print(f"[INFERENCE] reported_order={inference['reported_order']}")
    print(f"[DETAIL] {inference['reason']}")


if __name__ == "__main__":
    main()