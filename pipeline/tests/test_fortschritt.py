"""Fortschrittsbalken: liefert eine tqdm-kompatible Schnittstelle, die bei
nicht-interaktiver Ausgabe still bleibt (Docker/Logdatei)."""
from lernpaket_pipeline.fortschritt import _StillerBalken, balken


def test_stiller_balken_ist_noop_und_context():
    b = _StillerBalken()
    with b as ctx:
        ctx.update(5)
        ctx.update()
    b.close()  # darf nicht werfen


def test_balken_gibt_nutzbare_schnittstelle(capsys):
    # In der Test-Umgebung ist stderr kein TTY → tqdm deaktiviert sich (kein Output).
    b = balken(total=3, desc="Test", unit="Seite")
    b.update(1)
    b.update(2)
    b.close()
    assert capsys.readouterr().err == ""  # keine \r-Artefakte ohne TTY
