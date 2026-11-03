"""Erstellt die zwei Ergebnisabbildungen fuer Kapitel 5.4.

Datei neben activity_overlap.py in bears/streamlit_app legen und starten:
    python export_abbildungen_5_4_aktuell.py

Erwartet die aktualisierte Kamera-Eintrittszaehlung in activity_overlap.py.
Nur lesender Zugriff auf Datenbank und vorhandene Simulationsdateien.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import activity_overlap as ao


def main():
    print("Kapitel 5.4: 300 Laeufe, 48 h, 100 m, KDE 1,5 h, Seed 42, Gelaende AUS.", flush=True)
    print("Berechnung gestartet. Das kann einige Minuten dauern ...", flush=True)
    result = ao.compute_comparison(
        n_runs=300,
        hours_per_run=48,
        detection_radius_m=100,
        bandwidth=1.5,
        n_boot=1000,
        use_terrain=False,
        seed=42,
    )
    if not result["db_ok"] or result["delta"] is None:
        raise RuntimeError("Keine gueltige Auswertung: Verbindung zur MariaDB und Kameradaten pruefen.")

    n_real, n_sim = result["n_real"], result["n_sim"]
    delta = result["delta"]
    low, high = result["ci_low"], result["ci_high"]
    print(f"Reale Fotozeitpunkte: {n_real}", flush=True)
    print(f"Virtuelle Kameraeintritte: {n_sim}", flush=True)
    print(f"Delta: {delta:.6f}", flush=True)
    print(f"95%-Bootstrap-Intervall: [{low:.6f}; {high:.6f}]", flush=True)

    # Veraltete Statistiken sollen nicht unbemerkt die Abschlussabbildungen ersetzen.
    if (n_real, n_sim) != (50, 247) or abs(delta - 0.5539343654333979) > 0.002:
        raise RuntimeError(
            "Die Ergebnisse stimmen nicht mit dem geprueften Referenzlauf "
            "(50 reale, 247 virtuelle, Delta ca. 0,554) ueberein. "
            "Abbildungen nicht geschrieben; bitte zuerst die Ursache pruefen."
        )

    grid = result["grid"]
    real, sim = result["f_real"], result["f_sim"]
    fig, ax = plt.subplots(figsize=(9, 4.9))
    ax.axvspan(0, 6, alpha=0.06, color="grey", label="Nacht (18–6 Uhr)")
    ax.axvspan(18, 24, alpha=0.06, color="grey")
    ax.plot(grid, real, linewidth=2.2, label=f"Reale Kameraaufnahmen (n={n_real})")
    ax.plot(grid, sim, linewidth=2.2, label=f"Virtuelle Kameraeintritte (n={n_sim})")
    ax.fill_between(grid, np.minimum(real, sim), alpha=0.20, color="grey", label=f"Überlappung (Δ={delta:.3f})")
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2))
    ax.set_xlabel("Tageszeit (Uhr)")
    ax.set_ylabel("Geschätzte Dichte")
    ax.set_title("Zeitliche Verteilung realer und virtueller Kameraereignisse")
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    out_dir = Path(__file__).resolve().parent
    dest = out_dir / "ergebnis-kamerazeiten-kde.pdf"
    fig.savefig(dest, bbox_inches="tight")
    plt.close(fig)
    print(f"Gespeichert: {dest}", flush=True)

    bootstrap = np.asarray(result["boot_deltas"])
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.hist(bootstrap, bins=35, edgecolor="white")
    ax.axvline(delta, linewidth=2.1, color="black", label=f"Ergebnis: Δ={delta:.3f}")
    ax.axvline(low, linestyle="--", linewidth=1.8, color="firebrick", label=f"95%-Bootstrap-Intervall [{low:.3f}; {high:.3f}]")
    ax.axvline(high, linestyle="--", linewidth=1.8, color="firebrick")
    ax.set_xlabel("Überlappungskoeffizient Δ")
    ax.set_ylabel("Häufigkeit")
    ax.set_title("Verteilung aus 1.000 Bootstrap-Wiederholungen")
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    dest = out_dir / "ergebnis-kamerazeiten-bootstrap.pdf"
    fig.savefig(dest, bbox_inches="tight")
    plt.close(fig)
    print(f"Gespeichert: {dest}", flush=True)
    print("Fertig. Beide Diagramme basieren auf demselben Rechenlauf.")


if __name__ == "__main__":
    main()
