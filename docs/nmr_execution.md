# NMR Execution Manual (Triangulum / SpinQit)

This manual describes how to execute the MLAE-style QAE experiment in this repository on the **SpinQ Triangulum (3-qubit NMR QPU)**, following the same operational philosophy as the Grover–Rudolph practical repository: **scripts-first execution**, explicit backend configuration, and structured outputs in `data/`.

Although the main target of this manual is **hardware execution on Triangulum**, the recommended workflow now also includes:

- `scripts/00_check_function_affinity.py` for pre-screening functions under the current depth-constrained hardware assumptions,
- `scripts/01_run_mlae_sim.py` for simulator validation before sending a new function or configuration to hardware.

---

## 1. Prerequisites

### 1.1 System requirements
- Python 3.10+ recommended
- Network access (LAN/VPN) to the Triangulum device
- SpinQit installed and functional

### 1.2 Repository layout (relevant parts)
- `scripts/00_check_function_affinity.py`: diagnostic script to screen whether a function is a plausible hardware candidate
- `scripts/01_run_mlae_sim.py`: simulator validation entrypoint
- `scripts/02_run_mlae_triangulum.py`: main Triangulum execution entrypoint
- `scripts/03_summarize_results.py`: merges raw JSON runs into CSV summaries
- `scripts/04_run_triangulum_campaign.py`: optional three-rule campaign launcher
- `data/raw/`: raw results (JSON + per-run CSV)
- `data/processed/`: aggregated summaries
- `src/backends/nmr_triangulum.py`: backend wrapper (`NMRConfig` + engine call)

---

## 2. Environment Setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows PowerShell
pip install -U pip
pip install -r requirements.txt
```

Sanity check:

```bash
python -c "import spinqit; print('spinqit ok')"
```

---

## 3. Connectivity Check (Triangulum Port 55444)

Before running any experiment, verify that the device is reachable:

```bash
nc -vz -w 2 <TRIANGULUM_IP> 55444
```

Expected output: `succeeded`.

If this fails:

- verify you are on the correct LAN/VPN,
- verify routing (for example with `netstat -nr`),
- confirm the port is correct (default is `55444`),
- check local firewall rules.

---

## 4. Pre-Screening and Simulator Validation

Under the current implementation, **not every function that works in simulation is suitable for Triangulum hardware**. The limiting factor is the line-depth budget and, more specifically, whether the 4-point angle table is affine on the 2-qubit index grid.

### 4.1 Affinity diagnostic
Before launching hardware for a new function, run:

```bash
python -m scripts.00_check_function_affinity --gfunc sin2_pi --y 1.0 --rule midpoint
```

or, for another supported function,

```bash
python -m scripts.00_check_function_affinity --gfunc x --y 1.0 --rule midpoint
```

The script can also be used in exploratory mode:

```bash
python -m scripts.00_check_function_affinity --expr "cos(pi*x)**2" --y 1.0 --rule midpoint
```

This exploratory mode is intended only for screening. It does **not** imply that the full simulator or Triangulum execution pipeline can run that function automatically.

### 4.2 Simulator validation
Before sending a new hardware-oriented configuration to Triangulum, validate it in the simulator:

```bash
python -m scripts.01_run_mlae_sim \
  --gfunc sin2_pi \
  --y 1.0 \
  --rule midpoint \
  --ks 0,1,2 \
  --shots 4096 \
  --ancilla-bit-index-from-right 0 \
  --outdir data/raw
