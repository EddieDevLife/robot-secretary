import os
import json
import requests
import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# O ID correto da sua agenda
CALENDARIO_ID = 'ederbarreto41@gmail.com'

def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("CHAT_ID")
    credenciais_json = os.environ.get("GOOGLE_CREDENTIALS")

    print("Iniciando o Mordomo...")

    try:
        # Lendo o crachá direto do cofre do GitHub (sem precisar de arquivo físico)
        info = json.loads(credenciais_json)
        credenciais = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/calendar.readonly'])
        
        servico = build('calendar', 'v3', credentials=credenciais)
        agora = datetime.datetime.utcnow().isoformat() + 'Z'

        print("Lendo a agenda...")
        eventos_result = servico.events().list(calendarId=CALENDARIO_ID, timeMin=agora,
                                            maxResults=5, singleEvents=True,
                                            orderBy='startTime').execute()
        eventos = eventos_result.get('items', [])

        if not eventos:
            mensagem = "Chefe, bom dia! Olhei a sua agenda e não encontrei compromissos próximos."
        else:
            mensagem = "🗓️ *Bom dia! Seus próximos compromissos e contas:*\n\n"
            for evento in eventos:
                inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                data_curta = inicio[:10]
                ano, mes, dia = data_curta.split('-')
                mensagem += f"🔸 {dia}/{mes}/{ano} - {evento.get('summary', 'Sem título')}\n"

        print("Enviando mensagem para o Telegram...")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": mensagem, "parse_mode": "Markdown"}
        resposta = requests.post(url, data=payload)
        
        if resposta.status_code == 200:
            print("Mensagem enviada com sucesso!")
        else:
            print(f"Erro no Telegram: {resposta.text}")
            
    except Exception as e:
        print(f"Erro no sistema: {e}")

if __name__ == "__main__":
    main()
