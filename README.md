# J.A.R.V.I.S — assistente pessoal com painel HUD

Assistente pessoal que roda **localmente no Windows** e reúne num painel único os e-mails (Gmail), a agenda (Google Calendar), as entregas da faculdade (Canvas da PUC-Campinas) e a carteira de investimentos. Um "cérebro" de IA cruza essas informações, gera um briefing do dia e responde por texto e por voz.

> Projeto pessoal de fã, sem afiliação com Marvel ou Disney. O visual é inspirado na ideia de um assistente em HUD, mas tudo foi criado do zero em CSS, SVG e canvas: nenhum logo, imagem, som ou voz de filme é usado.

> **Status: Fase 2 de 6.** A interface completa funciona com dados de demonstração, e os painéis **Faculdade** (Canvas) e **Mercado** (brapi e AwesomeAPI) já usam dados reais. Gmail e Agenda chegam na Fase 3.

<!-- Espaço reservado: adicione aqui um print ou GIF do painel -->
<!-- ![Painel HUD](docs/painel.png) -->

## Roteiro

| Fase | Conteúdo | Situação |
|------|----------|----------|
| 1 | Esqueleto, interface HUD com dados de demonstração, núcleo animado e voz | ✅ pronta |
| 2 | Canvas (API + feed iCal como plano B), mercado (dólar ao vivo + cotações da carteira) e cache | ✅ pronta |
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
- **Sistemas:** o indicador no topo mostra quantas fontes (agenda, e-mails, faculdade e mercado) estão online. Passe o mouse para ver o estado de cada uma.
- **Atualizar:** cada painel tem seu botão ↻, e o botão "Atualizar" no topo recarrega todos, buscando dados novos. A atualização automática roda a cada `REFRESH_SECONDS` (padrão: 10 minutos) e aproveita o cache. As cotações respeitam sempre o cache de 30 minutos, por causa do limite do plano gratuito.
- **Avisos nos painéis:** a faixa âmbar no topo de um painel explica algo sobre os dados, por exemplo "usando o feed do calendário" ou "mostrando cotações de 14:30". "dados de 14:30" no cabeçalho do painel indica que os dados vieram do cache.

No modo demonstração, o chat entende perguntas sobre **entregas, e-mails, agenda e carteira**. Na Fase 4 ele passa a usar IA.

### Testar os estados de erro

Cada painel é independente. Para ver como a interface reage a falhas, abra:

```
http://127.0.0.1:8000/?simular=email:erro,market:nao_configurado
http://127.0.0.1:8000/?simular=todos:erro
```

Nomes aceitos: `briefing`, `calendar`, `email`, `canvas`, `market` e `todos`. Estados aceitos: `erro` e `nao_configurado`.

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
| `DEMO_MODE` | `true` = dados de demonstração; `false` = dados reais | `true` |
| `CANVAS_BASE_URL` | Endereço do Canvas da faculdade | `https://puc-campinas.instructure.com` |
| `CANVAS_TOKEN` | Token de acesso pessoal do Canvas | vazio |
| `CANVAS_ICS_URL` | Link do feed do calendário (plano B do token) | vazio |
| `BRAPI_TOKEN` | Token gratuito da brapi | vazio |
| `BRAPI_TICKERS_PER_REQUEST` | Ativos por requisição (gratuito: 1; Startup: 10; Pro: 20) | `1` |

As variáveis do Google e do Gemini serão usadas nas Fases 3 e 4.

## Conectando suas fontes

Depois de configurar, mude `DEMO_MODE=false` no `.env` e reinicie o servidor. Painéis sem credencial mostram "não configurado" e dizem o que falta.

### Canvas (faculdade)

Configure o token, o feed ou os dois. Com os dois, o painel usa o token e cai para o feed sozinho se o token falhar.

**Token (recomendado, mostra se a tarefa foi entregue):**

1. Entre em https://puc-campinas.instructure.com.
2. Clique em **Conta** → **Configurações**.
3. Em "Integrações aprovadas", clique em **+ Novo token de acesso**.
4. Dê um nome (ex.: "Painel pessoal") e **defina uma data de validade**.
5. Copie o token e cole em `CANVAS_TOKEN=` no `.env`. O Canvas só mostra o token uma vez.

> O token do Canvas não tem "modo somente leitura": ele permite tudo o que você pode fazer na sua conta. Por isso o painel usa um cliente HTTP que **bloqueia qualquer requisição que não seja leitura (GET)**, e o token só é enviado para o endereço do Canvas. Mesmo assim, trate-o como uma senha e prefira uma validade curta.

**Feed do calendário (plano B, para quando a instituição bloqueia tokens):**

