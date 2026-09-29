# J.A.R.V.I.S — assistente pessoal com painel HUD

Assistente pessoal que roda **localmente no Windows** e reúne num painel único os e-mails (Gmail), a agenda (Google Calendar), as entregas da faculdade (Canvas da PUC-Campinas) e a carteira de investimentos. Um "cérebro" de IA cruza essas informações, gera um briefing do dia e responde por texto e por voz.

> Projeto pessoal de fã, sem afiliação com Marvel ou Disney. O visual é inspirado na ideia de um assistente em HUD, mas tudo foi criado do zero em CSS, SVG e canvas: nenhum logo, imagem, som ou voz de filme é usado.

> **Status: Fase 1 de 6.** A interface completa já funciona com **dados de demonstração**. As integrações reais chegam nas próximas fases.

<!-- Espaço reservado: adicione aqui um print ou GIF do painel -->
<!-- ![Painel HUD](docs/painel.png) -->

## Roteiro

| Fase | Conteúdo | Situação |
|------|----------|----------|
| 1 | Esqueleto, interface HUD com dados de demonstração, núcleo animado e voz | ✅ pronta |
| 2 | Canvas (API + feed iCal como plano B) e investimentos (CSV + brapi), com cache | ⏳ |
| 3 | Gmail e Google Calendar (OAuth, somente leitura) | ⏳ |
| 4 | Cérebro: IA com ferramentas, briefing do dia e chat | ⏳ |
| 5 | Acabamento: erros, testes, README final e `iniciar.ps1` | ⏳ |
| 6 | Extras: animação de abertura na borda da tela e seletor de voz (Piper TTS opcional) | ⏳ |

## Requisitos

