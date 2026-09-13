#!/usr/bin/env python3
"""
coleta_carreiras.py — Provas e espelhos de concursos jurídicos das bancas abertas.

O que decide o acesso é a BANCA, não a carreira (lição do FONTES_REGISTRO.md e do
ANALISE_AGU.md, que já registravam isso):

  CEBRASPE  cdn.cebraspe.org.br/concursos/<slug>/arquivos/<ARQUIVO>.PDF  — aberto
  FGV       conhecimento.fgv.br/sites/default/files/concursos/<ARQUIVO>.pdf — aberto
  TJRJ      tjrj.jus.br/documents/...                                      — aberto
  VUNESP    bloqueada por Akamai (PGE-SP, MP-SP, TJSP)  — sem porta
  FCC       site acessível, provas não publicadas nas páginas de edital

A listagem de diretório do CDN responde 403, então o nome de cada arquivo vem de
busca indexada. Por isso a lista abaixo é explícita e cresce por acréscimo.

O espelho ("padrão de resposta" na CEBRASPE, "espelho de correção" na FGV) é o
artefato que interessa: é a régua da banca, com os pontos esperados por item.

Saída: data/carreiras/raw/ + data/carreiras/manifest.jsonl
"""
from __future__ import annotations

import argparse, json, re, ssl, subprocess, tempfile, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data/carreiras/raw"
MANIFEST = ROOT / "data/carreiras/manifest.jsonl"
H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124 Safari/537.36"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

CEB = "https://cdn.cebraspe.org.br/concursos/"
FGV = "https://conhecimento.fgv.br/sites/default/files/concursos/"

# (carreira, órgão, descrição, url)
ALVOS = [
    # ── Defensoria Pública da União — CEBRASPE
    ("defensoria", "DPU 2017", "prova dissertativa grupo III", CEB + "DPU_17_DEFENSOR/arquivos/ProvadissertativaGRUPOIII.pdf"),
    ("defensoria", "DPU 2017", "prova dissertativa grupo IV", CEB + "DPU_17_DEFENSOR/arquivos/ProvadissertativaGRUPOIV.pdf"),
    ("defensoria", "DPU 2017", "padrão de resposta definitivo grupo III", CEB + "DPU_17_DEFENSOR/arquivos/Padraoderespostadefinitivo_GRUPOIII_Dissertativa.pdf"),
    # ── Defensorias estaduais — CEBRASPE
    ("defensoria", "DPE-PA 2021", "padrão de resposta definitivo P3", CEB + "dpe_pa_21_defensor/arquivos/DPE_PA_21_DEFENSOR_PADRO_DE_RESPOSTA_DEFINITIVO_P3_COMPLETO.PDF"),
    ("defensoria", "DPE-RO 2022", "padrão de resposta definitivo P3", CEB + "dpe_ro_22_defensor/arquivos/DPE_RO_22_DEFENSOR_PADRO_DE_RESPOSTA_DEFINITIVO_P3.PDF"),
    ("defensoria", "DPE-RS 2021", "padrão de resposta preliminar", CEB + "dpe_rs_21_defensor/arquivos/ED_10_DPRS_2021_PADRO_PRELIMINAR_RESPOSTAS.PDF"),
    ("defensoria", "DPDF 2020", "padrão de resposta definitivo cargo 6", CEB + "dpdf_20_analista/arquivos/DPDF_20_ANALISTA_PADRO_DE_RESPOSTA_DEFINITIVO_CARGO_06.PDF"),
    # ── Procuradorias — CEBRASPE e FGV (a PGE-SP é VUNESP, bloqueada)
    ("procuradoria", "PGE-RO 2021", "prova com padrão de resposta", CEB + "pge_ro_21/arquivos/706_PGERO_001_COMPADRAO.PDF"),
    ("procuradoria", "Procurador (FGV)", "prova discursiva", FGV + "procurador-discursivacns101-tipo-1.pdf"),
    ("procuradoria", "Procurador municipal (FGV)", "espelho de correção discursiva", FGV + "espelho-correcao-discursiva-procurador.pdf"),
    # ── Defensoria — FGV
    ("defensoria", "DPE-PE (FGV)", "prova discursiva", FGV + "defensor-publicocns200-tipo-1.pdf"),
    ("defensoria", "DPE-RO (FGV)", "espelho de correção discursivas", FGV + "espelhodpe-ro.pdf"),
    # ── Magistratura — FGV (fora dos 8 tribunais do Magis-Bench? CONFERIR antes de treinar)
    ("magistratura", "TJPE 2025 (FGV)", "espelho de correção discursivas", FGV + "tjpe-2025-espelho-de-correcao-provas-discursivas-publicacao.pdf"),
    ("magistratura", "TJPE 2025 (FGV)", "espelho de correção sentenças", FGV + "tribunal-de-justica-do-estado-de-pernambuco-sentencas.pdf"),
    ("magistratura", "TJDFT 2022 (FGV)", "espelhos da prova discursiva", FGV + "tjdft2022_espelhos_v2.pdf"),
    ("magistratura", "TJRJ L (VUNESP, via TJRJ)", "espelho de correção discursiva", "https://www.tjrj.jus.br/documents/d/guest/espelho_de_correcao_da_prova_discursiva"),
    ("magistratura", "TJRJ L (VUNESP, via TJRJ)", "prova discursiva 06/04/2025", "https://www.tjrj.jus.br/documents/d/guest/prova_discursiva_aplicada_em_06-04-2025"),
    ("magistratura", "TJDFT XXXIX", "prova de sentença cível", "https://www.tjdft.jus.br/informacoes/concursos/juiz-de-direito-substituto/provas-objetivas-e-subjetivas-concursos-anteriores/ProvadesentenacvelXXXIXConcurso.pdf"),
    # ── Outras carreiras jurídicas com espelho (gênero útil p/ transferência)
    ("outras", "Delegado PC-SC 2024 (FGV)", "espelho de correção", FGV + "pcscdelegado2024_espelhodecorrecao.pdf"),
    ("outras", "ALMT (FGV)", "espelho de correção — peça", FGV + "almt_espelho_peca.pdf"),
    ("outras", "CDEP 2023 (FGV)", "espelhos da prova discursiva", FGV + "cdep-espelhos-edital-4.pdf"),
]


