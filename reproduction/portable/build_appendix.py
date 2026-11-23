"""Build machine-readable appendix B tables and figure B1 from the five-cohort results."""

import argparse
import csv
import json
from pathlib import Path

COHORTS = {
    "D0": ("DSH historical", "E5 0.2.0-rc.2", "DeepSeek V4.1 Flash"),
    "D1": ("DSH", "0.2.2-rc.3", "MiMo 2.6 Flash"),
    "D2": ("DSH", "0.2.2-rc.3", "GLM 5.3 Flash"),
    "P1": ("Pi", "1.5.2", "DeepSeek V4.1 Flash"),
    "H1": ("Hermes", "0.23.2", "DeepSeek V4.1 Flash"),
}
BASELINES = ("B0", "B1", "B2a", "B2b", "B3")
ABLATIONS = ("A1", "A2", "A3", "A4", "A5", "A6", "sham")


def write_table(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        output = csv.writer(handle)
        output.writerow(columns)
        output.writerows(rows)


def source_tables(result, out):
    e1, e3, e4, e5 = (result[k] for k in ("e1", "e3", "e4", "e5"))
    ordinary, compound = e4["ordinary"], e4["compound"]
    e3a, e3b = (e3["fixture"][k] for k in ("S-A", "S-B"))
    write_table(out / "B3-cohorts.csv", ["cohort", "harness", "version", "model", "scoring_units"],
                [(g, *settings, 2475) for g, settings in COHORTS.items()])
    b4, b5, b6, b7 = [], [], [], []
    for g in COHORTS:
        sfa = e3["within"][g]["sfa_difference"]
        mc = e3["within"][g]["mcnemar"]
        a = e3a["metrics"][g]["metrics"]
        b = e3b["metrics"][g]["metrics"]
        b4.append((g, 192, 24, a["sfa"]["median"], b["sfa"]["median"], sfa["point"],
                   *sfa["bootstrap_95"], a["pass_rate"]["median"], b["pass_rate"]["median"],
                   mc["p_exact_two_sided"], a["slr"]["median"], b["slr"]["median"]))
        for arm in BASELINES:
            b5.append((g, arm, e5["arms"][g][arm], 168, e5["tool_calls"][g][arm]["mean"]))
        for arm in ABLATIONS:
            b6.append((g, arm, e5["arms"][g][arm], 168))
        b7.append((g, e1["estimates"][g], sum(x["disposal_ok"] for x in ordinary["rounds"][g].values()), 105,
                   sum(x["n_pass"] for x in ordinary["rounds"][g].values()),
                   sum(x["n_scored"] for x in ordinary["rounds"][g].values()),
                   sum(x["disposal_ok"] for x in compound["rounds"][g].values()), 54))
    write_table(out / "B4-offline-E3.csv",
                ["cohort", "offline_answers", "online_answers", "SFA_A", "SFA_B", "SFA_delta",
                 "SFA_ci95_low", "SFA_ci95_high", "strict_pass_A", "strict_pass_B",
                 "strict_pass_mcnemar_p", "SLR_A", "SLR_B"], b4)
    write_table(out / "B5-E5-baselines.csv", ["cohort", "arm", "success", "n", "mean_tool_calls"], b5)
    write_table(out / "B6-E5-ablations.csv", ["cohort", "arm", "success", "n"], b6)
    write_table(out / "B7-E1-E4.csv",
                ["cohort", "E1_weighted", "E4_ordinary_correct", "E4_ordinary_n", "E4_weighted_pass",
                 "E4_weighted_n", "E4_compound_correct", "E4_compound_n"], b7)
    endpoints = (
        ("E1 weighted", e1), ("E3 offline S-A SFA", e3a), ("E3 offline S-B SFA", e3b),
        ("E4 ordinary disposition", ordinary), ("E5 B3 success", e5["cross_b3"]),
    )
    b8 = [(endpoint, c["left"], c["right"], c["n_tasks"], c["delta"], *c["ci95"], c["p_holm"])
          for endpoint, section in endpoints for c in section["contrasts"] if c["p_holm"] is not None]
    write_table(out / "B8-paired-contrasts.csv",
                ["endpoint", "left", "right", "paired_tasks", "delta", "ci95_low", "ci95_high", "holm_p"], b8)
    overview = [
        [e1["estimates"][g], e3a["estimates"][g], e3b["estimates"][g],
         ordinary["estimates"][g], e5["arms"][g]["B3"] / 168] for g in COHORTS
    ]
    ablations = [[e5["arms"][g][a] / 168 for a in (*BASELINES, *ABLATIONS)] for g in COHORTS]
    headers = ("E1 weighted", "E3 S-A SFA", "E3 S-B SFA", "E4 ordinary", "E5 B3")
    write_table(out / "B1-overview.csv", ["cohort", *headers], [(g, *v) for g, v in zip(COHORTS, overview)])
    write_table(out / "B1-E5-all-arms.csv", ["cohort", *BASELINES, *ABLATIONS],
                [(g, *v) for g, v in zip(COHORTS, ablations)])
    return overview, headers, ablations


def figure(out, overview, headers, ablations):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    labels = [f"{harness} / {model}" for harness, _, model in COHORTS.values()]
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 9, "svg.fonttype": "none"}):
        fig, axes = plt.subplots(2, 1, figsize=(12.1, 7.0), layout="constrained")
        panels = (
            ("A   Main outcomes", overview, headers),
            ("B   E5 success by configuration", ablations, (*BASELINES, *ABLATIONS)),
        )
        for ax, (heading, matrix, cols) in zip(axes, panels, strict=True):
            img = ax.imshow(matrix, cmap="viridis", vmin=0, vmax=1, aspect="auto")
            ax.set_title(heading, loc="left", fontweight="bold")
            ax.set_xticks(range(len(cols)), labels=cols)
            ax.set_yticks(range(len(labels)), labels=labels)
            ax.tick_params(axis="both", length=0)
            for row, values in enumerate(matrix):
                for col, value in enumerate(values):
                    ax.text(col, row, f"{value:.1%}", ha="center", va="center",
                            color="#111827" if value > 0.55 else "white", fontsize=8.5)
            for spine in ax.spines.values():
                spine.set_visible(False)
        bar = fig.colorbar(img, ax=axes, fraction=0.035, pad=0.025)
        ticks = [0, 0.25, 0.5, 0.75, 1]
        bar.set_ticks(ticks, labels=[f"{n:.0%}" for n in ticks])
        for suffix in ("svg", "pdf", "png"):
            fig.savefig(out / f"figure-B1.{suffix}", dpi=240)
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("five-group-results.json"))
    parser.add_argument("--output", type=Path, default=Path("appendix-B"))
    args = parser.parse_args()
    data = json.loads(args.results.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    figure(args.output, *source_tables(data, args.output))
    print(f"Wrote tables B3–B8 and figure B1 to {args.output}")


if __name__ == "__main__":
    main()