1. No Canvas, abra **Calendário**.
2. No canto inferior direito, clique em **Feed do calendário** e copie o link.
3. Cole em `CANVAS_ICS_URL=` no `.env`. O link contém um código secreto; trate-o como um token.

O feed traz os prazos, mas não diz se a tarefa já foi entregue. Por isso, com ele, as entregas aparecem sem o selo "Pendente"/"Entregue".

### Mercado (dólar e cotações da carteira)

O painel **Mercado** da home mostra o dólar comercial ao vivo e a cotação do dia de cada ativo da sua carteira. **Ele não mostra quantidades, patrimônio nem resultado**, e o briefing e o chat também não falam do valor investido, só de percentuais.

1. Copie o modelo e edite com as suas posições:

   ```powershell
   Copy-Item data\carteira.example.csv data\carteira.csv
   ```

   Colunas: `ticker,tipo,quantidade,preco_medio`. Tipos aceitos: `ação`, `FII`, `ETF`, `BDR`, `ETF Internacional` (listado nos EUA, ex.: `VOO`, com preço médio em dólar) e `Tesouro Direto` (o "ticker" é o nome do título, ex.: `Tesouro Selic 2031`). Quantidades fracionadas (ex.: `0.75`) são aceitas. Pode editar no Excel: o formato com `;` e vírgula decimal (ex.: `32,50`) também funciona. O mesmo ticker em duas linhas é somado, e o preço médio é recalculado. O arquivo fica fora do Git.

2. Crie uma conta gratuita em https://brapi.dev, copie o token no painel (https://brapi.dev/dashboard) e cole em `BRAPI_TOKEN=` no `.env`.

**De onde vêm os dados:**

| Dado | Fonte | Custo |
|------|-------|-------|
| Cotações da B3 e dos EUA | brapi v2 (`/api/v2/stocks/quote`), com token | grátis, 15 mil requisições em 30 dias |
| Dólar comercial | AwesomeAPI (`/json/last/USD-BRL`), sem chave | grátis, atualiza a cada minuto |
| Tesouro Direto | sem fonte gratuita ao vivo (a brapi só oferece nos planos pagos) | aparece como "sem cotação" |

Ativos dos EUA aparecem em US$. A conversão para reais pelo dólar do momento só é usada nos cálculos internos da carteira (percentuais do briefing).

**Limites do plano gratuito da brapi** (conferidos em brapi.dev/pricing): 1 ativo por requisição, 15 mil requisições em 30 dias e dados atualizados a cada 30 minutos. O câmbio da brapi só existe nos planos pagos, por isso o dólar vem da AwesomeAPI. Para respeitar os limites, o painel:

- guarda cada cotação por 30 minutos durante o pregão e, com o mercado fechado, até a próxima abertura (B3: 10h às 18h30; EUA: 9h30 às 16h15 de Nova York);
- busca só os ativos cujo cache venceu, um de cada vez;
- lê a cota restante que a própria brapi informa em cada resposta e pausa as buscas quando sobram menos de 5%, mostrando as últimas cotações conhecidas.

Com cerca de 20 ativos, isso dá no máximo umas 7.600 requisições por mês, mesmo com o painel aberto o dia inteiro. O dólar é consultado a cada minuto enquanto a página está visível.

O painel apenas descreve o mercado. Ele não faz recomendação de compra ou venda.

### Aba privada "Minha carteira"

O botão de cadeado no painel Mercado abre a sua carteira completa: patrimônio, variação do dia, resultado sobre o preço médio, distribuição por tipo, posições (quantidade, preço médio, preço e valor) e os ativos sem cotação ao vivo, como o Tesouro Direto, pelo valor aplicado.

1. No `.env`, defina uma chave que só você saiba, com **10 caracteres ou mais** (mais curta, a aba fica desativada):

   ```
   PORTFOLIO_ACCESS_KEY=sua-chave-aqui
   PRIVATE_SESSION_MINUTES=5
   ```

2. Reinicie o servidor. Sem a chave, a aba fica desativada.

Como a proteção funciona:

- a chave é conferida só no servidor, com comparação em tempo constante, e nunca aparece em logs, na URL nem no código da página;
- a carteira só sai de `/api/private/portfolio`, que exige a sessão desbloqueada, com `Cache-Control: no-store`; não existe outra rota que devolva quantidades ou valores;
- a sessão fica num cookie `HttpOnly` e `SameSite=Strict`, expira após `PRIVATE_SESSION_MINUTES` sem uso e acaba no botão **Bloquear** ou ao reiniciar o servidor;
- depois de 3 erros, cada tentativa espera o dobro da anterior (5 s, 10 s, 20 s... até 5 minutos);
- fechar a janela, apertar Esc, trocar de aba ou minimizar apaga os dados da tela.

