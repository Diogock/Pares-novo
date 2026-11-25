"""Gera BDR/data/sample/ (sintético, versionado) para testes e rodada de exemplo.

Uso:
    python BDR/scripts/generate_sample.py
"""

from bdr_models.synthetic import generate

if __name__ == "__main__":
    files = generate("BDR/data/sample")
    print("\n".join(str(p) for p in files.values()))