```

Under the current implementation, the simulator working default is:

```text
--ancilla-bit-index-from-right 0
```

### 4.3 Current practical classification
Based on the current implementation and tests:

- **hardware-friendly**: `sin2_pi`, `x`
- **simulation-ready**: `x2`, `parabola`
- **simulation-first**: `exp_minus_x`, `sqrt_x`

Only hardware-friendly functions should be sent to Triangulum directly under the present depth-constrained path.

---

## 5. Running on Triangulum (Main Command)

### 5.1 Minimal recommended run (baseline)

This is the reference configuration intended to work under typical hardware constraints:

- discretization: 2 index qubits (4 points)
- ancilla: 1 qubit
- amplification indices: $k = \{0,1\}$
- rule: `midpoint`
- `gfunc`: start with `sin2_pi` or `x`
- `y`: 1.0

```bash
python -m scripts.02_run_mlae_triangulum \
  --ip <TRIANGULUM_IP> \
  --port 55444 \
  --account <USER> \
  --password <PASSWORD> \
  --task-name qae_mlae_demo \
  --task-desc "MLAE-style QAE numerical integration (Triangulum)" \
  --gfunc sin2_pi \
  --y 1.0 \
  --rule midpoint \
  --ks 0,1 \
  --shots 1024 \
  --ancilla-bit-index-from-right 2 \
  --outdir data/raw
```

On success the script prints:

- the locations of the written files,
- the estimated amplitude `a_hat`,
- the estimated integral `I_hat`,
- and, when available, the exact integral.

### 5.2 Output artifacts

Each run generates two files under `data/raw/`:

1. `triangulum_....json`  
   Contains:
   - backend metadata (`ip`, `port`, task),
   - experiment parameters (`gfunc`, `y`, `rule`, `ks`, shots),
   - raw bitstring counts for each $k$,
   - MLE estimate `a_hat` and derived `I_hat`,
   - exact integral when available,
   - hardware-affinity metadata.

2. `triangulum_....csv`  
   Flat per-$k$ summary (one row per $k$) to facilitate quick plots.

---

## 6. Important Practical Issue: Bitstring Ordering

SpinQit backends may return measurement strings with different endianness conventions. This affects which bit corresponds to the ancilla.

The scripts expose:

- `--ancilla-bit-index-from-right`

Interpretation:

- `0` = rightmost bit
- `1` = second from right
- `2` = third from right (common working default for Triangulum with ancilla as qubit 2)

### 6.1 Quick calibration procedure

If you suspect the extracted probabilities are incorrect (for example `p_hat` always near 0 or 1), run the same command with three settings:

```bash
python -m scripts.02_run_mlae_triangulum ... --ancilla-bit-index-from-right 0
python -m scripts.02_run_mlae_triangulum ... --ancilla-bit-index-from-right 1
python -m scripts.02_run_mlae_triangulum ... --ancilla-bit-index-from-right 2
```

Choose the setting that yields sensible `p_hat` values and coherent variation across $k$.

---

## 7. Recommended Experimental Workflow (Triangulum)

### 7.1 Step 1 — Hardware screening

Run the affinity diagnostic first:

```bash
python -m scripts.00_check_function_affinity --gfunc sin2_pi --y 1.0 --rule midpoint
```

If the function is not classified as hardware-friendly, do **not** send it directly to Triangulum under the present implementation.

### 7.2 Step 2 — Simulator validation

Validate the configuration in simulation:

```bash
python -m scripts.01_run_mlae_sim \
  --gfunc sin2_pi \
  --y 1.0 \
  --rule midpoint \
  --ks 0,1,2 \
  --shots 4096 \
  --ancilla-bit-index-from-right 0 \
  --outdir data/raw
```

For `x`, an equally relevant simulator validation is:

```bash
python -m scripts.01_run_mlae_sim \
  --gfunc x \
  --y 1.0 \
  --rule midpoint \
  --ks 0,1,2 \
  --shots 4096 \
  --ancilla-bit-index-from-right 0 \
  --outdir data/raw
```

### 7.3 Step 3 — Baseline hardware functionality

Start shallow and conservative:

- `--ks 0,1`
- `--shots 1024`

```bash
python -m scripts.02_run_mlae_triangulum \
  --ip <TRIANGULUM_IP> --port 55444 --account <USER> --password <PASSWORD> \
  --gfunc sin2_pi --y 1.0 --rule midpoint --ks 0,1 --shots 1024 \
  --ancilla-bit-index-from-right 2 --outdir data/raw
