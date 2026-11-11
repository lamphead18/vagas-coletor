# Radar de Vagas

Junta as vagas da Gupy, do Indeed, do Glassdoor e do LinkedIn num lugar só, sem duplicatas, filtradas pelas suas regras. Também mantém um quadro de candidaturas com status, prazos e linha do tempo.

Tudo roda no seu computador. Nada é enviado para fora, além das buscas feitas nos sites de vagas.

## Instalar no Windows (uma vez)

1. Instale o **Python 3.12 ou mais novo** em <https://www.python.org/downloads/>. Na primeira tela do instalador, marque **"Add python.exe to PATH"**.
   - Se a instalação do `python-jobspy` falhar na sua versão, instale também o Python 3.12: as duas versões convivem, e o `iniciar.bat` usa a 3.12 quando ela existe (rode o `reinstalar.bat` depois).
2. Descompacte esta pasta onde quiser, por exemplo `C:\Users\<você>\radar-vagas`.
3. Dê dois cliques em **`iniciar.bat`**.
   - Na primeira vez, ele cria o ambiente e instala as dependências (1 a 3 minutos).
   - Depois, abre o navegador em <http://127.0.0.1:8765>.
4. Feche o app, abra o **`config.yaml`** no Bloco de Notas ou no VS Code e troque os termos de `buscas` pela sua área.
5. Rode o `iniciar.bat` de novo e clique em **Coletar agora**.

Para parar o app, feche a janela preta do terminal.

## Uso diário

| Tela | O que fazer |
| --- | --- |
| **Início** | Veja quantas vagas novas chegaram, os prazos dos próximos 7 dias e as candidaturas paradas |
| **Vagas** | Clique em **Abrir vaga**, candidate-se no site e volte para clicar em **Me candidatei**. Use **Salvar** para guardar e **Descartar** para tirar da lista |
| **Detalhe da vaga** | Leia a descrição, veja em quais sites ela apareceu e bloqueie empresas que não interessam |
| **Candidaturas** | Mova cada cartão de etapa quando receber notícias, defina o próximo passo e o prazo, e anote o que acontecer |
| **Adicionar candidatura** | Registre candidaturas feitas fora do radar colando o link |

A coleta roda sozinha a cada 6 horas enquanto o app está aberto. Também dá para rodar só a coleta pelo `coletar.bat`, ou só a avaliação de afinidade pelo `avaliar.bat`.

## Afinidade com IA (fase 2)

O radar dá uma nota de 0 a 100 para cada vaga comparando com o seu **perfil.yaml**, pede segunda opinião de outro provedor nas melhores e monta a tela **Hoje** com o que cabe no seu tempo. Na página de cada vaga dá para adaptar o CV (DOCX e PDF), gerar texto para o perfil Gupy, responder perguntas de formulário, escrever mensagem para recrutador e preparar a entrevista.

### Configurar as chaves (uma vez)

1. Gere as chaves:
   - **Gemini**: resgate os créditos do Google AI Pro em <https://developers.google.com/program/my-benefits> e crie a chave em <https://aistudio.google.com/apikey>.
   - **OpenAI**: <https://platform.openai.com/api-keys> (coloque crédito em Billing).
   - **Claude**: <https://platform.claude.com> → API Keys (coloque crédito em Billing).
2. Abra o arquivo **`.env`** da pasta do projeto no Bloco de Notas (o `iniciar.bat` cria na primeira vez) e cole cada chave depois do `=`.
3. Feche e abra o app. A tela **Ajustes** mostra quais chaves estão funcionando.

Não precisa ter as três: com uma só chave, ela faz tudo. As chaves nunca saem do seu PC, exceto para o próprio provedor.

### Quem faz o quê (padrão)

| Tarefa | Provedor preferido | Reserva |
| --- | --- | --- |
| Nota de todas as vagas | Gemini (rápido) | OpenAI, Claude |
| Segunda opinião nas 10 melhores | OpenAI (forte) | Claude, Gemini |
| CV e textos | Claude (forte) | OpenAI, Gemini |

Dá para mudar a ordem, os modelos e o limite de chamadas por dia na seção `ia` do `config.yaml`.

### Uso diário

