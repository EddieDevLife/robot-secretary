import argparse
import datetime as dt
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build


DEFAULT_CALENDAR_ID = "seu_email@gmail.com"
DEFAULT_TIMEZONE = "America/Sao_Paulo"
DEFAULT_SHEET_NAME = "Controle Financeiro"
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"

# Como a coluna "Tipo" e gravada e reconhecida na planilha.
SHEET_TIPO_INCOME = "Receita"
SHEET_TIPO_EXPENSE = "Despesa"
INCOME_TIPO_WORDS = ("receita", "ganho", "entrada")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets",
]


@dataclass(frozen=True)
class Config:
    telegram_token: str | None
    chat_id: str | None
    calendar_id: str
    timezone_name: str
    sheet_id: str | None
    sheet_name: str
    telegram_offset_file: Path

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            telegram_token=os.environ.get("TELEGRAM_TOKEN"),
            chat_id=os.environ.get("CHAT_ID"),
            calendar_id=os.environ.get("CALENDAR_ID") or DEFAULT_CALENDAR_ID,
            timezone_name=os.environ.get("TIMEZONE") or DEFAULT_TIMEZONE,
            sheet_id=os.environ.get("SHEET_ID"),
            sheet_name=os.environ.get("SHEET_NAME") or DEFAULT_SHEET_NAME,
            telegram_offset_file=Path(
                os.environ.get("TELEGRAM_OFFSET_FILE") or ".telegram_offset"
            ),
        )


class GoogleServices:
    def __init__(self) -> None:
        self._credentials = None
        self._calendar = None
        self._sheets = None

    @property
    def credentials(self):
        if self._credentials is None:
            info = load_google_credentials_info()
            self._credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=GOOGLE_SCOPES,
            )
        return self._credentials

    @property
    def calendar(self):
        if self._calendar is None:
            self._calendar = build(
                "calendar",
                "v3",
                credentials=self.credentials,
                cache_discovery=False,
            )
        return self._calendar

    @property
    def sheets(self):
        if self._sheets is None:
            self._sheets = build(
                "sheets",
                "v4",
                credentials=self.credentials,
                cache_discovery=False,
            )
        return self._sheets


def load_google_credentials_info() -> dict[str, Any]:
    raw_credentials = os.environ.get("GOOGLE_CREDENTIALS")
    credentials_file = os.environ.get("GOOGLE_CREDENTIALS_FILE")

    if raw_credentials:
        return json.loads(raw_credentials)

    if credentials_file:
        with open(credentials_file, encoding="utf-8") as file:
            return json.load(file)

    raise RuntimeError(
        "Defina GOOGLE_CREDENTIALS com o JSON da service account ou "
        "GOOGLE_CREDENTIALS_FILE com o caminho do arquivo."
    )


def require(value: str | None, env_name: str) -> str:
    if not value:
        raise RuntimeError(f"Variavel de ambiente obrigatoria ausente: {env_name}")
    return value


def local_now(config: Config) -> dt.datetime:
    return dt.datetime.now(config.timezone)


def today_window(config: Config, now: dt.datetime | None = None) -> tuple[str, str]:
    current = now or local_now(config)
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=1)
    return start.isoformat(), end.isoformat()


def parse_google_datetime(value: str, config: Config) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        config.timezone
    )


def event_start_label(event: dict[str, Any], config: Config) -> tuple[str, dt.datetime]:
    start = event.get("start", {})

    if "dateTime" in start:
        start_at = parse_google_datetime(start["dateTime"], config)
        return start_at.strftime("%H:%M"), start_at

    if "date" in start:
        event_date = dt.date.fromisoformat(start["date"])
        start_at = dt.datetime.combine(event_date, dt.time.min, tzinfo=config.timezone)
        return "dia todo", start_at

    fallback = local_now(config)
    return "sem horario", fallback


def list_today_events(calendar_service, config: Config) -> list[dict[str, Any]]:
    time_min, time_max = today_window(config)
    result = (
        calendar_service.events()
        .list(
            calendarId=config.calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            timeZone=config.timezone_name,
        )
        .execute()
    )
    return result.get("items", [])


