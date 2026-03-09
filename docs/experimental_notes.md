# Experiment Notes: MLAE-Style QAE Numerical Integration on SpinQ Triangulum (SpinQit)

## Purpose
These notes document the experimental design implemented in this repository: a Triangulum-compatible (3-qubit) realization of a hardware-oriented Quantum Amplitude Estimation (QAE) workflow for numerical integration, based on the efficient state-preparation strategy of Carrera Vazquez and Woerner.

The goal is to estimate an integral

$$
I(y)=\int_0^y g(x)\,dx,\qquad y\in[0,1],
$$

by encoding function values into an ancilla amplitude via a shallow operator $A$ and estimating the ancilla probability using a maximum-likelihood (MLAE-style) procedure.

Under the current implementation, the repository supports a broad class of bounded functions in simulation, but only a selective subset is presently executable on the SpinQ Triangulum hardware under the existing depth-constrained compression strategy.

---

## Hardware Mapping (Triangulum: 3 qubits)
We assume a 3-qubit register:

- **Index qubits**: $q_0,q_1$ represent $i\in\{0,1,2,3\}$, i.e. a uniform 4-point quadrature grid.
- **Ancilla qubit**: $q_2$ is measured; the event $q_2=1$ defines the “good” outcome.

The state-preparation operator $A$ is constructed so that

$$
a := \Pr(q_2=1 \text{ after } A|000\rangle)\approx \frac{1}{2^n}\sum_{i=0}^{2^n-1} g(x_i),
$$

and for a uniform grid on $[0,y]$ we use

$$
\widehat{I}(y) \approx y\cdot \hat a.
$$

---

## Discretization / Quadrature Rules
We discretize $[0,y]$ with $2^n$ points (Triangulum: typically $n=2$, i.e. 4 points). Sampling points $x_i$ are defined as:

- **Left rule**:
  $$
  x_i = y \cdot \frac{i}{2^n}
  $$
- **Right rule**:
  $$
  x_i = y \cdot \frac{i+1}{2^n}
  $$
- **Midpoint rule**:
  $$
  x_i = y \cdot \frac{i+\frac12}{2^n}
  $$

### Simpson-type postprocessing
To reduce quadrature bias without increasing qubit count, one may combine three independent estimates:

$$
\widehat{I}_S = \frac{\widehat{I}_{\text{left}} + 4\,\widehat{I}_{\text{mid}} + \widehat{I}_{\text{right}}}{6}.
$$

This requires three separate runs (`left`, `midpoint`, `right`), each with the same MLAE estimation pipeline.

---

## Integrand Families and Rotation Encoding

### Supported function families
At the current stage of development, the repository distinguishes clearly between:

- **officially supported functions** via `--gfunc`, used by the full simulator and hardware pipeline;
- **exploratory custom expressions** via `--expr`, used only in the affinity-diagnostic script.

The current named benchmark set includes:

- `sin2_pi`
- `x`
- `x2`
- `sqrt_x`
- `exp_minus_x`
- `parabola`

These functions are required to satisfy, at least after normalization if needed,

$$
0 \le g(x) \le 1 \qquad \text{for } x\in[0,1],
$$

so that they can be encoded as ancilla probabilities.

### Rotation encoding
For each quadrature point $x_i$ we define

$$
\theta_i = 2\arcsin\!\big(\sqrt{g(x_i)}\big),
$$

so that

$$
\sin^2\!\left(\frac{\theta_i}{2}\right)=g(x_i).
$$

Conditioned on the index state $|i\rangle$, we therefore apply $\mathrm{Ry}(\theta_i)$ to the ancilla.

### Default benchmark
The default benchmark integrand is

$$
g(x)=\sin^2(\pi x).
$$

In this case one may use the simplified encoding

$$
\theta_i = 2\pi x_i,
$$

since

$$
\sin^2\!\left(\frac{\theta_i}{2}\right)=\sin^2(\pi x_i).
$$

---

## State Preparation Operator $A$
For $n=2$ index qubits, $A$ has the form:

1. Apply Hadamards on index qubits:
   $$
   H^{\otimes 2} \text{ on } (q_0,q_1).
   $$
2. Apply rotations on the ancilla whose angles depend on the selected quadrature node.

