# J.A.R.V.I.S — assistente pessoal com painel HUD

Assistente pessoal que roda **localmente no Windows** e reúne num painel único os e-mails (Gmail), a agenda (Google Calendar), as entregas da faculdade (Canvas da PUC-Campinas) e a carteira de investimentos. Um "cérebro" de IA cruza essas informações, gera um briefing do dia, responde por texto e por voz e, sempre com a sua confirmação, cria compromissos na agenda e insere ativos na carteira.

> Projeto pessoal de fã, sem afiliação com Marvel ou Disney. O visual é inspirado na ideia de um assistente em HUD, mas tudo foi criado do zero em CSS, SVG e canvas: nenhum logo, imagem, som ou voz de filme é usado.

> **Status: Fase 5 de 6.** O assistente está completo: painéis com dados reais, IA com ferramentas, ações com confirmação, tratamento de erros e inicialização com um clique. Falta só a Fase 6, de extras visuais e de voz.

<!-- Espaço reservado: adicione aqui um print ou GIF do painel -->
<!-- ![Painel HUD](docs/painel.png) -->

## Sumário

- [Começo rápido](#começo-rápido)
- [Roteiro](#roteiro)
- [Instalação manual](#instalação-manual)
- [Usando o painel](#usando-o-painel)
- [Configuração (`.env`)](#configuração-env)
- [Conectando suas fontes](#conectando-suas-fontes): [Canvas](#canvas-faculdade), [Google](#google-gmail-e-agenda), [Mercado](#mercado-dólar-e-cotações-da-carteira), [Minha carteira](#aba-privada-minha-carteira), [IA](#ia-google-gemini), [Ações pelo chat](#criar-compromissos-e-inserir-ativos-pelo-chat)
- [Solução de problemas](#solução-de-problemas)
- [Testes](#testes)
- [Estrutura](#estrutura)
- [Segurança e privacidade](#segurança-e-privacidade)
- [Decisões técnicas](#decisões-técnicas)

## Começo rápido

Precisa de: Windows 10 ou 11, [Python 3.11 ou mais novo](https://www.python.org/downloads/) (na instalação, marque **"Add python.exe to PATH"**) e Chrome ou Edge.

1. Baixe o projeto (ou clone com o Git) numa pasta, por exemplo `C:\dev\jarvis`.
2. Abra o PowerShell nessa pasta e rode:

   ```powershell
   .\iniciar.ps1
   ```

3. O painel abre sozinho no navegador, no **modo demonstração**, com dados de exemplo. Para encerrar, aperte **Ctrl+C** na janela do PowerShell.

Na primeira vez, o `iniciar.ps1` cria o ambiente virtual, instala as dependências e cria o arquivo `.env` a partir do modelo. Nas próximas, ele só inicia o servidor, e reinstala as dependências apenas quando o `requirements.txt` muda. Se o assistente já estiver aberto, ele só abre o painel de novo. Use `.\iniciar.ps1 -SemNavegador` para não abrir o navegador.

Para usar os seus dados, siga [Conectando suas fontes](#conectando-suas-fontes) e mude `DEMO_MODE=false` no `.env`.

> Se o PowerShell disser que a execução de scripts está desabilitada, rode uma vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e tente de novo.

## Roteiro

| Fase | Conteúdo | Situação |
|------|----------|----------|
| 1 | Esqueleto, interface HUD com dados de demonstração, núcleo animado e voz | ✅ pronta |
| 2 | Canvas (API + feed iCal como plano B), mercado (dólar ao vivo + cotações da carteira) e cache | ✅ pronta |
| 3 | Gmail e Google Calendar (OAuth) | ✅ pronta |
| 4 | Cérebro: IA com ferramentas, briefing do dia e chat; criar eventos e inserir ativos com confirmação | ✅ pronta |
| 5 | Acabamento: tratamento de erros, logs sem segredos, testes, README final e `iniciar.ps1` | ✅ pronta |
| 6 | Extras: animação de abertura na borda da tela, seletor de voz (Piper TTS opcional) e, por último, interface mais fluida, futurista e minimalista | ⏳ |

## Instalação manual

Se preferir fazer à mão o que o `iniciar.ps1` faz:

```powershell
cd C:\dev\jarvis

# 1. Ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Dependências
python -m pip install -r requirements.txt

# 3. Configuração
Copy-Item .env.example .env

# 4. Iniciar (--open abre o navegador quando o servidor estiver pronto)
python -m app --open
```

O painel fica em **http://127.0.0.1:8000**. Para desenvolver, `python -m app --reload` reinicia o servidor sozinho quando você salva um arquivo. A documentação interativa da API fica em http://127.0.0.1:8000/api/docs.

Ao iniciar, o terminal lista o que ainda falta configurar (por exemplo, "defina BRAPI_TOKEN no .env"). A interface nunca mostra nomes de arquivos ou variáveis: esses detalhes ficam só no terminal.

## Usando o painel

- **Falar:** segure **Espaço** e fale; solte para enviar. Funciona também com o cursor no campo de mensagem, desde que ele esteja vazio; com texto no campo, o Espaço digita normalmente. Ou clique no microfone (ele para sozinho quando você fica em silêncio).
- **Interromper:** **Esc** para de ouvir e de falar.
- **Voz das respostas:** o botão de alto-falante ao lado do campo liga e desliga a fala.
- **Briefing em voz alta:** o botão de alto-falante no painel do briefing.
- **Sistemas:** o indicador no topo mostra quantas fontes (agenda, e-mails, faculdade e mercado) estão online. Passe o mouse para ver o estado de cada uma.
- **Atualizar:** cada painel tem seu botão ↻, e o botão "Atualizar" no topo recarrega todos, buscando dados novos. A atualização automática roda a cada `REFRESH_SECONDS` (padrão: 5 minutos) e aproveita o cache. As cotações respeitam sempre o cache de 30 minutos, por causa do limite do plano gratuito.
- **Avisos nos painéis:** a faixa âmbar no topo de um painel explica algo sobre os dados, por exemplo "usando o feed do calendário" ou "mostrando cotações de 14:30". "dados de 14:30" no cabeçalho do painel indica que os dados vieram do cache.
- **Cada painel é independente:** se uma fonte falhar, só aquele painel mostra "erro — tentar de novo"; o resto continua funcionando.

Com a IA configurada (veja [IA (Google Gemini)](#ia-google-gemini)), o chat responde perguntas livres e consulta a agenda, os e-mails, a faculdade e a carteira quando precisa. Ele lembra as últimas falas por 15 minutos, então dá para emendar ("e depois de amanhã?"). Ele também prepara [compromissos e ativos](#criar-compromissos-e-inserir-ativos-pelo-chat) para você confirmar. Sem a IA, ou quando a cota acaba, o chat entende só perguntas diretas sobre **entregas, e-mails, agenda e carteira**, e uma mensagem na conversa avisa quando isso acontece.

### Testar os estados de erro

Para ver como a interface reage a falhas, no modo demonstração, abra:

```
http://127.0.0.1:8000/?simular=email:erro,market:nao_configurado
http://127.0.0.1:8000/?simular=todos:erro
```

Nomes aceitos: `briefing`, `calendar`, `email`, `canvas`, `market` e `todos`. Estados aceitos: `erro` e `nao_configurado`.

## Configuração (`.env`)

| Variável | Para que serve | Padrão |
|----------|----------------|--------|
| `ASSISTANT_NAME` | Nome exibido e falado pelo assistente | `J.A.R.V.I.S` |
| `USER_NAME` | Como o assistente chama você: seu nome ou um tratamento como `senhor` ou `senhora` | vazio |
| `PORT` | Porta local do servidor | `8000` |
| `TIMEZONE` | Fuso horário | `America/Sao_Paulo` |
| `REFRESH_SECONDS` | Intervalo da atualização automática, em segundos | `300` |
| `DEMO_MODE` | `true` = dados de demonstração; `false` = dados reais | `true` |
| `CANVAS_BASE_URL` | Endereço do Canvas da faculdade | `https://puc-campinas.instructure.com` |
| `CANVAS_TOKEN` | Token de acesso pessoal do Canvas | vazio |
| `CANVAS_ICS_URL` | Link do feed do calendário (plano B do token) | vazio |
| `BRAPI_TOKEN` | Token gratuito da brapi | vazio |
| `BRAPI_TICKERS_PER_REQUEST` | Ativos por requisição (gratuito: 1; Startup: 10; Pro: 20) | `1` |
| `PORTFOLIO_ACCESS_KEY` | Chave da aba privada "Minha carteira" (10 caracteres ou mais) | vazio |
| `PRIVATE_SESSION_MINUTES` | Minutos sem uso até a aba privada bloquear sozinha | `5` |
| `GOOGLE_CREDENTIALS_FILE` | Credencial OAuth "Desktop app" do Google Cloud | `credentials.json` |
| `GOOGLE_TOKEN_FILE` | Acesso salvo ao conectar o Google (criado sozinho) | `token.json` |
| `GMAIL_MAX_MESSAGES` | Quantos e-mails recentes mostrar (1 a 50) | `15` |
| `UNIVERSITY_EMAIL_DOMAINS` | Domínios que contam como "da faculdade" | `puc-campinas.edu.br,instructure.com` |
| `GOOGLE_CALENDAR_IDS` | Agendas lidas, separadas por vírgula | `primary` |
| `LLM_PROVIDER` | Provedor da IA (por enquanto, só `gemini`) | `gemini` |
| `GEMINI_API_KEY` | Chave gratuita do Google AI Studio | vazio |
| `GEMINI_MODEL` | Modelo principal | `gemini-3.5-flash-lite` |
| `GEMINI_FALLBACK_MODEL` | Modelo usado quando a cota do principal acaba ou ele está sobrecarregado | `gemini-3.8-flash` |
| `LLM_MAX_TOOL_ROUNDS` | Rodadas de ferramentas por pergunta (0 a 5); cada uma gasta uma requisição | `2` |
| `AI_BRIEFING_MINUTES` | Intervalo mínimo para refazer o briefing da IA quando os dados mudam (5 a 720) | `30` |

Se algum valor for inválido (por exemplo, `PORT=abc`), o servidor não inicia e o terminal diz qual variável corrigir, sem mostrar o valor digitado.

## Conectando suas fontes

Depois de configurar, mude `DEMO_MODE=false` no `.env` e reinicie o servidor. Painéis sem credencial mostram "não configurado", e o terminal diz o que falta.

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

### Google (Gmail e Agenda)

Permissões pedidas:

- **Gmail: só leitura** (`gmail.readonly`). Do Gmail vêm só remetente, assunto e o trecho inicial que o próprio Gmail gera; o corpo dos e-mails nunca é baixado. Mesmo que o código tentasse, o Google recusaria enviar, apagar ou alterar e-mails.
- **Agenda: ler e criar eventos** (`calendar.events`). O painel lê os eventos de hoje e dos próximos 7 dias. Criar evento só acontece quando você clica em **Confirmar** num cartão do chat, e sempre na agenda principal. O app não tem código para editar nem apagar eventos, e o cliente usado para criar recusa qualquer outra operação.

**1. Criar o projeto e ativar as APIs** (uma vez só, gratuito):

1. Entre em https://console.cloud.google.com com a sua conta Google e crie um projeto (ex.: "Jarvis").
2. Em **APIs e serviços → Biblioteca**, procure e **ative** a **Gmail API** e a **Google Calendar API**.

**2. Configurar a tela de consentimento** (menu **Google Auth Platform**):

1. Em **Branding**, clique em **Começar** (Get started): dê um nome ao app e escolha o seu e-mail como e-mail de suporte.
2. Em **Público-alvo** (Audience), escolha **Externo**. A opção "Interno" só existe para contas Google Workspace de empresas.
3. Ainda em **Público-alvo**, deixe o app em **Teste** e, em **Usuários de teste**, adicione o **seu próprio e-mail**.
4. Informe o e-mail de contato, aceite a política de dados do Google e conclua.

**3. Criar a credencial**:

1. Em **Google Auth Platform → Clientes**, clique em **Criar cliente**.
2. Tipo de aplicativo: **App para computador** (Desktop app). Dê um nome e crie.
3. Clique em **Baixar JSON** e salve o arquivo na pasta do projeto com o nome **`credentials.json`**. Ele fica fora do Git.

**4. Conectar**:

1. Com `DEMO_MODE=false`, reinicie o servidor e abra o painel.
2. Nos painéis Agenda ou E-mails, clique em **Conectar Google**. O Google abre no navegador.
3. Escolha a sua conta. Como o app é seu e está em teste, o Google avisa que ele **não foi verificado**: clique em **Avançado → Acessar (nome do app)**. Isso é esperado para apps pessoais.
4. Autorize a leitura do Gmail e o acesso à Agenda. Quando aparecer "Conectado ao Google", pode fechar a aba: os painéis se atualizam sozinhos.

**Conectou antes da Fase 4?** A conexão antiga era só leitura e continua funcionando para os painéis. Na primeira vez que você confirmar um evento, o cartão pede **Reconectar Google**: clique, autorize de novo e confirme. Se na tela do Google você desmarcar a Agenda, o painel continua lendo, mas não cria eventos.

**Reconexão a cada 7 dias:** com o app em modo **Teste**, o Google invalida a autorização depois de 7 dias. Quando isso acontece, os painéis mostram **Reconectar Google**; basta clicar e autorizar de novo. O resto do painel continua funcionando.

O acesso fica salvo em `token.json`, na pasta do projeto e fora do Git. Para revogar a qualquer momento, apague esse arquivo ou remova o app em https://myaccount.google.com/permissions.

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

O botão de cadeado no painel Mercado abre a sua carteira completa: patrimônio, variação do dia, resultado sobre o preço médio, distribuição por tipo, posições (quantidade, preço médio, preço e valor) e os ativos sem cotação ao vivo, como o Tesouro Direto, pelo valor aplicado. É também lá que você confirma os ativos que pedir ao chat.

1. No `.env`, defina uma chave que só você saiba, com **10 caracteres ou mais** (mais curta, a aba fica desativada):

   ```
   PORTFOLIO_ACCESS_KEY=sua-chave-aqui
   PRIVATE_SESSION_MINUTES=5
   ```

2. Reinicie o servidor. Sem a chave, a aba fica desativada.

Como a proteção funciona:

- a chave é conferida só no servidor, com comparação em tempo constante, e nunca aparece em logs, na URL nem no código da página;
- a carteira só sai das rotas `/api/private/...`, que exigem a sessão desbloqueada e respondem com `Cache-Control: no-store`; nenhuma outra rota devolve quantidades ou valores;
- a sessão fica num cookie `HttpOnly` e `SameSite=Strict`, expira após `PRIVATE_SESSION_MINUTES` sem uso e acaba no botão **Bloquear** ou ao reiniciar o servidor;
- depois de 3 erros, cada tentativa espera o dobro da anterior (5 s, 10 s, 20 s... até 5 minutos);
- fechar a janela, apertar Esc, trocar de aba ou minimizar apaga os dados da tela.

O objetivo é que a carteira não apareça na tela do Jarvis para quem estiver olhando. O arquivo `data/carteira.csv` continua sendo um arquivo comum no seu computador.

### IA (Google Gemini)

O chat e o briefing usam o Google Gemini pelo SDK oficial `google-genai`, no plano gratuito. Sem a chave, tudo continua funcionando com as respostas e o briefing por regras.

1. Acesse [Google AI Studio → API keys](https://aistudio.google.com/apikey) com a sua conta Google e clique em **Create API key**.
2. No `.env`, preencha a chave. Não compartilhe nem cole a chave em nenhum outro lugar:

   ```
   GEMINI_API_KEY=sua-chave-aqui
   ```

3. Reinicie o servidor.

**Modelos e limites.** O padrão é o `gemini-3.5-flash-lite`: gratuito, com chamada de funções e com limites folgados (15 requisições por minuto e 500 por dia, em setembro de 2026). Quando a cota dele acaba ou ele está sobrecarregado, o assistente tenta o `gemini-3.8-flash`, mais capaz, mas com só 20 requisições por dia. Os limites mudam com o tempo e por conta: confira os seus em [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit). Uma pergunta no chat gasta de 1 a 3 requisições. O briefing gasta 1 e só é refeito quando os dados mudam, no máximo a cada `AI_BRIEFING_MINUTES`.

**Quando a IA falha** (cota esgotada, sem internet, erro da API), o chat responde pelas regras e avisa na conversa, e o briefing volta a ser gerado por regras, com um aviso no painel. Depois de uma falha, o briefing espera 10 minutos antes de chamar a IA de novo.

> ⚠️ **Privacidade no plano gratuito.** Pelos [termos do Gemini API](https://ai.google.dev/gemini-api/terms), nos serviços gratuitos **o Google usa o conteúdo enviado e as respostas para melhorar os produtos**, e revisores humanos podem ler esses dados (desvinculados da sua conta e da sua chave). Os termos também pedem que você **não envie informações sensíveis, confidenciais ou pessoais** aos serviços gratuitos, e com `DEMO_MODE=false` o assistente envia dados pessoais seus (assuntos de e-mail, compromissos, entregas). Decida conscientemente se vale a pena, e evite digitar no chat coisas realmente sensíveis (senhas, documentos, saúde). Veja abaixo exatamente o que é enviado. Para não enviar nada, deixe `GEMINI_API_KEY` vazio, e o painel funciona só com as regras.

**O que é enviado ao Google a cada pergunta ou briefing:**

- sua pergunta e as últimas falas da conversa (até 3 perguntas e respostas dos últimos 15 minutos);
- **agenda:** título, horário e local dos eventos do período pedido;
- **e-mails:** nome do remetente, assunto, data e se foi lido. **Nunca** o corpo da mensagem nem o endereço de e-mail;
- **faculdade:** título, disciplina, prazo e situação das entregas. Nunca os links do Canvas;
- **carteira:** dólar, cotação e variação de cada ativo, variação da carteira em %, resultado sobre o preço médio em % e distribuição por tipo em %. **Nunca** quantidades, valor investido ou patrimônio;
- **ações pedidas:** o que você pediu (título e horário do compromisso; ticker, tipo, quantidade e preço do ativo). A IA não fica sabendo se o ativo já existia na carteira.

Com `DEMO_MODE=true`, a IA recebe só os dados de demonstração. É uma boa forma de testar antes de ligar os seus dados reais.

### Criar compromissos e inserir ativos pelo chat

Por texto ou voz, peça algo como "marque estudo de Cálculo amanhã às 19h" ou "adicione 10 cotas de MXRF11 a R$ 9,80". Precisa da IA configurada; para ativos, também da [aba privada](#aba-privada-minha-carteira).

**A IA só propõe. Nada é gravado antes do seu clique em Confirmar.**

- Aparece um cartão no chat com os botões **Confirmar** e **Cancelar**. Ele expira em 5 minutos e só vale uma vez.
- Dizer "confirmo" no chat ou por voz não grava nada: a IA não tem como confirmar por você.
- **Compromisso:** o cartão mostra título, data, horário e duração (1 hora, se você não disser). O evento vai para a agenda principal do Google.
- **Ativo:** por privacidade, o cartão do chat mostra só o ticker. Clique em **Revisar em Minha carteira**: com a aba desbloqueada, aparecem o tipo, a quantidade, o preço pago e o efeito na carteira. Se o ativo já existe, a quantidade é somada e o preço médio recalculado, e o cartão mostra o antes e o depois. É lá que fica o botão Confirmar.
- O ativo passa pelas mesmas validações do arquivo da carteira (ticker, tipo, quantidade e preço). Antes de cada alteração, uma cópia de segurança vai para `data/backups/` (as 30 mais recentes são mantidas). O arquivo é regravado no formato em que estava, inclusive o do Excel em português.
- Cada ação confirmada é registrada em `data/historico_acoes.jsonl` (data, tipo e resumo), fora do Git.
- No modo demonstração, confirmar não grava nada de verdade.
- Editar ou apagar eventos, vender ativos e enviar e-mails continuam fora do alcance do assistente.

## Solução de problemas

| O que acontece | O que fazer |
|----------------|-------------|
| O PowerShell diz que a execução de scripts está desabilitada | Rode uma vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e tente de novo. |
| "Python 3.11 ou mais novo não encontrado" | Instale pelo [python.org](https://www.python.org/downloads/) marcando **"Add python.exe to PATH"**, feche e abra o PowerShell. |
| "A porta 8000 já está em uso por outro programa" | Feche o programa que usa a porta ou escolha outra em `PORT` no `.env`. Se for o próprio assistente, o `iniciar.ps1` só abre o painel. |
| "Há um valor inválido no .env" | O terminal diz qual variável corrigir. Compare com o `.env.example`. |
| Um painel mostra "Erro inesperado" | Só aquele painel foi afetado. Clique em "tentar de novo"; se continuar, o terminal do servidor mostra os detalhes (sem segredos). |
| "Servidor desatualizado" na aba privada | O código foi atualizado com o servidor aberto. Encerre com Ctrl+C e inicie de novo. |
| O microfone não funciona | Use o Chrome ou o Edge e libere o microfone no cadeado da barra de endereço. A página precisa estar em `127.0.0.1` ou `localhost`. |
| O assistente não fala, ou fala com voz estranha | Instale uma voz em português em **Configurações do Windows → Hora e idioma → Fala**. No Edge, as vozes "Natural" em português costumam soar melhor. |
| O Google diz que o app **não foi verificado** | Esperado para apps pessoais em teste: clique em **Avançado → Acessar (nome do app)**. |
| Os painéis do Google pedem **Reconectar** | Com o app em modo Teste, a autorização vale 7 dias. Clique em Reconectar e autorize de novo. |
| "O Google negou o acesso à Agenda" | Confira se a **Google Calendar API** está ativada no seu projeto do Google Cloud. |
| O cartão de evento pede **Reconectar Google** | A conexão salva é antiga (só leitura) ou a Agenda foi desmarcada na autorização. Reconecte e permita o acesso à Agenda. |
| "A cota gratuita da IA acabou por enquanto" | Espere um minuto (limite por minuto) ou até o dia seguinte (limite diário). Enquanto isso, as regras respondem. |
| "A planilha da carteira está aberta em outro programa" | Feche o arquivo no Excel e clique em Confirmar de novo. O cartão continua valendo até expirar. |
| "O Canvas recusou o token" | O token expirou ou foi bloqueado. Gere um novo no Canvas ou use o feed do calendário como plano B. |

## Testes

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest
```

Os testes não usam a rede nem os seus arquivos: todas as APIs (Canvas, brapi, AwesomeAPI, Google e Gemini) são simuladas, e o cache, a carteira e o histórico ficam em pastas temporárias. Eles cobrem, entre outras coisas: cada conector e seus erros, o cache com reserva, a aba privada, o laço de ferramentas da IA, os cartões de confirmação (expiração, uso único, bloqueio de outros sites), a gravação na carteira com backup, o filtro de segredos nos logs, a inicialização e a regra de que a interface nunca cita nomes de arquivos.

## Estrutura

```
jarvis/
├── app/
│   ├── __main__.py        # python -m app: confere a configuração, a porta e inicia o servidor
│   ├── main.py            # FastAPI: rotas, arquivos estáticos, proteções de acesso local e erros
│   ├── config.py          # configuração lida do .env (Pydantic Settings)
│   ├── logs.py            # logs do terminal com filtro de segredos
│   ├── models.py          # schemas Pydantic compartilhados por API, conectores e IA
│   ├── sources.py         # ponto único de onde cada painel tira seus dados
│   ├── cache.py           # cache SQLite com validade (TTL) e reserva de dados antigos
│   ├── formatting.py      # formatação em português (R$, %, durações)
│   ├── private.py         # chave e sessões da aba "Minha carteira"
│   ├── actions.py         # propostas de ação: expiram, valem uma vez e só gravam com o clique em Confirmar
│   ├── connectors/        # canvas, gmail, gcalendar, google_auth, brapi, fx, investments, portfolio_write, http, demo
│   └── llm/               # provider.py (camada do Gemini), tools.py (ferramentas), chat.py e briefing.py
├── static/                # index.html, css/hud.css, js/ (módulos ES, sem framework)
├── data/                  # carteira.example.csv (a sua carteira, backups, cache e histórico ficam fora do Git)
├── tests/
├── iniciar.ps1            # prepara o ambiente e abre o painel
├── .env.example
└── requirements.txt
```

## Segurança e privacidade

- O servidor escuta **somente em `127.0.0.1`**; não é acessível por outros dispositivos da rede.
- Requisições com o header `Host` diferente de `127.0.0.1` ou `localhost` são recusadas. Isso protege contra *DNS rebinding*: um site malicioso aberto no seu navegador não consegue ler os dados do painel.
- Requisições que alteram algo (chat, confirmar ou cancelar uma ação) vindas de outros sites são bloqueadas.
- A interface nunca cita nomes de arquivos (`.env`, `carteira.csv`...) nem de variáveis de configuração. Quando falta algo, o painel mostra uma mensagem genérica, e o terminal diz exatamente o que configurar e onde.
- Todo texto vindo das fontes é inserido na página como texto puro, nunca como HTML. Um e-mail com código malicioso no assunto não é executado.
- Chaves e tokens ficam só no `.env`, que o `.gitignore` exclui, assim como `credentials.json`, `token.json`, a pasta `data/` e bancos SQLite.
- **Logs sem segredos:** tokens vão no header `Authorization`, nunca na URL, e as mensagens de erro são escritas sem URLs (o link do feed iCal contém um segredo). Além disso, um filtro troca por `***` qualquer chave ou token configurado que apareça num log do terminal, inclusive em mensagens de erro detalhadas. As bibliotecas de rede só registram avisos, para não listarem as URLs acessadas.
- **Erros contidos:** um erro inesperado derruba só o painel em que aconteceu. A interface mostra uma mensagem curta, e os detalhes (já filtrados) ficam no terminal.
- As integrações leem dados por um cliente HTTP que recusa qualquer método diferente de GET antes de a requisição sair do computador. A única escrita externa, criar evento, usa outro cliente, que só aceita `POST` no endereço de criação de eventos da agenda principal. Editar ou apagar eventos e tocar no Gmail são bloqueados antes de sair da máquina. No Google, o Gmail é só leitura (`gmail.readonly`).
- **Ações com confirmação:** a IA só propõe. Gravar exige o clique em Confirmar, que chama uma rota protegida contra outros sites. A proposta vive só na memória do servidor, com identificador aleatório, expira em 5 minutos e vale uma vez. O ativo só é gravado com a aba privada desbloqueada, e o efeito dele na carteira nunca aparece fora dela nem é enviado à IA.
- O login do Google acontece no seu navegador, direto com o Google; o painel nunca vê a sua senha. O acesso salvo (`token.json`) fica fora do Git e pode ser revogado apagando o arquivo.
- O cache (`data/cache.sqlite3`) guarda só o que aparece nos painéis e fica fora do Git.
- **IA:** só é chamada com `GEMINI_API_KEY` configurada. As ferramentas enviam ao Gemini um resumo mínimo dos dados, e a carteira vai só em percentuais (veja [IA (Google Gemini)](#ia-google-gemini)). As instruções do modelo mandam ignorar comandos escritos em assuntos de e-mail ou títulos de eventos. Mesmo que um e-mail tente manipular a IA, ela só consegue ler e propor: nada é gravado sem o seu clique. A conversa fica só na memória do servidor e some ao reiniciar.
- **Voz:** no Chrome e no Edge, o reconhecimento de fala envia o áudio ao serviço online do próprio navegador (Google ou Microsoft). A síntese de fala usa as vozes do Windows ou do navegador.

## Decisões técnicas

- **Um envelope para todo painel** (`PanelResponse`): `status` (`ok`, `not_configured` ou `error`), origem, horário e dados. É o que permite a cada painel falhar sozinho, inclusive diante de erros inesperados.
- **Os dados de demonstração usam os mesmos modelos que os dados reais.** Trocar de modo muda só a origem dos dados em `sources.py`; as rotas e a interface são as mesmas.
- **Cálculos da carteira nos modelos** (`computed_field`): valor de mercado, resultado sobre o preço médio, variação do dia e distribuição por tipo ficam num só lugar, testado.
- **Briefing por regras + IA:** as regras cruzam as fontes (prazo apertado + e-mail do professor + agenda até o prazo) e sempre geram os destaques do painel. A IA redige o texto a partir de um resumo das mesmas fontes, numa única requisição sem ferramentas. As regras continuam como plano B quando a cota acaba.
- **Camada de IA trocável** (`app/llm/provider.py`): o resto do app só conhece `Tool`, `Turn`, `Reply` e o método `run`. O laço de ferramentas fica dentro do provedor, porque cada API tem o próprio formato (o Gemini exige devolver as "assinaturas de pensamento" intactas). Trocar pelo Groq ou pelo Ollama é escrever outra classe com o mesmo método.
- **Gemini sem estado:** o assistente usa `models.generate_content` e reenvia o histórico a cada pergunta, em vez da API de interações, que guardaria a conversa nos servidores do Google. As novas tentativas automáticas do SDK ficam desligadas, porque cada tentativa gastaria cota.
- **Propor em vez de agir:** as ferramentas de escrita da IA só criam uma proposta. A execução fica em rotas que só o clique na interface chama, então nenhuma resposta da IA, por voz ou texto, consegue gravar algo.
- **Canvas pelo planner:** `/api/v1/planner/items` traz numa só lista tarefas, quizzes e fóruns avaliados, com prazo e situação da entrega, o que evita cruzar `todo` e `upcoming_events`. Os nomes das disciplinas vêm de `/api/v1/courses` e ficam 12 horas no cache. A paginação segue o header `Link`, só dentro do domínio do Canvas.
- **Cache com reserva:** cada fonte guarda a última resposta boa. Se a API cair, o painel mostra os dados antigos com um aviso, em vez de um erro.
- **Uma busca por vez:** um lock por conector evita que o painel e o briefing, pedindo os mesmos dados ao mesmo tempo, gastem duas requisições.
- **Tom e visual inspirados, não copiados:** o assistente fala como um mordomo educado e direto, com frases próprias. O núcleo usa a linguagem visual de HUD (anéis concêntricos, varredura de radar, anel de barras como visualizador de voz), desenhada em canvas. A voz preferida é uma voz masculina gratuita já disponível no Edge ou no Windows; nenhuma voz real é imitada.
- **"Reagir ao áudio":** a `speechSynthesis` não expõe o áudio gerado. O núcleo reage aos eventos de palavra da fala, somados a uma modulação sintética para as vozes que não emitem esses eventos.