def list_upcoming_events(
    calendar_service,
    config: Config,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    result = (
        calendar_service.events()
        .list(
            calendarId=config.calendar_id,
            timeMin=local_now(config).isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
            timeZone=config.timezone_name,
        )
        .execute()
    )
    return result.get("items", [])


def format_events(
    events: list[dict[str, Any]],
    config: Config,
    heading: str,
) -> str:
    if not events:
        return f"{heading}\n\nNenhum compromisso encontrado."

    lines = [heading, ""]

    for event in events:
        label, start_at = event_start_label(event, config)
        summary = event.get("summary") or "Sem titulo"
        date_label = start_at.strftime("%d/%m/%Y")
        location = event.get("location")
        location_text = f" - {location}" if location else ""
        lines.append(f"- {date_label} {label}: {summary}{location_text}")

    return "\n".join(lines)


def build_daily_reminder_message(calendar_service, config: Config) -> str:
    today = local_now(config).strftime("%d/%m/%Y")
    events = list_today_events(calendar_service, config)

    if events:
        return format_events(
            events,
            config,
            f"Bom dia, chefe. Sua agenda de hoje ({today}):",
        )

    upcoming = list_upcoming_events(calendar_service, config)
    if upcoming:
        return format_events(
            upcoming,
            config,
            f"Bom dia, chefe. Nao encontrei compromissos para hoje ({today}). Proximos:",
        )

    return (
        f"Bom dia, chefe. Olhei a agenda de hoje ({today}) e tambem nao encontrei "
        "compromissos proximos."
    )


def telegram_request(
    token: str,
    method: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = TELEGRAM_API_URL.format(token=token, method=method)

    try:
        if data is not None:
            response = requests.post(url, data=data, timeout=20)
        else:
            response = requests.get(url, params=params, timeout=20)

        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.RequestException as exc:
        # Avoid leaking full URL with token in case of error (requests often includes URL in exception)
        raise RuntimeError(f"Erro na comunicação com Telegram (metodo {method})") from None

    if not payload.get("ok"):
        error_msg = payload.get("description", "Erro desconhecido")
        raise RuntimeError(f"Telegram retornou erro: {error_msg}")

    return payload


def send_telegram_message(token: str, chat_id: str | int, text: str) -> None:
    telegram_request(
        token,
        "sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
    )


def send_daily_reminder(config: Config, services: GoogleServices) -> None:
    token = require(config.telegram_token, "TELEGRAM_TOKEN")
    chat_id = require(config.chat_id, "CHAT_ID")

    print("Lendo agenda do dia...")
    message = build_daily_reminder_message(services.calendar, config)

    print("Enviando lembrete para o Telegram...")
    send_telegram_message(token, chat_id, message)
    print("Mensagem enviada com sucesso.")


def read_offset(path: Path) -> int | None:
    if not path.exists():
        return None

    value = path.read_text(encoding="utf-8").strip()
    return int(value) if value else None


def write_offset(path: Path, offset: int) -> None:
    path.write_text(str(offset), encoding="utf-8")


def fetch_telegram_updates(token: str, offset: int | None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"timeout": 0, "allowed_updates": json.dumps(["message"])}
    if offset is not None:
        params["offset"] = offset

    payload = telegram_request(token, "getUpdates", params=params)
    return payload.get("result", [])


def is_allowed_chat(config: Config, chat_id: int | str) -> bool:
    return not config.chat_id or str(chat_id) == str(config.chat_id)


def normalize_command(text: str) -> tuple[str, str]:
    command, _, args = text.strip().partition(" ")
    return command.split("@", 1)[0].lower(), args.strip()


def help_message(config: Config) -> str:
    sheet_status = "configurada" if config.sheet_id else "nao configurada"
    return "\n".join(
        [
            "Comandos disponiveis:",
            "",
            "/hoje - mostra a agenda de hoje",
            "/proximos - mostra os proximos compromissos",
            "/evento Titulo | 06/06/2026 15:00 | 60 | descricao",
            "/evento Titulo | 06/06/2026",
            "/gasto 42,50 Mercado | Alimentacao",
            "/ganho 2500 Salario | Trabalho",
            "/saldo - resumo de entradas e saidas do mes",
            "/saldo 05/2026 - resumo de um mes especifico",
            "/extrato - mostra os ultimos lancamentos",
            "/apagar <numero> - apaga um lancamento (veja o numero no /extrato)",
            "",
            "Tambem entendo frases soltas, por exemplo:",
            "- gastei 50 no mercado",
            "- recebi 2000 de salario",
            "- reuniao com cliente amanha 15h",
            "",
            f"Planilha: {sheet_status}.",
        ]
    )


def parse_local_date_or_datetime(
    value: str,
    config: Config,
    now: dt.datetime | None = None,
) -> tuple[dt.datetime, bool]:
    current = now or local_now(config)
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    day_words = {
        "hoje": current.strftime("%d/%m/%Y"),
        "amanha": (current + dt.timedelta(days=1)).strftime("%d/%m/%Y"),
        "amanhã": (current + dt.timedelta(days=1)).strftime("%d/%m/%Y"),
    }
    for word, replacement in day_words.items():
        if cleaned == word or cleaned.startswith(f"{word} "):
            cleaned = cleaned.replace(word, replacement, 1)
            break

    datetime_formats = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%y %H:%M",
        "%d/%m %H:%M",
        "%Y-%m-%d %H:%M",
    ]

    date_formats = [
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d/%m",
        "%Y-%m-%d",
    ]

    for date_format in datetime_formats:
        try:
            parse_value = cleaned
            parse_format = date_format
            if "%Y" not in date_format and "%y" not in date_format:
                parse_value = f"{cleaned} {current.year}"
                parse_format = f"{date_format} %Y"
            parsed = dt.datetime.strptime(parse_value, parse_format)
            return parsed.replace(tzinfo=config.timezone), False
        except ValueError:
            pass

    for date_format in date_formats:
        try:
            parse_value = cleaned
            parse_format = date_format
            if "%Y" not in date_format and "%y" not in date_format:
                parse_value = f"{cleaned}/{current.year}"
                parse_format = f"{date_format}/%Y"
            parsed_date = dt.datetime.strptime(parse_value, parse_format)
            start = parsed_date.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
                tzinfo=config.timezone,
            )
            return start, True
        except ValueError:
            pass

    raise ValueError(
        "Use uma data como 06/06/2026, 06/06/2026 15:00 ou 2026-06-06 15:00."
    )


