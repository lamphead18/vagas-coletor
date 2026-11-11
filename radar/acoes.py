"""Ações de escrita sob demanda: CV adaptado (validado contra o perfil), texto Gupy, respostas, mensagem, entrevista."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import db
from . import perfil as perfil_mod
from .afinidade import vaga_para_prompt
from .ia import prompts
from .ia.servico import ServicoIA
from .normalizacao import normalizar

# Tecnologias comuns: se o texto reescrito citar uma destas e o bullet original não, a reescrita é descartada.
CATALOGO_TECNOLOGIAS = [
    "python", "java", "javascript", "typescript", "node", "node.js", "nestjs", "express", "react",
    "react native", "next.js", "angular", "vue", "svelte", "flutter", "dart", "kotlin", "swift", "go", "golang",
    "rust", "php", "laravel", "django", "flask", "fastapi", "spring", "spring boot", "ruby", "rails",
    "postgresql", "postgres", "mysql", "mariadb", "mongodb", "redis", "sqlite", "oracle", "sql server",
    "dynamodb", "elasticsearch", "cassandra", "kafka", "rabbitmq", "sqs", "aws", "azure", "gcp", "google cloud",
    "docker", "kubernetes", "k8s", "terraform", "ansible", "jenkins", "github actions", "gitlab ci", "graphql",
    "grpc", "websocket", "microsserviços", "microservices", "serverless", "lambda", "firebase", "supabase",
    "prisma", "typeorm", "sequelize", "drizzle", "knex", "tailwind", "material ui", "chakra", "redux", "zustand",
    "riverpod", "bloc", "jest", "vitest", "cypress", "playwright", "selenium", "pytest", "junit", "scrum",
    "kanban", "figma", "storybook", "webpack", "vite", "nginx", "linux", "power bi", "tableau", "spark",
    "airflow", "dbt", "pandas", "numpy", "tensorflow", "pytorch", "langchain", "llm", "rag",
]
TERMOS_TECNOLOGIA = sorted({normalizar(t) for t in CATALOGO_TECNOLOGIAS}, key=len, reverse=True)
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _contem(texto_norm: str, termo_norm: str) -> bool:
    return bool(termo_norm) and f" {termo_norm} " in f" {texto_norm} "


def _tecnologias(texto: str) -> set[str]:
    alvo = normalizar(texto)
    return {t for t in TERMOS_TECNOLOGIA if _contem(alvo, t)}


def _numeros(texto: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", texto or ""))


def reescrita_segura(original: str, reescrito: str) -> tuple[bool, str | None]:
    """A reescrita não pode trazer tecnologia nem número que o bullet original não tem."""
    novas = _tecnologias(reescrito) - _tecnologias(original)
    # "node" dentro de "node js" do original conta como presente
    original_norm = normalizar(original)
    novas = {t for t in novas if not _contem(original_norm, t)}
    if novas:
        return False, f"citou {', '.join(sorted(novas))}, que não está no original"
    numeros = _numeros(reescrito) - _numeros(original)
    if numeros:
        return False, f"trouxe números que não estão no original ({', '.join(sorted(numeros))})"
    return True, None


def periodo(inicio: Any, fim: Any) -> str:
    def formatar(valor: Any) -> str:
        texto = str(valor or "").strip()
        if texto.lower() in ("atual", "em andamento", "presente"):
            return texto.capitalize()
        partes = texto.split("-")
        if len(partes) >= 2 and partes[0].isdigit() and partes[1].isdigit():
            return f"{MESES[int(partes[1]) - 1]}/{partes[0]}"
        return texto
    return f"{formatar(inicio)} – {formatar(fim)}"


def cobertura(palavras: list[str], texto: str, texto_perfil: str) -> dict[str, Any]:
    """Quantas palavras-chave da vaga aparecem no CV; as que faltam são separadas em 'tem no perfil' e 'não tem'."""
    if not palavras:
        return {"percentual": None, "faltando_no_cv": [], "faltando_no_perfil": []}
    alvo = normalizar(texto)
    presentes, fora_do_cv, fora_do_perfil = [], [], []
    for palavra in palavras:
        termo = normalizar(palavra)
        tokens = [t for t in termo.split() if len(t) > 2] or termo.split()
        if _contem(alvo, termo) or (tokens and all(_contem(alvo, t) for t in tokens)):
            presentes.append(palavra)
        elif _contem(texto_perfil, termo) or (tokens and all(_contem(texto_perfil, t) for t in tokens)):
            fora_do_cv.append(palavra)
        else:
            fora_do_perfil.append(palavra)
    return {
        "percentual": round(100 * len(presentes) / len(palavras)),
        "faltando_no_cv": fora_do_cv,
        "faltando_no_perfil": fora_do_perfil,
    }


def montar_cv(perfil: dict[str, Any], proposta: dict[str, Any], palavras_chave: list[str]) -> dict[str, Any]:
    """Valida a proposta do modelo contra o perfil e monta o CV final. O que não confere é descartado."""
    indice = perfil_mod.bullets_por_id(perfil)
    avisos: list[str] = []
    skills_perfil = {normalizar(s): s for s in perfil_mod.todas_skills(perfil)}

    skills = []
    for skill in proposta.get("skills") or []:
        original = skills_perfil.get(normalizar(str(skill)))
        if original and original not in skills:
            skills.append(original)
        elif not original:
            avisos.append(f"Skill \"{skill}\" removida: não está no perfil.")
    if not skills:
        skills = perfil_mod.todas_skills(perfil)[:18]

    def bullets_validados(item_id: str, sugeridos: Any) -> list[str]:
        textos = []
        for b in sugeridos or []:
            if not isinstance(b, dict):
                continue
            bid = str(b.get("id") or "")
            referencia = indice.get(bid)
            if referencia is None or referencia["dono"] != item_id:
                avisos.append(f"Trecho sem origem no perfil foi removido ({bid or 'sem id'}).")
                continue
            texto = " ".join(str(b.get("texto") or "").split())
            seguro, motivo = reescrita_segura(referencia["texto"], texto) if texto else (False, "veio vazio")
            if not seguro:
                avisos.append(f"Bullet {bid}: reescrita descartada ({motivo}); usei o texto original.")
                texto = referencia["texto"]
            if texto not in textos:
                textos.append(texto)
        return textos

    sugestoes_exp = {str(e.get("id")): e for e in proposta.get("experiencias") or [] if isinstance(e, dict)}
    experiencias = []
    for item in perfil["experiencias"]:  # ordem e lista completa vêm do perfil, não do modelo
        textos = bullets_validados(str(item["id"]), (sugestoes_exp.get(str(item["id"])) or {}).get("bullets"))
        if not textos:
            textos = [b["texto"] for b in (item.get("bullets") or [])[:2]]
            avisos.append(f"{item['empresa']}: o modelo não escolheu bullets; usei os dois primeiros do perfil.")
        experiencias.append({
            "empresa": item["empresa"], "cargo": item["cargo"],
            "periodo": periodo(item.get("inicio"), item.get("fim")), "bullets": textos,
        })

    projetos_perfil = {str(p["id"]): p for p in perfil["projetos"]}
    projetos = []
    for sugestao in proposta.get("projetos") or []:
        if not isinstance(sugestao, dict):
            continue
        item = projetos_perfil.get(str(sugestao.get("id")))
        if item is None:
            continue
        textos = bullets_validados(str(item["id"]), sugestao.get("bullets"))
        if textos:
            projetos.append({"nome": item["nome"], "link": item.get("link") or "",
                             "stack": item.get("stack") or [], "bullets": textos})

    alvos = perfil["objetivo"].get("cargos_alvo") or []
    titulo = str(proposta.get("titulo") or "").strip()
    if alvos and normalizar(titulo) not in {normalizar(a) for a in alvos}:
        titulo = alvos[0]

    cv = {
        "pessoal": perfil.get("pessoal") or {},
        "titulo": titulo,
        "resumo": " ".join(str(proposta.get("resumo") or perfil.get("resumo") or "").split()),
        "skills": skills[:18],
        "experiencias": experiencias,
        "projetos": projetos[:3],
        "formacao": [
            {"curso": f.get("curso"), "instituicao": f.get("instituicao"),
             "periodo": periodo(f.get("inicio"), f.get("fim"))}
            for f in perfil.get("formacao") or []
        ],
        "idiomas": perfil.get("idiomas") or [],
        "observacoes": str(proposta.get("observacoes") or "").strip(),
        "avisos": avisos,
    }
    cv["cobertura"] = cobertura(palavras_chave, texto_do_cv(cv), perfil_mod.texto_completo(perfil))
    return cv


def texto_do_cv(cv: dict[str, Any]) -> str:
    partes = [cv["titulo"], cv["resumo"], " ".join(cv["skills"])]
    for item in cv["experiencias"] + cv["projetos"]:
        partes += item["bullets"] + [" ".join(item.get("stack") or [])]
    return " ".join(partes)


# ---------- execução ----------

def _contexto(conexao, vaga_id: int) -> tuple[Any, dict[str, Any]]:
    vaga = db.obter_vaga(conexao, vaga_id)
    if vaga is None:
        raise ValueError("vaga não encontrada")
    analise = json.loads(vaga["score_dados"] or "{}")
    return vaga, analise


def _usuario(perfil: dict[str, Any], vaga: Any, analise: dict[str, Any], extra: str = "", com_ids: bool = False) -> str:
    partes = [f"PERFIL DO CANDIDATO:\n{perfil_mod.para_prompt(perfil, com_ids=com_ids)}",
              f"VAGA:\n{vaga_para_prompt(vaga)}"]
    if analise:
        partes.append(
            "ANÁLISE DE AFINIDADE:\n"
            f"Atende: {', '.join(analise.get('requisitos_atendidos') or [])}\n"
            f"Falta: {', '.join(analise.get('requisitos_faltando') or [])}\n"
            f"Palavras-chave da vaga: {', '.join(analise.get('palavras_chave') or [])}"
        )
    if extra:
        partes.append(extra)
    return "\n\n".join(partes)


def gerar_cv(config: dict[str, Any], vaga_id: int, servico: ServicoIA | None = None,
             perfil: dict[str, Any] | None = None, caminho: Path | None = None,
             pasta_saida: Path | None = None) -> int:
    from . import documentos

    perfil = perfil or perfil_mod.carregar()
    servico = servico or ServicoIA(config, caminho)
    with db.conectar(caminho) as conexao:
        vaga, analise = _contexto(conexao, vaga_id)
    resultado = servico.gerar_json("escrita", prompts.CV_SISTEMA,
                                   _usuario(perfil, vaga, analise, com_ids=True), max_tokens=4000)
    cv = montar_cv(perfil, resultado.dados, analise.get("palavras_chave") or [])
    arquivos = documentos.salvar(cv, vaga, pasta_saida)
    with db.conectar(caminho) as conexao:
        return db.salvar_versao_cv(
            conexao, vaga_id, json.dumps(cv, ensure_ascii=False), str(arquivos["docx"]), str(arquivos["pdf"]),
            cv["cobertura"]["percentual"], resultado.provedor, resultado.modelo,
        )


ACOES_TEXTO = {
    "gupy": ("Texto para perfil Gupy", prompts.GUPY_SISTEMA, 2500),
    "resposta": ("Resposta de formulário", prompts.RESPOSTA_SISTEMA, 1200),
    "mensagem": ("Mensagem para recrutador", prompts.MENSAGEM_SISTEMA, 800),
    "entrevista": ("Preparação para entrevista", prompts.ENTREVISTA_SISTEMA, 3500),
}


def gerar_texto(config: dict[str, Any], vaga_id: int, tipo: str, entrada: str = "",
                servico: ServicoIA | None = None, perfil: dict[str, Any] | None = None,
                caminho: Path | None = None) -> int:
    if tipo not in ACOES_TEXTO:
        raise ValueError(f"ação desconhecida: {tipo}")
    _, sistema, max_tokens = ACOES_TEXTO[tipo]
    perfil = perfil or perfil_mod.carregar()
    servico = servico or ServicoIA(config, caminho)
    with db.conectar(caminho) as conexao:
        vaga, analise = _contexto(conexao, vaga_id)
    extra = ""
    if tipo == "resposta":
        extra = f"PERGUNTA DO FORMULÁRIO:\n{entrada}"
    elif tipo == "mensagem" and entrada:
        extra = f"CONTEXTO (quem vai receber, link do post etc.):\n{entrada}"
    resultado = servico.gerar_json("escrita", sistema, _usuario(perfil, vaga, analise, extra), max_tokens)
    with db.conectar(caminho) as conexao:
        return db.salvar_geracao(conexao, vaga_id, tipo, entrada or None,
                                 json.dumps(resultado.dados, ensure_ascii=False), resultado.provedor, resultado.modelo)
