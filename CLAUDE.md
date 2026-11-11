# Radar de Vagas

Plataforma pessoal (uso de uma pessoa, roda no PC Windows do dono) para encontrar vagas de tecnologia no Brasil,
ordená-las por afinidade com o perfil dele e acompanhar as candidaturas. **Não automatiza a candidatura**: o
usuário abre o link e se candidata manualmente. Toda a interface, os textos e os nomes no código são em português.

## Comandos

```powershell
iniciar.bat                          # cria .venv, instala dependências se requirements.txt mudou, abre o app
.venv\Scripts\python -m radar        # app em http://127.0.0.1:8765
.venv\Scripts\python -m radar coletar | avaliar | refiltrar
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest       # testes (provedores de IA e sites sempre simulados)
.venv\Scripts\ruff check .
```

## Arquitetura

- `radar/coletores/` — um arquivo por fonte, cada um devolve `list[VagaColetada]` (`radar/modelos.py`).
  `gupy.py` usa `https://portal.gupy.io/api/job-search/jobs` (endpoint interno do portal; o antigo
  `portal.api.gupy.io/api/v1/jobs` morreu em out/2026). `jobspy_coletor.py` usa a lib python-jobspy
  (Indeed, Glassdoor, LinkedIn, sem login).
- `radar/pipeline.py` — roda coletores, deduplica (`normalizacao.chave_dedup`: empresa+título+cidade), aplica
  o filtro de regras (`filtros.py` + regras aprovadas no banco via `sugestoes.filtros_efetivos`).
- `radar/afinidade.py` — score 0–100 por IA, segunda opinião de outro provedor nas melhores, plano do dia
  (tela Hoje: afinidade × frescor ÷ esforço^0.25, enche o tempo disponível).
- `radar/ia/` — clientes HTTP puros (sem SDK) para Anthropic (Messages API), OpenAI (Responses API) e Gemini
  (generateContent); `servico.py` roteia por tarefa (`score`, `segunda_opiniao`, `escrita`) com fallback,
  limite diário e registro de uso na tabela `uso_ia`. Prompts em `prompts.py`.
- `radar/acoes.py` — CV adaptado e textos (Gupy, resposta de formulário, mensagem, entrevista).
  `montar_cv` valida a proposta do modelo contra o `perfil.yaml`: bullet sem id válido é removido; reescrita
  que cite tecnologia (catálogo) ou número ausente no original volta ao texto original; todas as experiências
  aparecem. `documentos.py` gera DOCX (python-docx) e PDF (reportlab), uma coluna.
- `radar/db.py` — SQLite em `dados/radar.db`, sem ORM. `_migrar` adiciona colunas novas em bancos antigos:
  ao criar coluna nova, registre em `COLUNAS_NOVAS`.
- `radar/web/` — Starlette + Jinja2, HTML renderizado no servidor, formulários POST + redirect com `?msg=`.
  Chamadas de IA nas rotas vão por `run_in_threadpool` para não travar o servidor.
- `radar/agendador.py` — thread que coleta a cada N horas e depois roda a afinidade.

## Arquivos do usuário (fora do Git)

- `config.yaml` (a partir de `config.example.yaml`): buscas, filtros, modelos e ordem dos provedores de IA.
- `perfil.yaml`: perfil mestre com dados pessoais; é a única fonte de fatos para a IA. Nunca commitar.
- `.env`: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. Nunca commitar nem imprimir.
- `dados/`: banco, log e CVs gerados.

## Regras do projeto

- Nunca usar login do usuário em sites de vagas (LinkedIn proíbe scraping no contrato; risco de restrição de conta).
- A IA nunca inventa experiência: qualquer geração passa pelo perfil mestre e, no caso do CV, pelo validador.
- Nada de texto oculto ou truques para ATS.
- Uma fonte com erro não pode derrubar as outras; erros aparecem na tela Início (coletas) ou Ajustes (IA).
- Dependências novas: adicionar em `requirements.txt` (o `iniciar.bat` reinstala sozinho quando o arquivo muda).

## Roadmap

1. ✅ Coleta, deduplicação, filtro de regras, quadro de candidaturas.
2. ✅ Perfil mestre, afinidade com IA, tela Hoje, feedback, CV adaptado e textos.
3. Ler e-mails de atualização (Gmail API, só leitura, etiqueta "Vagas"), classificar com IA, sugerir mudança de
   status, prazos e lembretes; alertas de vaga do LinkedIn como fonte.
4. Monitorar empresas-alvo (Greenhouse, Lever, Gupy por subdomínio via
   `private-api.gupy.io/job-publication/public/jobs?subdomain=`), mudanças em páginas de carreira,
   posts "contratando" via API de busca (só o link), Adzuna.
