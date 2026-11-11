"""Gera o CV adaptado em DOCX e PDF: uma coluna, títulos padrão e texto selecionável (bom para ATS)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .config import PASTA_DADOS
from .normalizacao import sem_acentos

PASTA_CVS = PASTA_DADOS / "cvs"


def _slug(texto: str | None) -> str:
    texto = sem_acentos(texto or "").lower()
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:40] or "vaga"


def _contato(pessoal: dict[str, Any]) -> list[str]:
    linha1 = " | ".join(x for x in [pessoal.get("cidade"), pessoal.get("email"), pessoal.get("telefone")] if x)
    linha2 = " | ".join(x for x in [pessoal.get("linkedin"), pessoal.get("github")] if x)
    return [linha for linha in (linha1, linha2) if linha]


def _idiomas(cv: dict[str, Any]) -> list[str]:
    return [f"{i.get('idioma')}: {i.get('nivel')}" for i in cv.get("idiomas") or [] if i.get("idioma")]


def gerar_docx(cv: dict[str, Any], caminho: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    documento = Document()
    for secao in documento.sections:
        secao.top_margin = secao.bottom_margin = Cm(1.6)
        secao.left_margin = secao.right_margin = Cm(1.8)
    estilo: Any = documento.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(10.5)
    estilo.paragraph_format.space_after = Pt(2)

    def titulo_secao(texto: str) -> None:
        paragrafo = documento.add_paragraph()
        paragrafo.paragraph_format.space_before = Pt(10)
        paragrafo.paragraph_format.space_after = Pt(4)
        execucao = paragrafo.add_run(texto)
        execucao.bold = True
        execucao.font.size = Pt(12)

    nome = documento.add_paragraph()
    execucao = nome.add_run(cv["pessoal"].get("nome") or "")
    execucao.bold = True
    execucao.font.size = Pt(18)
    nome.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if cv.get("titulo"):
        cargo = documento.add_paragraph()
        cargo.add_run(cv["titulo"]).font.size = Pt(12)
    for linha in _contato(cv["pessoal"]):
        documento.add_paragraph(linha)

    titulo_secao("Resumo Profissional")
    documento.add_paragraph(cv["resumo"])

    titulo_secao("Competências Técnicas")
    documento.add_paragraph(", ".join(cv["skills"]))

    titulo_secao("Experiência Profissional")
    for item in cv["experiencias"]:
        paragrafo = documento.add_paragraph()
        paragrafo.paragraph_format.space_before = Pt(6)
        paragrafo.add_run(f"{item['cargo']} — {item['empresa']}").bold = True
        documento.add_paragraph(item["periodo"])
        for bullet in item["bullets"]:
            documento.add_paragraph(bullet, style="List Bullet")

    if cv["projetos"]:
        titulo_secao("Projetos")
        for item in cv["projetos"]:
            paragrafo = documento.add_paragraph()
            paragrafo.paragraph_format.space_before = Pt(6)
            paragrafo.add_run(item["nome"]).bold = True
            for bullet in item["bullets"]:
                documento.add_paragraph(bullet, style="List Bullet")
            detalhes = []
            if item.get("stack"):
                detalhes.append("Stack: " + ", ".join(item["stack"]))
            if item.get("link"):
                detalhes.append("Link: " + item["link"])
            if detalhes:
                documento.add_paragraph(" | ".join(detalhes))

    if cv["formacao"]:
        titulo_secao("Formação Acadêmica")
        for f in cv["formacao"]:
            paragrafo = documento.add_paragraph()
            paragrafo.add_run(f"{f['curso']} — {f['instituicao']}").bold = True
            documento.add_paragraph(f["periodo"])

    idiomas = _idiomas(cv)
    if idiomas:
        titulo_secao("Idiomas")
        documento.add_paragraph(" | ".join(idiomas))

    documento.core_properties.author = cv["pessoal"].get("nome") or ""
    documento.core_properties.title = f"Currículo — {cv['pessoal'].get('nome') or ''}"
    documento.save(str(caminho))


def gerar_pdf(cv: dict[str, Any], caminho: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

    normal = ParagraphStyle("normal", fontName="Helvetica", fontSize=10, leading=13.5, spaceAfter=2)
    negrito = ParagraphStyle("negrito", parent=normal, fontName="Helvetica-Bold", spaceBefore=6)
    secao = ParagraphStyle("secao", parent=normal, fontName="Helvetica-Bold", fontSize=12, leading=15,
                           spaceBefore=10, spaceAfter=4)
    nome = ParagraphStyle("nome", parent=normal, fontName="Helvetica-Bold", fontSize=18, leading=22)
    cargo = ParagraphStyle("cargo", parent=normal, fontSize=12, leading=15, spaceAfter=4)

    def p(texto: str, estilo: ParagraphStyle = normal) -> Paragraph:
        return Paragraph(escape(texto or ""), estilo)

    def lista(itens: list[str]) -> ListFlowable:
        itens_lista: list[Any] = [ListItem(p(i), leftIndent=12) for i in itens]
        return ListFlowable(itens_lista, bulletType="bullet",
                            start="•", leftIndent=12, bulletFontSize=9)

    historia: list[Any] = [p(cv["pessoal"].get("nome") or "", nome)]
    if cv.get("titulo"):
        historia.append(p(cv["titulo"], cargo))
    historia += [p(linha) for linha in _contato(cv["pessoal"])]
    historia += [p("Resumo Profissional", secao), p(cv["resumo"])]
    historia += [p("Competências Técnicas", secao), p(", ".join(cv["skills"]))]
    historia.append(p("Experiência Profissional", secao))
    for item in cv["experiencias"]:
        historia += [p(f"{item['cargo']} — {item['empresa']}", negrito), p(item["periodo"]), lista(item["bullets"])]
    if cv["projetos"]:
        historia.append(p("Projetos", secao))
        for item in cv["projetos"]:
            historia += [p(item["nome"], negrito), lista(item["bullets"])]
            detalhes = []
            if item.get("stack"):
                detalhes.append("Stack: " + ", ".join(item["stack"]))
            if item.get("link"):
                detalhes.append("Link: " + item["link"])
            if detalhes:
                historia.append(p(" | ".join(detalhes)))
    if cv["formacao"]:
        historia.append(p("Formação Acadêmica", secao))
        for f in cv["formacao"]:
            historia += [p(f"{f['curso']} — {f['instituicao']}", negrito), p(f["periodo"])]
    idiomas = _idiomas(cv)
    if idiomas:
        historia += [p("Idiomas", secao), p(" | ".join(idiomas))]
    historia.append(Spacer(1, 4))

    documento = SimpleDocTemplate(
        str(caminho), pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm,
        bottomMargin=1.6 * cm, title=f"Currículo — {cv['pessoal'].get('nome') or ''}",
        author=cv["pessoal"].get("nome") or "",
    )
    documento.build(historia)


def salvar(cv: dict[str, Any], vaga: Any, pasta: Path | None = None) -> dict[str, Path]:
    pasta = pasta or PASTA_CVS
    pasta.mkdir(parents=True, exist_ok=True)
    base = f"{vaga['id']}-{_slug(vaga['empresa'])}-{datetime.now():%Y%m%d-%H%M%S}"
    docx, pdf = pasta / f"{base}.docx", pasta / f"{base}.pdf"
    gerar_docx(cv, docx)
    gerar_pdf(cv, pdf)
    return {"docx": docx, "pdf": pdf}


def nome_para_download(cv_nome: str | None, empresa: str | None, extensao: str) -> str:
    nome = "-".join(p.capitalize() for p in _slug(cv_nome or "curriculo").split("-"))
    return f"Curriculo-{nome}-{_slug(empresa).capitalize() or 'Vaga'}.{extensao}"