def parse_duration(value: str | None) -> int:
    if not value:
        return 60

    try:
        duration = int(value.strip())
    except ValueError as exc:
        raise ValueError("A duracao precisa ser um numero em minutos.") from exc

    if duration <= 0:
        raise ValueError("A duracao precisa ser maior que zero.")

    return duration


def create_calendar_event(
    calendar_service,
    config: Config,
    args: str,
) -> dict[str, Any]:
    parts = [part.strip() for part in args.split("|")]

    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(
            "Use: /evento Titulo | 06/06/2026 15:00 | 60 | descricao"
        )

    title = parts[0]
    starts_at, all_day = parse_local_date_or_datetime(parts[1], config)
    duration_minutes = parse_duration(parts[2] if len(parts) > 2 and parts[2] else None)
    description = parts[3] if len(parts) > 3 else None

    event: dict[str, Any] = {"summary": title}
    if description:
        event["description"] = description

    if all_day:
        end_date = starts_at.date() + dt.timedelta(days=1)
        event["start"] = {"date": starts_at.date().isoformat()}
        event["end"] = {"date": end_date.isoformat()}
    else:
        ends_at = starts_at + dt.timedelta(minutes=duration_minutes)
        event["start"] = {
            "dateTime": starts_at.isoformat(),
            "timeZone": config.timezone_name,
        }
        event["end"] = {
            "dateTime": ends_at.isoformat(),
            "timeZone": config.timezone_name,
        }

    return (
        calendar_service.events()
        .insert(calendarId=config.calendar_id, body=event)
        .execute()
    )


EXPENSE_WORDS = (
    "gastei",
    "paguei",
    "comprei",
    "gasto",
    "despesa",
    "saiu",
    "saida",
    "saída",
)
INCOME_WORDS = (
    "recebi",
    "ganhei",
    "entrou",
    "ganho",
    "receita",
    "salario",
    "salário",
    "entrada",
)
MONEY_PATTERN = re.compile(r"(?:R\$\s*)?\d[\d.,]*")
# So removemos os verbos-gatilho e conectores da descricao. Substantivos como
# "salario" ou "aluguel" sao mantidos por serem a propria descricao.
STOPWORDS_FOR_DESCRIPTION = {
    "gastei",
    "paguei",
    "comprei",
    "recebi",
    "ganhei",
    "entrou",
    "saiu",
    "de",
    "do",
    "da",
    "no",
    "na",
    "em",
    "com",
    "reais",
    "real",
    "pila",
    "conto",
    "r$",
    "hoje",
    "amanha",
    "amanhã",
}


def interpret_natural_language(text: str, config: Config) -> tuple[str, str] | None:
    """Tenta transformar uma frase livre em um comando conhecido.

    Retorna uma tupla (comando, argumentos) ou None se nao reconhecer.
    """
    lowered = text.strip().lower()
    if not lowered:
        return None

    has_expense = any(word in lowered for word in EXPENSE_WORDS)
    has_income = any(word in lowered for word in INCOME_WORDS)
    money_match = MONEY_PATTERN.search(text)

    # Lancamento financeiro: precisa de uma palavra-chave e de um valor.
    if (has_expense or has_income) and money_match:
        amount_text = money_match.group(0)
        # Monta a descricao com as palavras restantes, sem os termos-chave.
        without_amount = (
            text[: money_match.start()] + " " + text[money_match.end():]
        )
        words = [
            word
            for word in re.split(r"\s+", without_amount.strip())
            if word and word.lower() not in STOPWORDS_FOR_DESCRIPTION
        ]
        description = " ".join(words).strip() or "Lancamento"
        # Gasto tem prioridade quando ha ambiguidade ("paguei meu salario" e raro).
        command = "/gasto" if has_expense else "/ganho"
        return command, f"{amount_text} {description}"

    # Agendamento: presenca de uma data/hora reconhecivel sugere um evento.
    if looks_like_event(lowered, config):
        return "/evento", build_event_args_from_text(text, config)

    return None


