# robot-secretary

Assistente pessoal integrado ao Telegram, Google Calendar e Google Sheets.

## O que mudou

O bot antigo consultava a agenda usando `datetime.utcnow()` e `timeMin=agora`. Isso podia esconder compromissos do começo do dia e eventos de dia inteiro, principalmente quando voce esperava um resumo da agenda de hoje.

Agora o lembrete diario consulta a janela completa do dia no fuso `America/Sao_Paulo` por padrao. Tambem existe um modo de diagnostico para conferir ambiente, janela consultada e eventos encontrados.

## Variaveis de ambiente

Obrigatorias para enviar lembretes e responder comandos de agenda:

```bash
TELEGRAM_TOKEN=token_do_bot
CHAT_ID=id_do_chat
GOOGLE_CREDENTIALS='{"type":"service_account",...}'
```

Obrigatoria para registrar `/gasto` e `/ganho`:

```bash
SHEET_ID=id_da_planilha_google
```

Opcionais:

```bash
CALENDAR_ID=ederbarreto41@gmail.com
TIMEZONE=America/Sao_Paulo
SHEET_NAME=Controle Financeiro
TELEGRAM_OFFSET_FILE=.telegram_offset
```

Voce tambem pode usar `GOOGLE_CREDENTIALS_FILE=/caminho/credentials.json` em vez de `GOOGLE_CREDENTIALS`.

## Aba e colunas da planilha

Por padrao o bot grava na aba **Controle Financeiro** (mude com `SHEET_NAME`). A aba precisa ter uma linha de cabecalho com as colunas, em qualquer ordem, contendo pelo menos **Data** e **Valor**. O bot reconhece tambem **Descricao**, **Categoria**, **Tipo** e **Hora**.

O cabecalho nao precisa estar na linha 1: pode haver titulo e um bloco de resumo (Receitas/Despesas/Saldo) acima dele. O bot localiza a tabela pelos nomes das colunas e escreve na primeira linha livre abaixo.

Ao registrar, o bot grava `Tipo` como **Receita** (entradas) ou **Despesa** (saidas), `Valor` como numero positivo e `Data` como `dd/mm/aaaa`. Assim suas formulas de resumo (ex: SOMASE por Tipo) somam automaticamente.

## Permissoes no Google

Compartilhe sua agenda com o e-mail da service account.

Para apenas ler lembretes, permissao de leitura basta. Para criar eventos pelo bot, a service account precisa poder editar a agenda.

Para registrar gastos e ganhos, compartilhe a Google Sheet com a service account como **editora** e defina `SHEET_ID`. Habilite tambem a **Google Sheets API** no projeto do Google Cloud.

## Instalar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Rodar

Diagnostico:

```bash
python3 main.py diagnose
```

Enviar o lembrete diario:

```bash
python3 main.py reminder
```

Processar comandos recebidos no Telegram uma vez:

```bash
python3 main.py bot
```

Manter o bot escutando comandos:

```bash
python3 main.py bot --watch
```

Escutar por um tempo limitado e encerrar (usado pelo GitHub Actions):

```bash
python3 main.py bot --watch --interval 3 --max-runtime 300
```

## Comandos no Telegram

```text
/hoje
/proximos
/evento Reuniao com cliente | 06/06/2026 15:00 | 60 | pauta inicial
/evento Folga | 07/06/2026
/gasto 42,50 Mercado | Alimentacao
/ganho 2500 Salario | Trabalho
/saldo
/saldo 05/2026
/extrato
/apagar 12
```

Eventos com horario usam duracao em minutos. Eventos apenas com data viram eventos de dia inteiro.

`/saldo` soma entradas e saidas do mes (ou de um mes especifico). `/extrato` lista os ultimos lancamentos numerados pela linha da planilha. `/apagar <numero>` remove a linha indicada pelo `/extrato`.

### Linguagem natural

Alem dos comandos com barra, o bot tambem entende frases soltas:

```text
gastei 50 no mercado          -> registra um gasto de R$ 50
paguei R$ 1.234,56 aluguel    -> registra um gasto de R$ 1234,56
recebi 2000 de salario        -> registra um ganho de R$ 2000
reuniao com cliente amanha 15h -> cria um evento amanha as 15:00
```

A interpretacao e baseada em palavras-chave (gastei/paguei/comprei, recebi/ganhei, e termos de agenda como reuniao/consulta com uma data/hora). Quando ela falha, use o comando com barra correspondente.

## GitHub Actions

Há dois workflows:

`.github/workflows/daily-reminder.yml` roda todo dia as 10:00 UTC (aprox. 07:00 em `America/Sao_Paulo`) e envia a agenda do dia.

`.github/workflows/bot.yml` (Secretaria - responder comandos) funciona de forma **assincrona**: voce manda os comandos quando quiser e o bot responde no proximo horario agendado.

- **Horarios fixos:** o bot acorda as **09:00, 12:00, 15:00, 18:00 e 21:00** (horario de Brasilia), processa tudo o que voce enviou desde a ultima vez e confirma cada registro (ex: *"Gasto registrado: R$ 50,00 - mercado"*). Para mudar os horarios, edite os `cron` em `bot.yml` (estao em UTC; Brasilia = UTC-3).
- **Teste / forcar agora:** na aba *Actions* do GitHub, abra *Secretaria - responder comandos* e clique em *Run workflow*. O bot escuta por ~5 minutos; mande um comando no Telegram e a resposta chega na hora.

Como o offset do Telegram e confirmado a cada execucao, mensagens ja processadas nao sao respondidas de novo no horario seguinte.

### Confirmacoes

Cada lancamento recebe uma confirmacao detalhada, por exemplo:

```text
✅ Gasto registrado
💸 R$ 1.234,56 — aluguel
🏷️ Casa
🕒 14/06 09:00
```

Quando voce envia varias mensagens na mesma janela, ao final o bot manda um resumo:

```text
📋 Resumo da janela
💸 2 gasto(s): R$ 1.284,56
💰 1 ganho(s): R$ 2.000,00
📅 1 evento(s)
➡️ Saldo no periodo: R$ 715,44
```

Atencao ao custo: em repositorio privado o GitHub da 2000 minutos gratis por mes. Com 5 execucoes curtas por dia o consumo e baixo (cabe folgado nos 2000). Em repositorio publico os minutos sao ilimitados. O GitHub pode atrasar execucoes agendadas em alguns minutos em horarios de pico. Se um dia precisar de resposta instantanea, considere hospedar `python main.py bot --watch` em um servico como Railway, Render ou Fly.io.

Configure estes secrets no GitHub:

```text
TELEGRAM_TOKEN
CHAT_ID
GOOGLE_CREDENTIALS
```

Para usar `/gasto`, `/ganho`, `/saldo` e `/extrato`, configure tambem:

```text
SHEET_ID
```

Se quiser sobrescrever a agenda ou o fuso, configure tambem:

```text
CALENDAR_ID
TIMEZONE
SHEET_NAME
```

## Testes

```bash
python3 -m unittest
```