- Windows 10 ou 11
- Python 3.11 ou mais novo ([python.org](https://www.python.org/downloads/)); marque "Add python.exe to PATH" na instalação
- Chrome ou Edge (para a voz)

## Instalação (PowerShell)

```powershell
cd C:\dev\jarvis

# 1. Ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Se o PowerShell bloquear o script, rode uma vez:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 2. Dependências
python -m pip install -r requirements.txt

# 3. Configuração (opcional nesta fase: sem .env, valem os padrões)
Copy-Item .env.example .env
```

## Como rodar

```powershell
.\.venv\Scripts\Activate.ps1
python -m app
```

Abra **http://127.0.0.1:8000** no Chrome ou no Edge.

Para desenvolver, `python -m app --reload` reinicia o servidor sozinho quando você salva um arquivo.
A documentação interativa da API fica em http://127.0.0.1:8000/api/docs.

## Usando o painel

- **Falar:** segure **Espaço** e fale; solte para enviar. Funciona também com o cursor no campo de mensagem, desde que ele esteja vazio; com texto no campo, o Espaço digita normalmente. Ou clique no microfone (ele para sozinho quando você fica em silêncio).
- **Interromper:** **Esc** para de ouvir e de falar.
- **Voz das respostas:** o botão de alto-falante ao lado do campo liga e desliga a fala.
- **Briefing em voz alta:** o botão de alto-falante no painel do briefing.
- **Sistemas:** o indicador no topo mostra quantas fontes (agenda, e-mails, faculdade e carteira) estão online. Passe o mouse para ver o estado de cada uma.
- **Atualizar:** cada painel tem seu botão ↻, e o botão "Atualizar" no topo recarrega todos. A atualização automática roda a cada `REFRESH_SECONDS` (padrão: 5 minutos).

No modo demonstração, o chat entende perguntas sobre **entregas, e-mails, agenda e carteira**. Na Fase 4 ele passa a usar IA.

### Testar os estados de erro

Cada painel é independente. Para ver como a interface reage a falhas, abra:

```
http://127.0.0.1:8000/?simular=email:erro,portfolio:nao_configurado
http://127.0.0.1:8000/?simular=todos:erro
```

Nomes aceitos: `briefing`, `calendar`, `email`, `canvas`, `portfolio` e `todos`. Estados aceitos: `erro` e `nao_configurado`.

## Testes

```powershell
python -m pytest
```

## Configuração (`.env`)

| Variável | Para que serve | Padrão |
|----------|----------------|--------|
| `ASSISTANT_NAME` | Nome exibido e falado pelo assistente | `J.A.R.V.I.S` |
| `USER_NAME` | Como o assistente chama você: seu nome ou um tratamento como `senhor` ou `senhora` | vazio |
| `PORT` | Porta local do servidor | `8000` |
| `TIMEZONE` | Fuso horário | `America/Sao_Paulo` |
| `REFRESH_SECONDS` | Intervalo da atualização automática | `300` |
| `DEMO_MODE` | `true` = dados de demonstração | `true` |

As demais variáveis do `.env.example` (Canvas, brapi, Google e Gemini) serão usadas nas próximas fases.

## Estrutura

```
jarvis/
├── app/
│   ├── main.py            # FastAPI: rotas, arquivos estáticos e proteções de acesso local
│   ├── config.py          # configuração lida do .env (Pydantic Settings)
│   ├── models.py          # schemas Pydantic compartilhados por API, conectores e IA
│   ├── sources.py         # ponto único de onde cada painel tira seus dados
│   ├── formatting.py      # formatação em português (R$, %, durações)
│   ├── connectors/        # demo.py agora; canvas, investimentos, gmail e calendar depois
│   └── llm/               # briefing.py (regras, depois IA) e chat.py
├── static/                # index.html, css/hud.css, js/ (módulos ES, sem framework)
├── data/                  # carteira.example.csv (a sua carteira.csv fica fora do Git)
└── tests/
```

## Segurança e privacidade

- O servidor escuta **somente em `127.0.0.1`**; não é acessível por outros dispositivos da rede.
- Requisições com o header `Host` diferente de `127.0.0.1` ou `localhost` são recusadas. Isso protege contra *DNS rebinding*: um site malicioso aberto no seu navegador não consegue ler os dados do painel.
- Requisições que alteram algo (como o chat) vindas de outros sites são bloqueadas.
- Todo texto vindo das fontes é inserido na página como texto puro, nunca como HTML. Um e-mail com código malicioso no assunto não é executado.
- Chaves e tokens ficam só no `.env`, que o `.gitignore` exclui, assim como `credentials.json`, `token.json`, a pasta `data/` e bancos SQLite.
- **Voz:** no Chrome e no Edge, o reconhecimento de fala envia o áudio ao serviço online do próprio navegador (Google ou Microsoft). A síntese de fala usa as vozes do Windows ou do navegador.

## Decisões técnicas

- **Um envelope para todo painel** (`PanelResponse`): `status` (`ok`, `not_configured` ou `error`), origem, horário e dados. É o que permite a cada painel falhar sozinho.
- **Os dados de demonstração usam os mesmos modelos que os dados reais.** As próximas fases trocam só `sources.py`; as rotas e a interface não mudam.
- **Cálculos da carteira nos modelos** (`computed_field`): valor de mercado, resultado sobre o preço médio, variação do dia e distribuição por tipo ficam num só lugar, testado.
- **Briefing por regras:** já cruza as fontes (prazo apertado + e-mail do professor + agenda até o prazo). Na Fase 4 a IA assume a redação, e as regras ficam como plano B quando a cota acabar.
- **Tom e visual inspirados, não copiados:** o assistente fala como um mordomo educado e direto, com frases próprias. O núcleo usa a linguagem visual de HUD (anéis concêntricos, varredura de radar, anel de barras como visualizador de voz), desenhada em canvas. A voz preferida é uma voz masculina gratuita já disponível no Edge ou no Windows; nenhuma voz real é imitada.
- **"Reagir ao áudio":** a `speechSynthesis` não expõe o áudio gerado. O núcleo reage aos eventos de palavra da fala, somados a uma modulação sintética para as vozes que não emitem esses eventos.