EVENT_WORDS = (
    "reuniao",
    "reunião",
    "consulta",
    "compromisso",
    "marcar",
    "marca",
    "marque",
    "agendar",
    "agenda",
    "evento",
    "encontro",
    "call",
    "dentista",
    "medico",
    "médico",
    "aula",
    "prova",
    "exame",
    "treino",
    "academia",
    "missa",
    "culto",
    "entrevista",
    "viagem",
    "voo",
    "festa",
    "aniversario",
    "aniversário",
    "jantar",
    "almoco",
    "almoço",
    "cafe",
    "café",
    "trabalho",
    "plantao",
    "plantão",
    "reuniao",
)

# Hora no formato 15:00, 15h, 15h30 ou "15 horas".
TIME_PATTERN = re.compile(r"\b(\d{1,2})(?::(\d{2})|\s*h(\d{2})?|\s*horas?)\b")


def _contains_time(text: str) -> bool:
    return bool(TIME_PATTERN.search(text))


def looks_like_event(lowered: str, config: Config) -> bool:
    has_event_word = any(word in lowered for word in EVENT_WORDS)
    has_date = _contains_parseable_date(lowered, config)
    has_time = _contains_time(lowered)
    # Evento se: ha palavra de agenda com data, OU ha data e horario juntos
    # (ex: "ingles hoje as 20:00"), o que ja e um forte sinal de agendamento.
    return has_date and (has_event_word or has_time)


def _contains_parseable_date(lowered: str, config: Config) -> bool:
    # Datas explicitas (06/06, 2026-06-06) ou palavras relativas.
    if re.search(r"\d{1,2}/\d{1,2}", lowered):
        return True
    if re.search(r"\d{4}-\d{2}-\d{2}", lowered):
        return True
    if re.search(r"\b(hoje|amanha|amanhã)\b", lowered):
        return True
    return False


