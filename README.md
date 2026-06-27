# 🤖 Robot Secretary

[![status](https://img.shields.io/badge/status-ativo-green)]()
[![python](https://img.shields.io/badge/python-3.10%2B-yellow)]()
[![github-actions](https://img.shields.io/badge/deploy-GitHub_Actions-blue)]()

> **THE HOOK:** Assistente pessoal em linguagem natural integrado ao Telegram, Google Calendar e Sheets. Zero custo de servidor graças à arquitetura serverless orientada a eventos rodando em GitHub Actions.

---

## 🎬 DEMO

![Robot Secretary no Telegram](https://via.placeholder.com/800x400.png?text=Demonstra%C3%A7%C3%A3o+do+Bot+no+Telegram)

*(Exemplo de uso: Envie "gastei 50 no mercado" no Telegram e a linha aparecerá automaticamente na sua Google Sheet financeira).*

---

## 🏗️ ARQUITETURA

O Robot Secretary não roda em um servidor contínuo (24/7). Ele utiliza uma arquitetura baseada em **cron jobs e processamento em lote (batch)**, ideal para tarefas pessoais e de baixo custo.

**Fluxo de Dados:**
1. **Frontend (Telegram):** O usuário envia mensagens em linguagem natural ou comandos estritos (`/ganho`, `/evento`). O Telegram retém essas mensagens pendentes via *Long Polling API*.
2. **Orquestração (GitHub Actions):** Workflows acionam o script Python em horários agendados (ex: 07:00 para agenda, a cada 3h para mensagens).
3. **Processamento (Python):** O script consome as mensagens pendentes da API do Telegram, interpreta a linguagem natural e interage com as APIs do Google.
4. **Armazenamento (Google APIs):** As ações finais são persistidas no Google Calendar (Eventos) e Google Sheets (Finanças).

---

## 🚀 VITÓRIA TÉCNICA E MÉTRICAS

- **Custo Zero (FinOps):** Eliminação de 100% dos custos de cloud para hospedagem de bots (ex: Heroku, EC2). Ao rodar via GitHub Actions sob demanda (cron), o consumo de minutos fica totalmente dentro do free tier (2.000 min/mês em repositórios privados, ilimitado em públicos).
- **Flexibilidade Híbrida (NLU + Regex):** Capacidade de entender tanto comandos determinísticos estruturados (`/evento Reunião | 15/06 15:00`) quanto linguagem natural solta (`reuniao com cliente amanha 15h`), reduzindo a barreira de uso e mantendo robustez onde necessário.

---

## ⚙️ COMO RODAR

### Pré-requisitos
- Bot no Telegram ([@BotFather](https://t.me/BotFather)) e seu respectivo Token e `CHAT_ID`.
- Service Account do Google Cloud com as APIs habilitadas (Calendar API e Sheets API).
- Compartilhar sua Agenda e Planilha com o e-mail da Service Account.

### Instalação (Local para Teste)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Copie o env.example para .env e preencha CHAT_ID, TELEGRAM_TOKEN, e GOOGLE_CREDENTIALS
cp .env.example .env

# Diagnose de ambiente
python3 main.py diagnose

# Rodar para consumir a fila do bot
python3 main.py bot
```

### Deploy (GitHub Actions)
Configure as seguintes secrets em `Settings → Secrets and variables → Actions`:
`TELEGRAM_TOKEN`, `CHAT_ID`, `GOOGLE_CREDENTIALS`, `SHEET_ID`.
Os workflows `daily-reminder.yml` e `bot.yml` cuidarão do resto automaticamente.

---

## 🧠 DOCUMENTAÇÃO DE DECISÕES

- **Por que GitHub Actions e não Webhooks AWS Lambda/GCP?**
  Apesar de Webhooks responderem em tempo real (push), eles exigem configuração de API Gateway e provisionamento de infraestrutura (Terraform). Como um bot pessoal não requer latência de milissegundos para responder "gasto anotado", um modelo de processamento em lotes diários ou horarios no GitHub Actions provou ser a solução arquitetural mais simples e econômica (Zero-Ops).
- **Por que travar o `CHAT_ID`?**
  O bot verifica rigidamente se a mensagem veio do seu `CHAT_ID` configurado. Isso evita ataques e acesso não autorizado aos seus dados financeiros caso alguém descubra o nome de usuário do seu bot no Telegram.

---

## 🔒 ÉTICA, PRIVACIDADE E COMPLIANCE

- **Privacidade By Design:** O bot não tem banco de dados próprio. Todos os seus dados pessoais (Agenda, Gastos) permanecem no seu controle direto sob o ecossistema Google, e não em instâncias do serviço.
- **Autenticação Server-to-Server Segura:** O uso de Google Service Accounts garante autenticação via JSON Key rotacionável sem jamais precisar compartilhar sua senha pessoal do Google. As credenciais nunca são "printadas" nos logs da execução.
