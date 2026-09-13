#!/usr/bin/env python3
"""congela.py — fixa um depósito: inventário, soma de verificação e manifesto.

O manifesto é o que transforma "os dados estão no repositório" em "estes bytes exatos
produziram estes resultados". Sem ele, um depósito com DOI ainda não garante que o arquivo
baixado é o arquivo usado; com ele, qualquer pessoa confere em um comando.

    python dataset/congela.py                 # todos os depósitos
    python dataset/congela.py corpus-treino   # um só
    python dataset/congela.py --conferir      # revalida contra o manifesto gravado
"""
from __future__ import annotations

import hashlib, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from depositos import DEPOSITOS, arquivos, RAIZ

MANI = Path(__file__).resolve().parent / "manifestos"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for pedaco in iter(lambda: f.read(1 << 20), b""):
            h.update(pedaco)
    return h.hexdigest()


def linhas(p: Path) -> int | None:
    """Conta linhas só de .jsonl — é a unidade de registro desses arquivos."""
    if p.suffix != ".jsonl":
        return None
    n = 0
    with p.open("rb") as f:
        for pedaco in iter(lambda: f.read(1 << 20), b""):
            n += pedaco.count(b"\n")
    return n


def congela(dep: str) -> dict:
    itens = arquivos(dep)
    if not itens:
        raise SystemExit(f"depósito '{dep}' não encontrou nenhum arquivo")
    reg, total = [], 0
    for i, (destino, p) in enumerate(itens, 1):
        tam = p.stat().st_size
        total += tam
        reg.append({"caminho": destino, "origem": str(p.relative_to(RAIZ)),
                    "bytes": tam, "linhas": linhas(p), "sha256": sha256(p)})
        if i % 50 == 0:
            print(f"    {i}/{len(itens)}…", flush=True)
    m = {**{k: v for k, v in DEPOSITOS[dep].items() if k != "itens"},
         "deposito": dep, "congelado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
         "arquivos": len(reg), "bytes": total, "itens": reg}
    MANI.mkdir(parents=True, exist_ok=True)
    (MANI / f"{dep}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), "utf-8")
    return m


def confere(dep: str) -> int:
    f = MANI / f"{dep}.json"
    if not f.exists():
        print(f"  {dep}: sem manifesto"); return 1
    m = json.loads(f.read_text("utf-8"))
    ruim = 0
    for it in m["itens"]:
        p = RAIZ / it["origem"]
        if not p.exists():
            print(f"  FALTA    {it['origem']}"); ruim += 1
        elif sha256(p) != it["sha256"]:
            print(f"  MUDOU    {it['origem']}"); ruim += 1
    print(f"  {dep}: {m['arquivos']} arquivos · {ruim or 'nenhuma'} divergência"
          f"{'s' if ruim > 1 else ''}")
    return ruim


if __name__ == "__main__":
    alvos = [a for a in sys.argv[1:] if not a.startswith("--")] or list(DEPOSITOS)
    if "--conferir" in sys.argv:
        raise SystemExit(1 if sum(confere(d) for d in alvos) else 0)
    for d in alvos:
        print(f"  congelando {d}…", flush=True)
        m = congela(d)
        print(f"  {d:20s} {m['arquivos']:5d} arquivos · {m['bytes']/1e9:6.2f} GB")