```

If this works reliably, you may increase the shot budget. Under the current depth-constrained implementation, moving to `ks = {0,1,2}` is not generally recommended for direct hardware runs.

### 7.4 Step 4 — Validation points

Use values where the exact integral is known.

For `sin2_pi`:

- `y = 1.0` gives exact $I(1)=1/2$
- `y = 0.5` gives exact $I(1/2)=1/4$

For `x`:

- `y = 1.0` gives exact $I(1)=1/2$

Note: with only 4 grid points, quadrature bias may be visible; compare both against:

- the exact integral, and
- the corresponding quadrature reference (left / right / midpoint).

### 7.5 Step 5 — Optional Simpson improvement (3 runs)

Run three variants:

- `--rule left`
- `--rule midpoint`
- `--rule right`

Then combine classically:

$$
I_S = \frac{I_{\text{left}} + 4 I_{\text{mid}} + I_{\text{right}}}{6}.
$$

A campaign script is available:

```bash
python -m scripts.04_run_triangulum_campaign \
  --ip <TRIANGULUM_IP> --port 55444 --account <USER> --password <PASSWORD> \
  --gfunc sin2_pi --y 1.0 --ks 0,1 --shots 1024
```

To recompute the campaign summary without relaunching hardware:

```bash
python -m scripts.04_run_triangulum_campaign \
  --ip <TRIANGULUM_IP> --port 55444 --account <USER> --password <PASSWORD> \
  --gfunc sin2_pi --y 1.0 --ks 0,1 --shots 1024 --reuse-existing
```

---

## 8. Aggregating Results

To merge all raw JSON runs into two CSV summary files:

```bash
python -m scripts.03_summarize_results --indir data/raw --outdir data/processed
```

Outputs:

- `data/processed/summary_runs.csv` (one row per run)
- `data/processed/summary_by_k.csv` (one row per run × per $k$)

These summaries retain metadata such as:

- `gfunc`
- exact integral (when available)
- absolute error
- hardware-affinity classification under the current Triangulum path

---

## 9. Troubleshooting

### 9.1 Connection errors

Symptoms:

- timeouts
- refused connection
- backend exceptions
- transient messages such as `invalid state`

Actions:

- re-check `nc -vz <IP> 55444`
- ensure VPN/LAN is active
- verify correct IP and credentials

### 9.2 `Line depth exceeds limit:60`

This indicates that the current circuit exceeds the Triangulum hardware budget.

Actions:

- run `scripts/00_check_function_affinity.py` first,
- validate in simulation with `scripts/01_run_mlae_sim.py`,
- restrict hardware tests to functions classified as hardware-friendly,
- keep `--ks 0,1`,
- do not assume that a function working in simulation is hardware-compatible.

At the current stage, direct tests indicate:

- `sin2_pi`: works
- `x`: works
- `x2`: exceeds depth limit
- `parabola`: exceeds depth limit
- `sqrt_x`: exceeds depth limit

### 9.3 Counts look degenerate (all 0 or all 1)

Actions:

- re-check `--ancilla-bit-index-from-right` (Section 6)
- reduce depth: use `--ks 0,1`
- reduce shots initially (some backends have hidden limits)
- confirm Triangulum calibration status (T1/T2, temperature stability)

### 9.4 Backend API mismatch

If SpinQit version differs, you may need to adapt:

- `src/backends/nmr_triangulum.py::TriangulumBackend.run()`
- `src/backends/simulator.py::SimulatorBackend.run()`

The wrappers are intentionally isolated so you only modify backend invocation / return parsing in one place.

---

## 10. Reproducibility Checklist (Before Reporting Results)

Record:

- SpinQit version
- backend type and NMR task name
- full command line used
- `data/raw/*.json` produced
- affinity diagnostic output when testing a new function
- simulator validation output from `scripts/01_run_mlae_sim.py`

Run:

- at least 3 repeated trials for the same configuration to assess variability

Keep:

- `summary_runs.csv`
- `summary_by_k.csv`
- any `affinity_*.json` / `affinity_*_summary.csv` / `affinity_*_grid.csv` files used to justify hardware screening
