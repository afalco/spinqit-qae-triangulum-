# calibrate_bit_order.py
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from typing import Any


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

    # Triangulum-only params
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


def normalize_counts(result: Any) -> dict[str, int]:
    if isinstance(result, dict):
        return {str(k): int(v) for k, v in result.items()}
    if hasattr(result, "counts"):
        return {str(k): int(v) for k, v in result.counts.items()}
    if hasattr(result, "get_counts"):
        c = result.get_counts()
        return {str(k): int(v) for k, v in c.items()}
    raise RuntimeError("Unsupported backend result type for counts extraction.")


def clean_bitstring(s: str) -> str:
    return s.replace("0b", "").strip()


def dominant_bitstring(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def expected_bitstring_q0q1q2(flips: list[int]) -> str:
    bits = ["0", "0", "0"]
    for q in flips:
        bits[q] = "1"
    return "".join(bits)


def expected_bitstring_q2q1q0(flips: list[int]) -> str:
    return expected_bitstring_q0q1q2(flips)[::-1]


def build_circuit(flips: list[int]):
    from spinqit import Circuit, X  # type: ignore

    circ = Circuit()
    try:
        circ.allocateQubits(3)
    except Exception:
        pass

    for q in flips:
        circ << (X, q)

    try:
        circ.measure_all()
    except Exception:
        try:
            circ.measure(range(3))
        except Exception:
            pass

    return circ


def make_backend(args: argparse.Namespace):
    if args.backend == "sim":
        from spinqit import get_basic_simulator  # type: ignore
        return get_basic_simulator(), None

    from spinqit import get_nmr, NMRConfig  # type: ignore

    if not args.ip or not args.account or not args.password:
        raise SystemExit("For --backend triangulum you must provide --ip, --account, and --password.")

    engine = get_nmr()
    conf = NMRConfig()
    conf.configure_ip(args.ip)
    conf.configure_port(int(args.port))
    conf.configure_account(args.account, args.password)
    conf.configure_task(args.task_prefix, "3-qubit bit-order calibration")
    return engine, conf


def public_attrs(obj: Any) -> list[str]:
    return [name for name in dir(obj) if not name.startswith("_")]


def probe_backend_api(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {"backend": args.backend}

    if args.backend == "sim":
        from spinqit import get_basic_simulator  # type: ignore

        engine = get_basic_simulator()
        payload["engine_type"] = str(type(engine))
        payload["engine_public_attrs"] = public_attrs(engine)

        try:
            from spinqit import get_compiler  # type: ignore

            compiler = get_compiler()
            payload["compiler_type"] = str(type(compiler))
            payload["compiler_public_attrs"] = public_attrs(compiler)
        except Exception as e:
            payload["compiler_probe_error"] = repr(e)

        try:
            from spinqit import get_basic_simulator_config  # type: ignore

            cfg = get_basic_simulator_config()
            payload["sim_config_type"] = str(type(cfg))
            payload["sim_config_public_attrs"] = public_attrs(cfg)
        except Exception as e:
            payload["sim_config_probe_error"] = repr(e)

    else:
        from spinqit import get_nmr, NMRConfig  # type: ignore

        engine = get_nmr()
        payload["engine_type"] = str(type(engine))
        payload["engine_public_attrs"] = public_attrs(engine)

        conf = NMRConfig()
        payload["config_type"] = str(type(conf))
        payload["config_public_attrs"] = public_attrs(conf)

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

    for key in ("compiler_probe_error", "sim_config_probe_error"):
        if key in payload:
            print(f"{key}: {payload[key]}")


def run_circuit(engine, conf, circ, shots: int):
    if conf is None:
        errors: list[str] = []

        # 1) direct execute(circ, shots=...)
        try:
            return engine.execute(circ, shots=shots)
        except Exception as e:
            errors.append(f"engine.execute(circ, shots=shots): {repr(e)}")

        # 2) direct execute(circ, shots)
        try:
            return engine.execute(circ, shots)
        except Exception as e:
            errors.append(f"engine.execute(circ, shots): {repr(e)}")

        # 3) direct execute(circ)
        try:
            return engine.execute(circ)
        except Exception as e:
            errors.append(f"engine.execute(circ): {repr(e)}")

        # 4) compile + execute(compiled, ...)
        try:
            from spinqit import get_compiler  # type: ignore

            compiler = get_compiler()
            compile_errors: list[str] = []

            compiled = None
            for label, call in [
                ("compiler.compile(circ, 0)", lambda: compiler.compile(circ, 0)),
                ("compiler.compile(circ)", lambda: compiler.compile(circ)),
            ]:
                try:
                    compiled = call()
                    break
                except Exception as e:
                    compile_errors.append(f"{label}: {repr(e)}")

            if compiled is None:
                errors.extend(compile_errors)
            else:
                for label, call in [
                    ("engine.execute(compiled, shots=shots)", lambda: engine.execute(compiled, shots=shots)),
                    ("engine.execute(compiled, shots)", lambda: engine.execute(compiled, shots)),
                    ("engine.execute(compiled)", lambda: engine.execute(compiled)),
                ]:
                    try:
                        return call()
                    except Exception as e:
                        errors.append(f"{label}: {repr(e)}")

                # 5) compiled + simulator config if available
                try:
                    from spinqit import get_basic_simulator_config  # type: ignore

                    cfg = get_basic_simulator_config()
                    for setter_name in ("configure_shots", "set_shots"):
                        if hasattr(cfg, setter_name):
                            try:
                                getattr(cfg, setter_name)(shots)
                            except Exception as e:
                                errors.append(f"{setter_name}(shots): {repr(e)}")

                    for label, call in [
                        ("engine.execute(compiled, cfg)", lambda: engine.execute(compiled, cfg)),
                        ("engine.execute(compiled, cfg, shots)", lambda: engine.execute(compiled, cfg, shots)),
                        ("engine.execute(compiled, cfg, shots=shots)", lambda: engine.execute(compiled, cfg, shots=shots)),
                    ]:
                        try:
                            return call()
                        except Exception as e:
                            errors.append(f"{label}: {repr(e)}")

                except Exception as e:
                    errors.append(f"get_basic_simulator_config(): {repr(e)}")

        except Exception as e:
            errors.append(f"get_compiler(): {repr(e)}")

        msg = (
            "Could not execute circuit on simulator backend.\n"
            "Tried the following call patterns:\n- "
            + "\n- ".join(errors)
            + "\n\nRun again with --probe-only to inspect the backend API."
        )
        raise RuntimeError(msg)

    else:
        try:
            return engine.execute(circ, conf, shots=shots)
        except Exception:
            try:
                return engine.run(circ, conf, shots=shots)
            except Exception as e:
                raise RuntimeError("Could not execute circuit on Triangulum backend.") from e


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

    try:
        for case in TEST_CASES:
            circ = build_circuit(case["flips"])
            result = run_circuit(engine, conf, circ, shots=args.shots)
            counts = normalize_counts(result)
            dom = dominant_bitstring(counts)

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
                    "counts": counts,
                }
            )
    except RuntimeError as e:
        if args.backend == "sim":
            probe = probe_backend_api(args)
            full_payload["probe_on_failure"] = probe
            print(str(e))
            print()
            print_probe(probe)

            out_json = os.path.join(args.outdir, f"bit_order_failure_probe_{args.backend}_{utc_stamp()}.json")
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(full_payload, f, indent=2)
            print(f"[OK] Wrote failure probe: {out_json}")
        raise

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