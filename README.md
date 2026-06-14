# robot-secretary

Assistente pessoal via Telegram integrado ao Google Calendar e Google Sheets. Roda de graça no GitHub Actions — sem servidor, sem custo fixo.

## O que faz

- Envia um **resumo diário da agenda** às 07:00 (BRT)
- Responde comandos no Telegram para consultar e criar eventos no Google Calendar
- Registra gastos e ganhos em uma Google Sheet e responde consultas de saldo e extrato
- Entende **linguagem natural** além dos comandos com barra

## Comandos no Telegram

```
/hoje                                         lista os eventos de hoje
/proximos                                     próximos 5 eventos
/evento Reunião | 15/06/2026 15:00 | 60       cria evento com duração em minutos
/evento Folga | 16/06/2026                    cria evento de dia inteiro
/gasto 42,50 Mercado | Alimentacao            registra despesa
/ganho 2500 Salario | Trabalho                registra receita
/saldo                                        saldo do mês atual
/saldo 05/2026                                saldo de um mês específico
/extrato                                      últimos lançamentos numerados
/apagar 12                                    remove a linha 12 da planilha
```

O bot também entende frases soltas:

```
gastei 50 no mercado          → registra um gasto de R$ 50
paguei R$ 1.234,56 aluguel    → registra um gasto de R$ 1.234,56
recebi 2000 de salario        → registra um ganho de R$ 2.000
reuniao com cliente amanha 15h → cria evento amanhã às 15:00
```

## Pré-requisitos

1. Um bot no Telegram (via [@BotFather](https://t.me/BotFather))
2. Uma Service Account no Google Cloud com acesso ao **Calendar API** e **Sheets API**
3. Conta do Google Cloud compartilhada com sua agenda e sua planilha

## Configuração do Telegram

Você precisa de duas informações: o **token do bot** e o seu **chat ID**.

1. **Criar o bot:** no Telegram, abra o [@BotFather](https://t.me/BotFather), envie `/newbot` e siga as instruções (nome e usuário do bot). No final ele entrega o **token** — use em `TELEGRAM_TOKEN`.
2. **Iniciar a conversa:** abra o seu novo bot e envie qualquer mensagem (ex: `/start`). Sem isso, o bot não consegue te responder.
3. **Descobrir o chat ID:** envie uma mensagem ao [@userinfobot](https://t.me/userinfobot), que responde com o seu ID numérico — use em `CHAT_ID`. (Alternativa: acesse `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` e copie o valor de `"chat":{"id": ...}`.)
4. **Preencher:** coloque `TELEGRAM_TOKEN` e `CHAT_ID` nas variáveis de ambiente (uso local) ou nos Secrets do repositório (GitHub Actions).

O `CHAT_ID` funciona como uma trava: o bot só responde a esse chat, então ninguém mais consegue usar o seu robô.

## Configuração do Google (Service Account)

A *service account* é a "conta robô" que o bot usa para acessar sua agenda e planilha.

1. **Criar o projeto:** acesse o [Google Cloud Console](https://console.cloud.google.com) e crie (ou escolha) um projeto.
2. **Ativar as APIs:** em *APIs e serviços → Biblioteca*, ative **Google Calendar API** e **Google Sheets API**. (Pular isso causa o erro `SERVICE_DISABLED`.)
3. **Criar a service account:** em *IAM e administrador → Contas de serviço*, clique em *Criar conta de serviço*. Anote o e-mail gerado, no formato `nome@projeto.iam.gserviceaccount.com`.
4. **Gerar a chave JSON:** na conta de serviço, aba *Chaves → Adicionar chave → JSON*. Baixe o arquivo — o conteúdo dele vai em `GOOGLE_CREDENTIALS` (ou aponte o caminho em `GOOGLE_CREDENTIALS_FILE`).
5. **Compartilhar a agenda:** no Google Agenda, *Configurações da agenda → Compartilhar com pessoas específicas*, adicione o e-mail da service account com **"Fazer alterações nos eventos"** (necessário para criar eventos).
6. **Compartilhar a planilha:** abra a Google Sheet, clique em *Compartilhar*, adicione o e-mail da service account como **Editor**, e copie o ID da planilha (da URL) para `SHEET_ID`.

Sem o passo 5 o bot dá erro de *writer access*; sem o passo 6, erro de *caller does not have permission*.

## Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

```bash
# Obrigatórias
TELEGRAM_TOKEN=token_do_bot
CHAT_ID=id_do_seu_chat
GOOGLE_CREDENTIALS='{"type":"service_account",...}'   # JSON da service account

# Para /gasto, /ganho, /saldo e /extrato
SHEET_ID=id_da_sua_planilha

# Opcionais (já têm padrão)
CALENDAR_ID=seu_email@gmail.com
TIMEZONE=America/Sao_Paulo
SHEET_NAME=Controle Financeiro
```

Alternativa: use `GOOGLE_CREDENTIALS_FILE=/caminho/credentials.json` em vez de `GOOGLE_CREDENTIALS`.

## Planilha

A aba (padrão: `Controle Financeiro`) precisa de uma linha de cabeçalho com pelo menos as colunas **Data** e **Valor**. Também reconhece **Descricao**, **Categoria**, **Tipo** e **Hora** em qualquer ordem.

O bot grava `Tipo` como `Receita` ou `Despesa` e `Valor` como número positivo, compatível com fórmulas `SOMASE`.

## Instalação local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Comandos úteis:

```bash
python3 main.py diagnose          # verifica ambiente e mostra eventos encontrados
python3 main.py reminder          # envia o lembrete diário agora
python3 main.py bot               # processa comandos pendentes uma vez
python3 main.py bot --watch       # fica escutando continuamente
```

## GitHub Actions (sem servidor)

Configure os seguintes **Secrets** no repositório (`Settings → Secrets and variables → Actions`):

```
TELEGRAM_TOKEN
CHAT_ID
GOOGLE_CREDENTIALS
SHEET_ID          (para comandos financeiros)
CALENDAR_ID       (opcional)
TIMEZONE          (opcional)
SHEET_NAME        (opcional)
```

Há dois workflows:

**`daily-reminder.yml`** — roda todo dia às 10:00 UTC (07:00 BRT) e envia a agenda do dia.

**`bot.yml`** — modo assíncrono: o bot acorda às **09:00, 12:00, 15:00, 18:00 e 21:00 (BRT)**, processa tudo que você enviou desde a última vez e confirma cada registro. Para disparar na hora, vá em *Actions → Secretaria - responder comandos → Run workflow*.

Em repositório público os minutos do Actions são ilimitados. Em repositório privado, o plano gratuito inclui 2.000 min/mês (suficiente para este uso).

## Testes

```bash
python3 -m unittest
```