def build_event_args_from_text(text: str, config: Config) -> str:
    """Extrai titulo, data e hora de uma frase para o formato do /evento."""
    lowered = text.lower()

    # Captura uma data: dd/mm(/aaaa) ou aaaa-mm-dd ou hoje/amanha.
    date_token = None
    date_match = re.search(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", text)
    iso_match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    rel_match = re.search(r"\b(hoje|amanha|amanhã)\b", lowered)
    if date_match:
        date_token = date_match.group(0)
    elif iso_match:
        date_token = iso_match.group(0)
    elif rel_match:
        date_token = rel_match.group(1)

    # Captura uma hora: 15:00, 15h, 15h30, "15 horas".
    time_token = None
    time_match = TIME_PATTERN.search(text)
    if time_match:
        hour = int(time_match.group(1))
        minutes = time_match.group(2) or time_match.group(3) or "00"
        time_token = f"{hour:02d}:{int(minutes):02d}"

    when = " ".join(token for token in [date_token, time_token] if token).strip()

    # O titulo e o texto sem os termos de tempo e sem conectores comuns.
    title_source = text
    for pattern in [
        r"\d{1,2}/\d{1,2}(?:/\d{2,4})?",
        r"\d{4}-\d{2}-\d{2}",
        r"\b\d{1,2}:\d{2}\b",          # 20:00 (relogio completo primeiro)
        r"\b\d{1,2}\s*h\d{2}\b",       # 20h30
        r"\b\d{1,2}\s*h\b",            # 20h
        r"\b\d{1,2}\s*horas?\b",       # 20 horas
        r"\bhoras?\b",
        r"\b(hoje|amanha|amanhã)\b",
        r"\b(as|às|dia|para|pra|no|na|de|do|da)\b",
        r"\b(tenho|tem|marcar|marca|agendar|agenda|marque)\b",
    ]:
        title_source = re.sub(pattern, " ", title_source, flags=re.IGNORECASE)
    title = re.sub(r"[:]+", " ", title_source)
    title = re.sub(r"\s+", " ", title).strip(" .,-") or "Compromisso"

    return f"{title} | {when}" if when else title


def parse_money(value: str) -> Decimal:
    cleaned = value.replace("R$", "").replace("r$", "").strip()
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")

    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("O valor precisa ser numerico, por exemplo 42,50.") from exc

    if amount <= 0:
        raise ValueError("O valor precisa ser maior que zero.")

    return amount


def parse_transaction_args(args: str) -> tuple[Decimal, str, str]:
    match = re.match(r"\s*(?:R\$\s*)?([0-9.,]+)\s*(.*)", args)
    if not match:
        raise ValueError("Use: /gasto 42,50 Mercado | Alimentacao")

    amount = parse_money(match.group(1))
    remainder = match.group(2).strip()

    if not remainder:
        raise ValueError("Informe uma descricao para o lancamento.")

    description, _, category = remainder.partition("|")
    return amount, description.strip(), category.strip()


def _norm(value: Any) -> str:
    """Normaliza texto: minusculo, sem acento, sem espacos nas bordas."""
    text = str(value or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _is_income(kind: str) -> bool:
    return _norm(kind).startswith(INCOME_TIPO_WORDS)


# Sinonimos de cabecalho aceitos para cada campo da tabela.
HEADER_ALIASES = {
    "data": "data",
    "hora": "hora",
    "tipo": "tipo",
    "valor": "valor",
    "descricao": "descricao",
    "descrição": "descricao",
    "categoria": "categoria",
}


@dataclass(frozen=True)
class SheetTable:
    header_row: int  # linha 1-based do cabecalho
    columns: dict[str, int]  # campo -> indice de coluna (0-based)
    values: list[list[Any]]  # todas as linhas lidas (A1 em diante)


def locate_table(sheets_service, config: Config) -> SheetTable:
    """Encontra a linha de cabecalho da tabela pelos nomes das colunas.

    Funciona mesmo quando a tabela nao comeca na linha 1 (ha titulo/resumo
    acima dela), desde que exista uma linha com 'Data' e 'Valor'.
    """
    sheet_id = require(config.sheet_id, "SHEET_ID")
    result = (
        sheets_service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=f"'{config.sheet_name}'!A1:Z2000")
        .execute()
    )
    values = result.get("values", [])

    for index, row in enumerate(values):
        normalized = [_norm(cell) for cell in row]
        if "data" in normalized and "valor" in normalized:
            columns: dict[str, int] = {}
            for col_index, name in enumerate(normalized):
                field = HEADER_ALIASES.get(name)
                if field and field not in columns:
                    columns[field] = col_index
            return SheetTable(
                header_row=index + 1, columns=columns, values=values
            )

    raise RuntimeError(
        f"Nao encontrei o cabecalho (Data ... Valor) na aba '{config.sheet_name}'. "
        "Confira o nome da aba (SHEET_NAME) e se ela tem essa linha de cabecalho."
    )


def append_transaction(
    sheets_service,
    config: Config,
    transaction_type: str,
    amount: Decimal,
    description: str,
    category: str,
) -> None:
    sheet_id = require(config.sheet_id, "SHEET_ID")
    try:
        table = locate_table(sheets_service, config)
    except Exception as exc:
        raise RuntimeError(f"Nao consegui preparar a planilha: {exc}") from exc

    columns = table.columns
    date_col = columns.get("data", 0)

    # Descobre a proxima linha vazia abaixo do cabecalho (na coluna de data).
    last_filled = table.header_row  # 1-based
    for index in range(table.header_row, len(table.values)):
        row = table.values[index]
        cell = row[date_col] if date_col < len(row) else ""
        if str(cell).strip():
            last_filled = index + 1  # converte indice 0-based em linha 1-based
    next_row = last_filled + 1

    now = local_now(config)
    tipo = SHEET_TIPO_INCOME if transaction_type == "Ganho" else SHEET_TIPO_EXPENSE
    field_values = {
        "data": now.strftime("%d/%m/%Y"),
        "hora": now.strftime("%H:%M"),
        "tipo": tipo,
        "valor": float(amount),
        "descricao": description,
        "categoria": category,
    }

    width = max(columns.values()) + 1
    cells: list[Any] = ["" for _ in range(width)]
    for field, col_index in columns.items():
        if field in field_values:
            cells[col_index] = field_values[field]

    try:
        sheets_service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"'{config.sheet_name}'!A{next_row}",
            valueInputOption="USER_ENTERED",
            body={"values": [cells]},
        ).execute()
    except Exception as exc:
        raise RuntimeError(f"Falha ao salvar na planilha: {exc}") from exc


@dataclass(frozen=True)
class Transaction:
    row_number: int  # linha real na planilha (1-based)
    date: str
    time: str
    kind: str
    amount: Decimal
    description: str
    category: str


def _row_to_amount(raw: Any) -> Decimal:
    if raw is None or raw == "":
        return Decimal("0")
    try:
        return parse_money(str(raw))
    except ValueError:
        return Decimal("0")


def _cell(row: list[Any], columns: dict[str, int], field: str) -> str:
    index = columns.get(field)
    if index is None or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def read_transactions(sheets_service, config: Config) -> list[Transaction]:
    table = locate_table(sheets_service, config)
    columns = table.columns

    transactions: list[Transaction] = []
    for index in range(table.header_row, len(table.values)):
        row = table.values[index]
        date = _cell(row, columns, "data")
        kind = _cell(row, columns, "tipo")
        amount_raw = _cell(row, columns, "valor")
        if not date and not amount_raw:
            continue
        transactions.append(
            Transaction(
                row_number=index + 1,  # linha real na planilha (1-based)
                date=date,
                time=_cell(row, columns, "hora"),
                kind=kind,
                amount=_row_to_amount(amount_raw),
                description=_cell(row, columns, "descricao"),
                category=_cell(row, columns, "categoria"),
            )
        )
    return transactions