O objetivo é que a carteira não apareça na tela do Jarvis para quem estiver olhando. O arquivo `data/carteira.csv` continua sendo um arquivo comum no seu computador.

## Estrutura

```
jarvis/
├── app/
│   ├── main.py            # FastAPI: rotas, arquivos estáticos e proteções de acesso local
│   ├── config.py          # configuração lida do .env (Pydantic Settings)
│   ├── models.py          # schemas Pydantic compartilhados por API, conectores e IA
│   ├── sources.py         # ponto único de onde cada painel tira seus dados
│   ├── cache.py           # cache SQLite com validade (TTL) e reserva de dados antigos
│   ├── formatting.py      # formatação em português (R$, %, durações)
│   ├── connectors/        # canvas, brapi (cotações), fx (dólar), investments, http (só leitura), demo
│   └── llm/               # briefing.py (regras, depois IA) e chat.py
├── static/                # index.html, css/hud.css, js/ (módulos ES, sem framework)
├── data/                  # carteira.example.csv (a sua carteira.csv fica fora do Git)
└── tests/
```

## Segurança e privacidade

- O servidor escuta **somente em `127.0.0.1`**; não é acessível por outros dispositivos da rede.
- Requisições com o header `Host` diferente de `127.0.0.1` ou `localhost` são recusadas. Isso protege contra *DNS rebinding*: um site malicioso aberto no seu navegador não consegue ler os dados do painel.
- Requisições que alteram algo (como o chat) vindas de outros sites são bloqueadas.
- A interface nunca cita nomes de arquivos (`.env`, `carteira.csv`...) nem de variáveis de configuração. Quando falta algo, o painel mostra uma mensagem genérica, e o terminal onde você rodou `python -m app` diz exatamente o que configurar e onde.
- Todo texto vindo das fontes é inserido na página como texto puro, nunca como HTML. Um e-mail com código malicioso no assunto não é executado.
- Chaves e tokens ficam só no `.env`, que o `.gitignore` exclui, assim como `credentials.json`, `token.json`, a pasta `data/` e bancos SQLite.
- As integrações só leem dados: o cliente HTTP dos conectores recusa qualquer método diferente de GET antes de a requisição sair do computador.
- Tokens vão no header `Authorization`, nunca na URL, e as mensagens de erro do painel são escritas sem URLs (o link do feed iCal contém um segredo).
- O cache (`data/cache.sqlite3`) guarda só o que aparece nos painéis e fica fora do Git.
- **Voz:** no Chrome e no Edge, o reconhecimento de fala envia o áudio ao serviço online do próprio navegador (Google ou Microsoft). A síntese de fala usa as vozes do Windows ou do navegador.

## Decisões técnicas

- **Um envelope para todo painel** (`PanelResponse`): `status` (`ok`, `not_configured` ou `error`), origem, horário e dados. É o que permite a cada painel falhar sozinho.
- **Os dados de demonstração usam os mesmos modelos que os dados reais.** As próximas fases trocam só `sources.py`; as rotas e a interface não mudam.
- **Cálculos da carteira nos modelos** (`computed_field`): valor de mercado, resultado sobre o preço médio, variação do dia e distribuição por tipo ficam num só lugar, testado.
- **Briefing por regras:** já cruza as fontes (prazo apertado + e-mail do professor + agenda até o prazo). Na Fase 4 a IA assume a redação, e as regras ficam como plano B quando a cota acabar.
- **Canvas pelo planner:** `/api/v1/planner/items` traz numa só lista tarefas, quizzes e fóruns avaliados, com prazo e situação da entrega, o que evita cruzar `todo` e `upcoming_events`. Os nomes das disciplinas vêm de `/api/v1/courses` e ficam 12 horas no cache. A paginação segue o header `Link`, só dentro do domínio do Canvas.
- **Cache com reserva:** cada fonte guarda a última resposta boa. Se a API cair, o painel mostra os dados antigos com um aviso, em vez de um erro.
- **Uma busca por vez:** um lock por conector evita que o painel e o briefing, pedindo os mesmos dados ao mesmo tempo, gastem duas requisições.
- **Tom e visual inspirados, não copiados:** o assistente fala como um mordomo educado e direto, com frases próprias. O núcleo usa a linguagem visual de HUD (anéis concêntricos, varredura de radar, anel de barras como visualizador de voz), desenhada em canvas. A voz preferida é uma voz masculina gratuita já disponível no Edge ou no Windows; nenhuma voz real é imitada.
- **"Reagir ao áudio":** a `speechSynthesis` não expõe o áudio gerado. O núcleo reage aos eventos de palavra da fala, somados a uma modulação sintética para as vozes que não emitem esses eventos.