### Original exact pattern-controlled construction
A straightforward implementation is:

- for each basis pattern $b\in\{0,1\}^2$,
- apply $X$ on those control qubits where $b_j=0$,
- apply a multi-controlled $\mathrm{Ry}(\theta_b)$ on the ancilla,
- undo the $X$ flips.

This is exact, but on Triangulum it often exceeds the hardware line-depth budget.

### Compressed affine-angle construction
The current hardware path therefore uses a compressed implementation whenever the angle table is affine on the 2-qubit grid.

If the four angles satisfy

$$
\theta(b_0,b_1)=c_0+c_1 b_0+c_2 b_1,
$$

then $A$ can be implemented using only:

- Hadamards on the index register,
- one single-qubit $R_y(c_0)$ on the ancilla,
- one singly controlled $R_y(c_1)$ from $q_0$ to the ancilla,
- one singly controlled $R_y(c_2)$ from $q_1$ to the ancilla.

This compressed form is the key to current hardware viability on Triangulum.

---

## Affine-Angle Criterion
For the four quadrature nodes associated with

$$
(b_0,b_1)\in\{(0,0),(0,1),(1,0),(1,1)\},
$$

let the corresponding angles be

$$
\theta_{00},\theta_{01},\theta_{10},\theta_{11}.
$$

The table is **exactly affine** if and only if

$$
\theta_{00}+\theta_{11}=\theta_{01}+\theta_{10}.
$$

Equivalently, if we define

$$
c_0=\theta_{00},\qquad
c_1=\theta_{10}-\theta_{00},\qquad
c_2=\theta_{01}-\theta_{00},
$$

then the affine prediction for the fourth corner is

$$
\theta_{11}^{\text{fit}} = c_0+c_1+c_2
= \theta_{10}+\theta_{01}-\theta_{00}.
$$

The code measures the **affine residual**

$$
r=\left|\theta_{11}-\theta_{11}^{\text{fit}}\right|
=\left|\theta_{11}-(\theta_{10}+\theta_{01}-\theta_{00})\right|.
$$

Interpretation:

- $r=0$ up to tolerance: exact affine structure, strong hardware candidate;
- small $r$: nearly affine, possible candidate for approximate compression;
- large $r$: simulation-first under the current Triangulum constraints.

### Empirical classification under the current implementation
Current tests support the following practical classification:

- **hardware-friendly**: `sin2_pi`, `x`
- **simulation-ready**: `x2`, `parabola`
- **simulation-first**: `exp_minus_x`

This classification is empirical and specific to the present 3-qubit Triangulum implementation.

---

## Amplitude Amplification and the $Q$ Operator
We define “good” states as those with ancilla $|1\rangle$. The standard amplitude amplification operator is

$$
Q = A\,S_0\,A^\dagger\,S_{\psi_0},
$$

where:

- $S_{\psi_0}$ marks good states:
  - implemented as $Z$ on the ancilla $q_2$.
- $S_0$ is the reflection about $|000\rangle$:
  $$
  S_0 = I - 2|000\rangle\langle 000|.
  $$

### Practical construction of $S_0$ on 3 qubits
A convenient construction is:

1. Apply $X$ on all qubits.
2. Apply $\mathrm{CCZ}$ on $(q_0,q_1,q_2)$.
3. Apply $X$ on all qubits.

With 3 qubits, $\mathrm{CCZ}$ can be realized using a Toffoli (`CCX`) and Hadamards on the target:

$$
\mathrm{CCZ}(q_0,q_1,q_2) = H(q_2)\,\mathrm{CCX}(q_0,q_1\to q_2)\,H(q_2).
$$

---

## MLAE-Style Estimation (No QPE)
To reduce depth and improve robustness on NMR hardware, we avoid QPE-based QAE and instead use an MLAE-style likelihood fit.

For amplification indices $k\in\mathcal{K}$ we prepare

$$
|\psi_k\rangle = Q^k A|000\rangle,
$$

measure the ancilla, and estimate

$$
p_k = \Pr(q_2=1\mid k).
$$

Under the ideal model,

$$
p_k(a)=\sin^2\!\big((2k+1)\theta\big),\qquad \theta=\arcsin(\sqrt{a}).
$$