def _month_filter(value: str, config: Config) -> tuple[int, int]:
    """Retorna (ano, mes) a partir de um argumento opcional como '06/2026'."""
    cleaned = value.strip()
    if not cleaned:
        now = local_now(config)
        return now.year, now.month

    match = re.match(r"(\d{1,2})[/-](\d{4})", cleaned)
    if match:
        return int(match.group(2)), int(match.group(1))

    match = re.match(r"(\d{4})[/-](\d{1,2})", cleaned)
    if match:
        return int(match.group(1)), int(match.group(2))

    now = local_now(config)
    return now.year, now.month


def _parse_any_date(value: str) -> dt.date | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def build_balance_summary(sheets_service, config: Config, args: str) -> str:
    if not config.sheet_id:
        return "A planilha nao esta configurada (defina SHEET_ID)."

    year, month = _month_filter(args, config)
    transactions = read_transactions(sheets_service, config)

    total_in = Decimal("0")
    total_out = Decimal("0")
    count = 0
    for tx in transactions:
        tx_date = _parse_any_date(tx.date)
        if tx_date is None:
            continue
        if tx_date.year != year or tx_date.month != month:
            continue
        count += 1
        if _is_income(tx.kind):
            total_in += tx.amount
        else:
            total_out += tx.amount

    balance = total_in - total_out
    label = f"{month:02d}/{year}"
    if count == 0:
        return f"Resumo de {label}\n\nNenhum lancamento neste mes."

    return "\n".join(
        [
            f"📊 Resumo de {label}",
            "",
            f"💰 Entradas: {format_brl(total_in)}",
            f"💸 Saidas:   {format_brl(total_out)}",
            f"➡️ Saldo:    {format_brl(balance)}",
            "",
            f"{count} lancamento(s) no mes.",
        ]
    )


def build_statement(sheets_service, config: Config, args: str) -> str:
    if not config.sheet_id:
        return "A planilha nao esta configurada (defina SHEET_ID)."

    limit = 10
    cleaned = args.strip()
    if cleaned.isdigit():
        limit = max(1, min(int(cleaned), 50))

    transactions = read_transactions(sheets_service, config)
    if not transactions:
        return "Nenhum lancamento registrado ainda."

    recent = transactions[-limit:]
    lines = [f"Ultimos {len(recent)} lancamentos:", ""]
    for tx in recent:
        sign = "+" if _is_income(tx.kind) else "-"
        desc = tx.description or "sem descricao"
        cat = f" ({tx.category})" if tx.category else ""
        lines.append(
            f"#{tx.row_number} {tx.date} {sign}{format_brl(tx.amount)} - {desc}{cat}"
        )
    lines.append("")
    lines.append("Para apagar, use /apagar <numero> (ex: /apagar "
                 f"{recent[-1].row_number}).")
    return "\n".join(lines)


def delete_transaction(sheets_service, config: Config, args: str) -> str:
    if not config.sheet_id:
        return "A planilha nao esta configurada (defina SHEET_ID)."

    cleaned = args.strip().lstrip("#")
    if not cleaned.isdigit():
        return "Use /apagar <numero da linha>. Veja os numeros com /extrato."

    row_number = int(cleaned)
    if row_number < 2:
        return "Esse numero nao corresponde a um lancamento valido."

    sheet_id = require(config.sheet_id, "SHEET_ID")
    transactions = read_transactions(sheets_service, config)
    target = next((tx for tx in transactions if tx.row_number == row_number), None)
    if target is None:
        return f"Nao encontrei o lancamento #{row_number}. Confira com /extrato."

    metadata = sheets_service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    numeric_sheet_id = None
    for sheet in metadata.get("sheets", []):
        if sheet["properties"]["title"] == config.sheet_name:
            numeric_sheet_id = sheet["properties"]["sheetId"]
            break
    if numeric_sheet_id is None:
        return "Nao localizei a aba da planilha para apagar."

    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": numeric_sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_number - 1,  # 0-based
                            "endIndex": row_number,
                        }
                    }
                }
            ]
        },
    ).execute()

    desc = target.description or "lancamento"
    return f"Apagado #{row_number}: {target.kind} R$ {target.amount:.2f} - {desc}"


def format_brl(amount: Decimal) -> str:
    """Formata um Decimal no padrao brasileiro: 1234.5 -> 'R$ 1.234,50'."""
    formatted = f"{amount:,.2f}"  # 1,234.50
    swapped = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {swapped}"


@dataclass(frozen=True)
class BotReply:
    text: str
    kind: str = "info"  # gasto | ganho | evento | erro | info
    amount: Decimal | None = None