1. A coleta roda sozinha a cada 6 h e, logo depois, a avaliação de afinidade.
2. Abra **Hoje**, informe quantos minutos você tem e siga a lista.
3. Em cada vaga: **Adaptar CV** → baixe o PDF → **Abrir vaga** → candidate-se → **Me candidatei** (o CV fica ligado à candidatura).
4. Use **Mais vagas assim** e **Menos vagas assim** (com motivo). Isso ajusta as próximas notas e gera sugestões de regra na tela **Ajustes**.
5. Ao registrar uma candidatura, preencha quanto tempo levou: depois de duas, o radar passa a usar a sua média real por plataforma.

### O que o CV adaptado garante

- Só usa o que está no `perfil.yaml`. Um validador confere cada linha: trecho sem origem no perfil é removido, e reescrita que cite tecnologia ou número que o original não tem volta ao texto original. Os ajustes aparecem em "ajustes feitos pelo validador".
- Todas as experiências aparecem, na ordem certa, para não criar buracos no histórico.
- Uma coluna, títulos padrão e texto selecionável, o formato que os sistemas de triagem leem melhor.
- Mostra quanto das palavras-chave da vaga o CV cobre e separa o que você tem no perfil mas ficou de fora do que a vaga pede e você não tem.

Revise sempre o PDF antes de enviar.

## Ajustar os filtros

Os filtros ficam no `config.yaml`, na seção `filtros`:

- `titulo_deve_conter`: se tiver itens, o título precisa ter pelo menos um.
- `titulo_nao_pode_conter`: termos que eliminam a vaga (ex.: "estágio", "júnior").
- `modelos`: `remoto`, `hibrido`, `presencial`.
- `cidades`: cidades aceitas para vagas presenciais ou híbridas.
- `idade_max_dias`: esconde vagas antigas.
- `empresas_bloqueadas`: nunca mostra essas empresas.

Depois de mudar, clique em **Reaplicar filtros** na tela de Vagas. As vagas filtradas não são apagadas: marque **Incluir filtradas** para vê-las com o motivo.

## Abrir junto com o Windows (opcional)

1. Clique com o botão direito no `iniciar.bat` → **Criar atalho**.
2. Aperte `Win + R`, digite `shell:startup` e dê Enter.
3. Mova o atalho para a pasta que abriu.

## Arquivos

| Caminho | Conteúdo |
| --- | --- |
| `config.yaml` | Seus termos, filtros e configuração de IA (criado na primeira execução) |
| `perfil.yaml` | Seu perfil mestre: a única fonte de fatos para a IA |
| `.env` | Suas chaves de API. Nunca compartilhe este arquivo |
| `dados/cvs/` | Os CVs adaptados gerados (DOCX e PDF) |
| `dados/radar.db` | Banco com vagas e candidaturas. **Faça backup deste arquivo** |
| `dados/radar.log` | Registro das coletas, útil se algo falhar |
| `radar/coletores/` | Um arquivo por fonte. Se uma fonte mudar o formato, só esse arquivo muda |

## Problemas comuns

- **"Python não encontrado"**: reinstale o Python marcando "Add python.exe to PATH".
- **Indeed/LinkedIn sem vagas e erro na tela Início**: o pacote `python-jobspy` não instalou ou o site bloqueou temporariamente. A Gupy continua funcionando. Para reinstalar, rode `reinstalar.bat`.
- **LinkedIn com poucas vagas**: é proposital. A busca é pública, sem login, e poucas páginas evitam bloqueio. Para mais vagas do LinkedIn, ative os alertas de vaga no próprio LinkedIn; a leitura desses e-mails entra na fase 3.
- **IA com erro na tela Ajustes** ("Últimos erros de IA"): `HTTP 401` é chave errada no `.env`; `HTTP 402`/`429` é falta de crédito ou limite do provedor; `HTTP 404` com nome de modelo é modelo que mudou de nome: troque em `ia.provedores` no `config.yaml`. Enquanto um provedor falha, o próximo da lista assume.
- **Porta 8765 ocupada**: mude `servidor.porta` no `config.yaml`.

## Atualizar para uma versão nova

1. Feche o app.
2. Descompacte a versão nova **por cima** da pasta atual, aceitando substituir os arquivos. Seus `config.yaml`, `perfil.yaml`, `.env` e a pasta `dados` não vêm no pacote, então não são tocados.
3. Abra pelo `iniciar.bat`. Se as dependências mudaram, ele reinstala sozinho.

## Próximas fases

3. Leitura dos e-mails de atualização das plataformas, com sugestão de status e lembretes.
4. Monitoramento de empresas específicas e de posts "contratando".

## Para desenvolver

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
```
