#scripts/00_check_function_affinity.py
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime, timezone
from typing import Sequence

from src.qae.quadrature import grid_points
from src.qae.state_prep import build_A_spec, exact_integral, is_affine_hardware_friendly

GFUNC_CHOICES = ["sin2_pi", "x", "x2", "sqrt_x", "exp_minus_x", "parabola"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Diagnose whether a target function is likely hardware-friendly on Triangulum "
            "by inspecting the 4-point angle table and its affine fit."
        )
    )
    p.add_argument(
        "--gfunc",
        type=str,
        default=None,
        choices=GFUNC_CHOICES,
        help="Named target function officially supported by the repo.",
    )
    p.add_argument(
        "--expr",
        type=str,
        default=None,
        help=(
            "Custom expression in variable x for exploratory affinity checks only, "
            "e.g. '4*x*(1-x)' or 'cos(pi*x)**2'."
        ),
    )
    p.add_argument("--y", type=float, default=1.0, help="Upper limit y in [0,1].")
    p.add_argument("--rule", type=str, default="midpoint", choices=["left", "right", "midpoint"])
    p.add_argument("--tol", type=float, default=1e-9, help="Tolerance for exact affine check.")
    p.add_argument(
        "--outdir",
        type=str,
        default="data/processed",
        help="Output directory for optional JSON/CSV diagnostic artifacts.",
    )
    p.add_argument(
        "--save",
        action="store_true",
        help="If set, save the diagnostic summary as JSON and CSV.",
    )
    args = p.parse_args()

    if (args.gfunc is None) == (args.expr is None):
        raise SystemExit("Provide exactly one of --gfunc or --expr.")

    return args


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_csv(rows: list[dict], out_csv: str) -> None:
    if not rows:
        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            pass
        return

    fieldnames = list(rows[0].keys())
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def current_utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _clip01(v: float) -> float:
    return min(max(v, 0.0), 1.0)


def g_value(x: float, gfunc: str) -> float:
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


def eval_expr(x: float, expr: str) -> float:
    allowed = {
        "x": x,
        "pi": math.pi,
        "e": math.e,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        "sqrt": math.sqrt,
        "exp": math.exp,
        "log": math.log,
        "log10": math.log10,
        "fabs": math.fabs,
        "abs": abs,
    }
    return float(eval(expr, {"__builtins__": {}}, allowed))


def theta_from_value(gx: float) -> float:
    gx = _clip01(gx)
    return 2.0 * math.asin(math.sqrt(gx))


def affine_fit_from_angles(t00: float, t01: float, t10: float, t11: float):
    c0 = t00
    c1 = t10 - t00
    c2 = t01 - t00
    t11_fit = c0 + c1 + c2
    residual = abs(t11_fit - t11)
    return c0, c1, c2, t11_fit, residual


def classify_affinity(residual: float, tol: float) -> str:
    if residual <= tol:
        return "hardware-friendly"
    if residual <= 1e-2:
        return "candidate (very close to affine)"
    if residual <= 5e-2:
        return "candidate (approximate affine compression may be possible)"
    return "simulation-ready / likely too deep for current Triangulum path"


def recommendation_from_classification(
    label: str,
    gfunc: str | None,
    expr: str | None,
    y: float,
    rule: str,
) -> str:
    if gfunc is not None:
        if label == "hardware-friendly":
            return (
                "Proceed to Triangulum test: "
                f"python -m scripts.02_run_mlae_triangulum --gfunc {gfunc} --y {y} "
                f"--rule {rule} --ks 0,1 --shots 1024 ..."
            )
        return (
            "Validate in simulation first: "
            f"python -m scripts.01_run_mlae_sim --gfunc {gfunc} --y {y} "
            f"--rule {rule} --ks 0,1,2 --shots 4096 --ancilla-bit-index-from-right 0"
        )

    if label == "hardware-friendly":
        return (
            "Exploratory result: the custom expression looks hardware-friendly on the 4-point grid. "
            "To run it in simulator or Triangulum, you must first add it as an official --gfunc in the repo."
        )

    return (
        "Exploratory result: validate the expression conceptually first. "
        "If it looks promising, add it as an official --gfunc before attempting execution in the main pipeline."
    )


def bit_patterns_for_two_qubits() -> Sequence[tuple[int, int]]:
    return [(0, 0), (0, 1), (1, 0), (1, 1)]