def _confirm_transaction(
    services: GoogleServices,
    config: Config,
    kind_label: str,
    args: str,
) -> BotReply:
    amount, description, category = parse_transaction_args(args)
    append_transaction(services.sheets, config, kind_label, amount, description, category)

    when = local_now(config).strftime("%d/%m %H:%M")
    icon = "💸" if kind_label == "Gasto" else "💰"
    lines = [
        f"✅ {kind_label} registrado",
        f"{icon} {format_brl(amount)} — {description}",
    ]
    if category:
        lines.append(f"🏷️ {category}")
    lines.append(f"🕒 {when}")
    return BotReply(
        "\n".join(lines),
        kind="gasto" if kind_label == "Gasto" else "ganho",
        amount=amount,
    )


def dispatch_command(
    command: str,
    args: str,
    chat_id: int,
    config: Config,
    services: GoogleServices,
) -> BotReply | None:
    """Executa um comando conhecido. Retorna None se nao reconhecer."""
    if command in {"/start", "/help", "/ajuda"}:
        return BotReply(help_message(config))

    if command in {"/hoje", "/agenda"}:
        return BotReply(build_daily_reminder_message(services.calendar, config))

    if command in {"/proximos", "/proximos_eventos"}:
        events = list_upcoming_events(services.calendar, config)
        return BotReply(format_events(events, config, "Proximos compromissos:"))

    if command in {"/evento", "/add_event", "/compromisso"}:
        event = create_calendar_event(services.calendar, config, args)
        summary = event.get("summary", "Sem titulo")
        _, start_at = event_start_label(event, config)
        when = start_at.strftime("%d/%m/%Y %H:%M")
        link = event.get("htmlLink")
        lines = [
            "✅ Evento criado",
            f"📅 {summary}",
            f"🕒 {when}",
        ]
        if link:
            lines.append(f"🔗 {link}")
        return BotReply("\n".join(lines), kind="evento")

    if command in {"/gasto", "/despesa"}:
        return _confirm_transaction(services, config, "Gasto", args)

    if command in {"/ganho", "/receita"}:
        return _confirm_transaction(services, config, "Ganho", args)

    if command in {"/saldo", "/resumo", "/mes", "/mês"}:
        return BotReply(build_balance_summary(services.sheets, config, args))

    if command in {"/extrato", "/ultimos", "/últimos", "/lancamentos"}:
        return BotReply(build_statement(services.sheets, config, args))

    if command in {"/apagar", "/remover", "/excluir"}:
        return BotReply(delete_transaction(services.sheets, config, args))

    return None


def handle_telegram_text(
    text: str,
    chat_id: int,
    config: Config,
    services: GoogleServices,
) -> BotReply:
    command, args = normalize_command(text)

    response = dispatch_command(command, args, chat_id, config, services)
    if response is not None:
        return response

    # Nao foi um comando reconhecido: tenta entender linguagem natural.
    if not command.startswith("/"):
        interpreted = interpret_natural_language(text, config)
        if interpreted is not None:
            new_command, new_args = interpreted
            fallback = dispatch_command(
                new_command, new_args, chat_id, config, services
            )
            if fallback is not None:
                return fallback

    return BotReply(
        "🤔 Nao entendi essa mensagem.\n\n" + help_message(config),
        kind="info",
    )


def build_window_summary(counters: dict[str, Any]) -> str | None:
    """Monta o resumo enviado ao fim de uma janela com varios lancamentos."""
    gastos = counters["gastos"]
    ganhos = counters["ganhos"]
    eventos = counters["eventos"]
    erros = counters["erros"]
    registros = gastos["n"] + ganhos["n"] + eventos

    # So vale a pena resumir quando houve mais de uma acao na janela.
    if registros + erros < 2:
        return None

    lines = ["📋 Resumo da janela"]
    if gastos["n"]:
        lines.append(
            f"💸 {gastos['n']} gasto(s): {format_brl(gastos['total'])}"
        )
    if ganhos["n"]:
        lines.append(
            f"💰 {ganhos['n']} ganho(s): {format_brl(ganhos['total'])}"
        )
    if eventos:
        lines.append(f"📅 {eventos} evento(s)")
    if gastos["n"] or ganhos["n"]:
        saldo = ganhos["total"] - gastos["total"]
        lines.append(f"➡️ Saldo no periodo: {format_brl(saldo)}")
    if erros:
        lines.append(f"⚠️ {erros} mensagem(ns) nao entendida(s)")
    return "\n".join(lines)