Given observed successes $m_k$ out of $N_k$ shots, we compute

$$
\hat a=\arg\max_{a\in[0,1]}\sum_{k\in\mathcal{K}}
\Big[m_k\log p_k(a)+(N_k-m_k)\log(1-p_k(a))\Big].
$$

### Recommended settings for Triangulum
Under the current depth-constrained implementation:

- $n=2$ (4 grid points, 2 index qubits),
- $\mathcal{K}=\{0,1\}$ for direct hardware runs,
- start with $y=1$ and a hardware-friendly function such as `sin2_pi` or `x`.

For simulation, larger or less hardware-friendly function classes can still be explored with

- $\mathcal{K}=\{0,1,2\}$,
- broader function families,
- and explicit comparison against both the exact integral and the quadrature reference.

---

## Diagnostic Script for Hardware Screening
The repository includes the script

- `scripts/00_check_function_affinity.py`

which should be run before attempting a new function on Triangulum.

### Official named-function mode
Example:

```powershell
python -m scripts.00_check_function_affinity --gfunc x --y 1.0 --rule midpoint
```

### Exploratory custom-expression mode
The script can also screen a custom expression via `--expr`, for example:

```powershell
python -m scripts.00_check_function_affinity --expr "cos(pi*x)**2" --y 1.0 --rule midpoint
```

This exploratory mode is intended **only for affinity diagnostics**. It does **not** imply that the full simulator or Triangulum pipeline can execute that function automatically.

To use a promising custom expression in the full workflow, it should first be added officially as a supported `--gfunc` in:

- `src/qae/state_prep.py`
- `scripts/01_run_mlae_sim.py`
- `scripts/02_run_mlae_triangulum.py`
- `scripts/04_run_triangulum_campaign.py`

### Saved diagnostic artifacts
With `--save`, the diagnostic script produces:

- a JSON summary,
- a one-row CSV summary,
- and a grid-level CSV file.

This turns function-affinity screening into a reproducible part of the experimental pipeline.

---

## Bitstring Ordering (Important Practical Note)
SpinQit backends may return measurement outcomes with differing endianness conventions. This affects which bit corresponds to the ancilla in the returned bitstring counts.

The scripts expose an option:

- `--ancilla-bit-index-from-right`

where `0` means “rightmost bit”, `1` means “second from right”, etc.

### Current practical defaults
Under the current implementation:

- **simulator**: the working default is `--ancilla-bit-index-from-right 0`
- **Triangulum NMR backend**: the current working default is `--ancilla-bit-index-from-right 2`

### Suggested calibration
Run a simple circuit that flips only the ancilla and confirm which bit toggles in the returned counts. If results look inconsistent, recalibrate the ancilla bit ordering explicitly.

---

## Output Files and Interpretation
Each run produces structured outputs that may include:

- backend configuration (simulator / NMR),
- parameters $y$, `gfunc`, rule, $\mathcal{K}$, shots,
- raw counts per $k$,
- estimated $\hat a$ and $\widehat{I}(y)$,
- exact integral when available,
- hardware-affinity metadata under the current Triangulum path.

The summarization script consolidates raw JSON runs into:

- `data/processed/summary_runs.csv` (one row per run),
- `data/processed/summary_by_k.csv` (one row per run and per $k$).

The affinity diagnostic can additionally save:

- `affinity_... .json`
- `affinity_... _summary.csv`
- `affinity_... _grid.csv`

for reproducible screening of candidate functions.

---

## Current Experimental Status
Under the present implementation, the following has been observed:

- `sin2_pi`: validated in simulator and on Triangulum,
- `x`: validated in simulator and on Triangulum,
- `x2`: validated in simulator, rejected by Triangulum depth limit,
- `parabola`: validated in simulator, rejected by Triangulum depth limit,
- `exp_minus_x`: validated in simulator, currently treated as simulation-first.

This supports the methodological distinction between:

- **simulation-generalizable** function support,
- and **hardware-selective** execution under current Triangulum constraints.

---

## Reference
Carrera Vazquez, A., and Woerner, S.  
*Efficient State Preparation for Quantum Amplitude Estimation*.  
arXiv:2005.07711 (quant-ph), 2020.