def texto(b: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b)
        tmp = f.name
    try:
        return subprocess.run(["pdftotext", "-nopgbrk", tmp, "-"],
                              capture_output=True, text=True, timeout=120).stdout
    finally:
        Path(tmp).unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Coleta provas e espelhos de carreiras jurídicas.")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    ja = set()
    if MANIFEST.exists():
        for l in MANIFEST.read_text("utf-8").splitlines():
            try:
                ja.add(json.loads(l)["url"])
            except Exception:
                pass

    trava = threading.Lock()
    linhas, ok, erro = [], 0, 0

    def um(alvo):
        nonlocal ok, erro
        carreira, orgao, desc, url = alvo
        if url in ja:
            return
        nome = re.sub(r"[^a-zA-Z0-9]+", "_", f"{carreira}_{orgao}_{desc}")[:80] + ".pdf"
        arq = DEST / nome
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=120, context=CTX).read()
            if not b.startswith(b"%PDF"):
                raise ValueError(f"não é PDF ({b[:12]!r})")
            t = texto(b)
            if len(t.strip()) < 800:
                raise ValueError(f"texto curto demais ({len(t.strip())} chars)")
            arq.write_bytes(b)
        except Exception as e:
            with trava:
                erro += 1
                print(f"  ✗ {orgao:26s} {desc[:34]:34s} {str(e)[:40]}")
            return
        with trava:
            ok += 1
            print(f"  ✓ {orgao:26s} {desc[:34]:34s} {len(b)/1024:6.0f} KB · {len(t):6d} chars")
            linhas.append({"carreira": carreira, "orgao": orgao, "descricao": desc, "url": url,
                           "caminho": str(arq), "n_chars_texto": len(t), "licenca": "obra_publica_gov"})

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(as_completed([pool.submit(um, a) for a in ALVOS]))

    if linhas:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        with open(MANIFEST, "a", encoding="utf-8") as f:
            for d in linhas:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"\n✓ {ok} baixados · {erro} falhas · manifest +{len(linhas)}")


if __name__ == "__main__":
    main()