def process_telegram_updates(config: Config, services: GoogleServices) -> int:
    token = require(config.telegram_token, "TELEGRAM_TOKEN")
    offset = read_offset(config.telegram_offset_file)
    
    try:
        updates = fetch_telegram_updates(token, offset)
    except Exception as exc:
        print(f"Erro ao buscar atualizacoes: {exc}")
        return 0

    processed = 0
    last_chat_id: int | str | None = None
    counters: dict[str, Any] = {
        "gastos": {"n": 0, "total": Decimal("0")},
        "ganhos": {"n": 0, "total": Decimal("0")},
        "eventos": 0,
        "erros": 0,
    }

    for update in updates:
        next_offset = update["update_id"] + 1
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = message.get("text")

        if chat_id and text and is_allowed_chat(config, chat_id):
            print(f"Processando comando de {chat_id}: {text.split()[0]}")
            try:
                reply = handle_telegram_text(text, int(chat_id), config, services)
            except Exception as exc:
                print(f"Erro ao processar comando '{text}': {exc}")
                reply = BotReply(
                    f"⚠️ Tive um problema ao processar isso: {exc}", kind="erro"
                )

            # Acumula para o resumo da janela.
            if reply.kind == "gasto" and reply.amount is not None:
                counters["gastos"]["n"] += 1
                counters["gastos"]["total"] += reply.amount
            elif reply.kind == "ganho" and reply.amount is not None:
                counters["ganhos"]["n"] += 1
                counters["ganhos"]["total"] += reply.amount
            elif reply.kind == "evento":
                counters["eventos"] += 1
            elif reply.kind == "erro":
                counters["erros"] += 1

            try:
                send_telegram_message(token, chat_id, reply.text)
                processed += 1
                last_chat_id = chat_id
            except Exception as exc:
                print(f"Erro ao enviar resposta: {exc}")

        # Sempre atualiza o offset para não entrar em loop infinito com mensagem problemática
        write_offset(config.telegram_offset_file, next_offset)

    # Resumo da janela quando houve varias acoes (interacao assincrona).
    if last_chat_id is not None:
        summary = build_window_summary(counters)
        if summary:
            try:
                send_telegram_message(token, last_chat_id, summary)
            except Exception as exc:
                print(f"Erro ao enviar resumo da janela: {exc}")

    if processed > 0:
        print(f"Total de comandos processados: {processed}")
    return processed


def run_diagnostics(config: Config, services: GoogleServices) -> None:
    print("Diagnostico do Mordomo")
    print(f"TELEGRAM_TOKEN: {'ok' if config.telegram_token else 'ausente'}")
    print(f"CHAT_ID: {'ok' if config.chat_id else 'ausente'}")
    print(
        "GOOGLE_CREDENTIALS: "
        f"{'ok' if os.environ.get('GOOGLE_CREDENTIALS') else 'ausente'}"
    )
    print(
        "GOOGLE_CREDENTIALS_FILE: "
        f"{'ok' if os.environ.get('GOOGLE_CREDENTIALS_FILE') else 'ausente'}"
    )
    print(f"CALENDAR_ID: {config.calendar_id}")
    print(f"TIMEZONE: {config.timezone_name}")
    print(f"SHEET_ID: {'ok' if config.sheet_id else 'ausente'}")
    print("")

    time_min, time_max = today_window(config)
    print(f"Janela consultada para hoje: {time_min} ate {time_max}")

    today_events = list_today_events(services.calendar, config)
    print(f"Eventos encontrados hoje: {len(today_events)}")
    for event in today_events:
        label, start_at = event_start_label(event, config)
        print(
            f"- {start_at.strftime('%d/%m/%Y')} {label}: "
            f"{event.get('summary', 'Sem titulo')}"
        )

    upcoming_events = list_upcoming_events(services.calendar, config)
    print(f"Eventos proximos a partir de agora: {len(upcoming_events)}")
    for event in upcoming_events:
        label, start_at = event_start_label(event, config)
        print(
            f"- {start_at.strftime('%d/%m/%Y')} {label}: "
            f"{event.get('summary', 'Sem titulo')}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mordomo pessoal para Telegram.")
    parser.add_argument(
        "mode",
        nargs="?",
        default="reminder",
        choices=["reminder", "bot", "diagnose", "diagnostico"],
        help="reminder envia o lembrete diario; bot processa comandos; diagnose verifica config.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="No modo bot, continua procurando comandos.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Intervalo em segundos entre buscas no modo bot --watch.",
    )
    parser.add_argument(
        "--max-runtime",
        type=int,
        default=0,
        help=(
            "No modo bot --watch, encerra apos N segundos. "
            "0 significa rodar indefinidamente. Util no GitHub Actions."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = Config.from_env()
    services = GoogleServices()

    print("Iniciando o Mordomo...")

    if args.mode == "reminder":
        send_daily_reminder(config, services)
        return

    if args.mode in {"diagnose", "diagnostico"}:
        run_diagnostics(config, services)
        return

    if args.mode == "bot":
        if args.watch:
            deadline = (
                time.monotonic() + args.max_runtime if args.max_runtime > 0 else None
            )
            print(
                "Escutando comandos"
                + (f" por ate {args.max_runtime}s..." if deadline else "...")
            )
            while True:
                process_telegram_updates(config, services)
                if deadline is not None and time.monotonic() >= deadline:
                    print("Tempo limite atingido. Encerrando ate a proxima rodada.")
                    break
                time.sleep(max(args.interval, 1))
        else:
            process_telegram_updates(config, services)


if __name__ == "__main__":
    main()
