import unittest
from unittest.mock import patch, MagicMock
import requests
from main import telegram_request

class TestSecurity(unittest.TestCase):
    @patch('main.requests.get')
    def test_telegram_request_hides_token_on_error(self, mock_get):
        # Simulate a requests error that might contain the URL in the string representation
        token = "SECRET_BOT_TOKEN"
        mock_get.side_effect = requests.exceptions.RequestException(f"Error connecting to https://api.telegram.org/bot{token}/getUpdates")
        
        with self.assertRaises(RuntimeError) as cm:
            telegram_request(token, "getUpdates")
        
        error_msg = str(cm.exception)
        self.assertNotIn(token, error_msg)
        self.assertIn("Erro na comunicação com Telegram", error_msg)

    @patch('main.requests.get')
    def test_telegram_request_handles_api_error_gracefully(self, mock_get):
        # Simulate a successful HTTP response but with 'ok: false' from Telegram
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": False, "description": "Unauthorized"}
        mock_get.return_value = mock_response
        
        with self.assertRaises(RuntimeError) as cm:
            telegram_request("token", "getUpdates")
        
        self.assertEqual(str(cm.exception), "Telegram retornou erro: Unauthorized")

if __name__ == "__main__":
    unittest.main()