def main() -> None:
    args = parse_args()

    mode = "gfunc" if args.gfunc is not None else "expr"
    label_name = args.gfunc if args.gfunc is not None else args.expr

    grid = grid_points(y=args.y, n=2, rule=args.rule)

    # Official supported-function path
    if args.gfunc is not None:
        spec = build_A_spec(y=args.y, n_index_qubits=2, rule=args.rule, gfunc=args.gfunc)
        angle_map = {bits: theta for bits, theta in spec.patterns}
        exact_affine = is_affine_hardware_friendly(spec, tol=args.tol)
        exact_int = exact_integral(args.y, args.gfunc)
    else:
        # Exploratory custom-expression path
        angle_map = {}
        for i, bits in enumerate(bit_patterns_for_two_qubits()):
            x_i = grid.points[i]
            gx = _clip01(eval_expr(x_i, args.expr))
            angle_map[bits] = theta_from_value(gx)
        exact_affine = False  # determined from residual only below
        exact_int = None

    print("=" * 72)
    print("Triangulum function-affinity diagnostic")
    print("=" * 72)
    print(f"mode           : {mode}")
    print(f"target         : {label_name}")
    print(f"y              : {args.y}")
    print(f"rule           : {args.rule}")
    print(f"exact integral : {exact_int}")
    print()

    print("4-point quadrature grid")
    print("-" * 72)
    print(f"{'i':>2}  {'bits':>6}  {'x_i':>12}  {'g(x_i)':>12}  {'theta_i':>12}")
    print("-" * 72)

    detail_rows: list[dict] = []

    for i, bits in enumerate(bit_patterns_for_two_qubits()):
        x_i = grid.points[i]
        if args.gfunc is not None:
            gx = _clip01(g_value(x_i, args.gfunc))
        else:
            gx = _clip01(eval_expr(x_i, args.expr))
        theta_i = angle_map[bits]

        detail_rows.append(
            {
                "mode": mode,
                "gfunc": args.gfunc,
                "expr": args.expr,
                "y": args.y,
                "rule": args.rule,
                "i": i,
                "bits": str(bits),
                "x_i": x_i,
                "g_x_i": gx,
                "theta_i": theta_i,
            }
        )

        print(f"{i:>2}  {str(bits):>6}  {x_i:12.6f}  {gx:12.6f}  {theta_i:12.6f}")

    print()

    t00 = angle_map[(0, 0)]
    t01 = angle_map[(0, 1)]
    t10 = angle_map[(1, 0)]
    t11 = angle_map[(1, 1)]

    c0, c1, c2, t11_fit, residual = affine_fit_from_angles(t00, t01, t10, t11)

    if args.gfunc is None:
        exact_affine = residual <= args.tol

    label = classify_affinity(residual, args.tol)
    recommendation = recommendation_from_classification(label, args.gfunc, args.expr, args.y, args.rule)

    print("Affine-angle fit on the 2-qubit index grid")
    print("-" * 72)
    print(r"Model: theta(b0,b1) = c0 + c1*b0 + c2*b1")
    print(f"c0             : {c0:.12f}")
    print(f"c1             : {c1:.12f}")
    print(f"c2             : {c2:.12f}")
    print(f"theta(1,1)     : {t11:.12f}")
    print(f"theta_fit(1,1) : {t11_fit:.12f}")
    print(f"residual       : {residual:.12e}")
    print(f"exact affine   : {exact_affine}")
    print(f"classification : {label}")
    print()

    print("Interpretation")
    print("-" * 72)
    if exact_affine:
        print(
            "The angle table is exactly affine on the 4-point grid. "
            "This target is a strong candidate for direct Triangulum execution "
            "with the current compressed state-preparation path."
        )
    elif residual <= 1e-2:
        print(
            "The angle table is very close to affine. "
            "A shallow approximation may be possible, but this should be validated carefully."
        )
    elif residual <= 5e-2:
        print(
            "The angle table is only moderately close to affine. "
            "This may still be interesting for approximate compression studies, "
            "but direct hardware execution is uncertain."
        )
    else:
        print(
            "The angle table is not close to affine under the current criterion. "
            "This target is better treated as simulation-first under the present Triangulum constraints."
        )

    print()
    print("Recommendation")
    print("-" * 72)
    print(recommendation)

    summary = {
        "diagnostic_id": f"affinity_{mode}_{args.y:g}_{args.rule}_{current_utc_stamp()}",
        "mode": mode,
        "gfunc": args.gfunc,
        "expr": args.expr,
        "target_label": label_name,
        "y": args.y,
        "rule": args.rule,
        "exact_integral": exact_int,
        "c0": c0,
        "c1": c1,
        "c2": c2,
        "theta_11": t11,
        "theta_11_fit": t11_fit,
        "residual": residual,
        "exact_affine": exact_affine,
        "classification": label,
        "recommendation": recommendation,
    }

    if args.save:
        ensure_dir(args.outdir)
        stamp = current_utc_stamp()

        safe_name = (
            args.gfunc
            if args.gfunc is not None
            else "expr_" + "".join(ch if ch.isalnum() else "_" for ch in args.expr)[:40]
        )
        base = f"affinity_{safe_name}_y{args.y:g}_{args.rule}_{stamp}"

        out_json = os.path.join(args.outdir, f"{base}.json")
        out_csv_summary = os.path.join(args.outdir, f"{base}_summary.csv")
        out_csv_grid = os.path.join(args.outdir, f"{base}_grid.csv")

        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "grid_details": detail_rows}, f, indent=2)

        write_csv([summary], out_csv_summary)
        write_csv(detail_rows, out_csv_grid)

        print()
        print("[OK] Wrote:")
        print(f"  {out_json}")
        print(f"  {out_csv_summary}")
        print(f"  {out_csv_grid}")


if __name__ == "__main__":
    main()