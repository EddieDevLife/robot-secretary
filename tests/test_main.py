import dataclasses
import datetime as dt
import unittest
from decimal import Decimal
from pathlib import Path

from main import (
    BotReply,
    Config,
    build_window_summary,
    format_brl,
    handle_telegram_text,
    interpret_natural_language,
    parse_local_date_or_datetime,
    parse_money,
    parse_transaction_args,
    today_window,
)


class MainParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(
            telegram_token=None,
            chat_id=None,
            calendar_id="calendar@example.com",
            timezone_name="America/Sao_Paulo",
            sheet_id=None,
            sheet_name="Lancamentos",
            telegram_offset_file=Path(".telegram_offset.test"),
        )
        self.now = dt.datetime(2026, 6, 5, 8, 30, tzinfo=self.config.timezone)

    def test_today_window_uses_local_day(self) -> None:
        start, end = today_window(self.config, self.now)

        self.assertEqual(start, "2026-06-05T00:00:00-03:00")
        self.assertEqual(end, "2026-06-06T00:00:00-03:00")

    def test_parse_date_only_event(self) -> None:
        starts_at, all_day = parse_local_date_or_datetime(
            "06/06/2026",
            self.config,
            self.now,
        )

        self.assertTrue(all_day)
        self.assertEqual(starts_at.isoformat(), "2026-06-06T00:00:00-03:00")

    def test_parse_relative_datetime(self) -> None:
        starts_at, all_day = parse_local_date_or_datetime(
            "amanha 15:00",
            self.config,
            self.now,
        )

        self.assertFalse(all_day)
        self.assertEqual(starts_at.isoformat(), "2026-06-06T15:00:00-03:00")

    def test_parse_money_accepts_decimal_dot(self) -> None:
        self.assertEqual(parse_money("25.90"), Decimal("25.90"))

    def test_parse_money_accepts_brazilian_format(self) -> None:
        self.assertEqual(parse_money("1.234,56"), Decimal("1234.56"))

    def test_parse_transaction_args(self) -> None:
        amount, description, category = parse_transaction_args(
            "42,50 Mercado | Alimentacao"
        )

        self.assertEqual(amount, Decimal("42.50"))
        self.assertEqual(description, "Mercado")
        self.assertEqual(category, "Alimentacao")

    def test_natural_language_expense(self) -> None:
        result = interpret_natural_language("gastei 50 no mercado", self.config)
        self.assertIsNotNone(result)
        command, args = result
        self.assertEqual(command, "/gasto")
        amount, description, _ = parse_transaction_args(args)
        self.assertEqual(amount, Decimal("50"))
        self.assertIn("mercado", description.lower())

    def test_natural_language_income(self) -> None:
        result = interpret_natural_language("recebi 2000 de salario", self.config)
        self.assertIsNotNone(result)
        command, args = result
        self.assertEqual(command, "/ganho")
        amount, description, _ = parse_transaction_args(args)
        self.assertEqual(amount, Decimal("2000"))
        self.assertIn("salario", description.lower())

    def test_natural_language_expense_with_currency(self) -> None:
        result = interpret_natural_language("paguei R$ 1.234,56 aluguel", self.config)
        self.assertIsNotNone(result)
        command, args = result
        self.assertEqual(command, "/gasto")
        amount, _, _ = parse_transaction_args(args)
        self.assertEqual(amount, Decimal("1234.56"))

    def test_natural_language_event(self) -> None:
        result = interpret_natural_language(
            "marcar reuniao com cliente amanha 15h", self.config
        )
        self.assertIsNotNone(result)
        command, args = result
        self.assertEqual(command, "/evento")
        self.assertIn("|", args)
        title, when = [part.strip() for part in args.split("|", 1)]
        self.assertIn("reuniao", title.lower())
        self.assertIn("amanha", when.lower())
        self.assertIn("15:00", when)

    def test_natural_language_unrecognized(self) -> None:
        self.assertIsNone(
            interpret_natural_language("bom dia, tudo bem?", self.config)
        )

    def test_format_brl(self) -> None:
        self.assertEqual(format_brl(Decimal("50")), "R$ 50,00")
        self.assertEqual(format_brl(Decimal("1234.56")), "R$ 1.234,56")
        self.assertEqual(format_brl(Decimal("-80.5")), "R$ -80,50")

    def test_rich_confirmation_for_expense(self) -> None:
        services = FakeServices()
        config = dataclasses.replace(self.config, sheet_id="SHEET123")
        reply = handle_telegram_text(
            "gastei 50 no mercado", 123, config, services
        )
        self.assertIsInstance(reply, BotReply)
        self.assertEqual(reply.kind, "gasto")
        self.assertEqual(reply.amount, Decimal("50"))
        self.assertIn("✅", reply.text)
        self.assertIn("R$ 50,00", reply.text)
        self.assertEqual(len(services.sheets.appended), 1)

    def test_window_summary_aggregates(self) -> None:
        counters = {
            "gastos": {"n": 2, "total": Decimal("80")},
            "ganhos": {"n": 1, "total": Decimal("2000")},
            "eventos": 1,
            "erros": 0,
        }
        summary = build_window_summary(counters)
        self.assertIsNotNone(summary)
        self.assertIn("2 gasto(s): R$ 80,00", summary)
        self.assertIn("1 ganho(s): R$ 2.000,00", summary)
        self.assertIn("1 evento(s)", summary)
        self.assertIn("R$ 1.920,00", summary)  # saldo = 2000 - 80

    def test_window_summary_skips_single_action(self) -> None:
        counters = {
            "gastos": {"n": 1, "total": Decimal("50")},
            "ganhos": {"n": 0, "total": Decimal("0")},
            "eventos": 0,
            "erros": 0,
        }
        self.assertIsNone(build_window_summary(counters))


class FakeSheets:
    """Planilha falsa que apenas registra o que seria gravado."""

    def __init__(self) -> None:
        self.appended: list[list] = []

    # Imita a cadeia spreadsheets().values().append(...).execute()
    def spreadsheets(self):
        return self

    def get(self, spreadsheetId=None, range=None):  # noqa: N803
        outer = self

        class _Exec:
            def execute(self_inner):
                # ensure_sheet_ready espera metadados de abas e cabecalho.
                if range:
                    return {"values": [["Data", "Hora", "Tipo", "Valor", "Desc", "Cat"]]}
                return {"sheets": [{"properties": {"title": "Lancamentos"}}]}

        return _Exec()

    def values(self):
        return self

    def append(self, spreadsheetId=None, range=None, valueInputOption=None,  # noqa: N803
               insertDataOption=None, body=None):
        outer = self

        class _Exec:
            def execute(self_inner):
                outer.appended.extend(body["values"])
                return {}

        return _Exec()

    def batchUpdate(self, spreadsheetId=None, body=None):  # noqa: N803
        class _Exec:
            def execute(self_inner):
                return {}

        return _Exec()


class FakeServices:
    def __init__(self) -> None:
        self.sheets = FakeSheets()
        self.calendar = None


if __name__ == "__main__":
    unittest.main()
