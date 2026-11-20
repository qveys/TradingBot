import unittest

from tradingbot.notify import KNOWN_EVENTS, Mailer


class MailerTest(unittest.TestCase):
    def test_event_in_list_sends_mail(self) -> None:
        # Issue 52 : événement présent dans la liste configurée -> un mail.
        sent: list[str] = []
        mailer = Mailer(["SAFETY_NET_FIRED"], sent.append)
        delivery = mailer.notify("SAFETY_NET_FIRED")
        self.assertTrue(delivery.sent)
        self.assertEqual(sent, ["SAFETY_NET_FIRED"])

    def test_event_absent_from_list_sends_nothing(self) -> None:
        sent: list[str] = []
        mailer = Mailer(["SAFETY_NET_FIRED"], sent.append)
        delivery = mailer.notify("LEDGER_ANOMALY")
        self.assertFalse(delivery.sent)
        self.assertEqual(sent, [])

    def test_all_known_events_remain_available(self) -> None:
        self.assertEqual(
            KNOWN_EVENTS,
            {
                "METHOD_CHANGE_REQUIRED",
                "HARD_STOP",
                "SAFETY_NET_FIRED",
                "BROKER_UNREACHABLE",
                "LEDGER_ANOMALY",
                "METHOD_VALIDATED",
            },
        )

    def test_empty_configured_list_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Mailer([])

    def test_unknown_event_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Mailer(["MADE_UP"])


if __name__ == "__main__":
    unittest.main()
