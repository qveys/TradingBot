import unittest

from tradingbot.startup import (
    MAIL_EVENTS,
    KEY_RIGHTS_CHECK,
    STOP_POLICY,
    StartupRefused,
    check_startup,
    start,
    start_real,
)

DECIDED_MAIL_EVENTS = (
    "METHOD_CHANGE_REQUIRED",
    "HARD_STOP",
    "SAFETY_NET_FIRED",
    "BROKER_UNREACHABLE",
    "LEDGER_ANOMALY",
    "METHOD_VALIDATED",
)


class StartupTest(unittest.TestCase):
    def test_decided_mail_events_let_start_pass(self) -> None:
        self.assertEqual(MAIL_EVENTS, DECIDED_MAIL_EVENTS)
        self.assertEqual(STOP_POLICY, "refuse_naked")
        self.assertEqual(KEY_RIGHTS_CHECK, "manual_ui")
        start()

    def test_empty_mail_events_names_the_parameter(self) -> None:
        with self.assertRaises(StartupRefused) as caught:
            check_startup({"mail_events": ()})
        self.assertEqual(caught.exception.parameter, "mail_events")
        self.assertIn("mail_events", str(caught.exception))

    def test_nonempty_mail_events_passes(self) -> None:
        check_startup({"mail_events": ["undecided-name"]})

    def test_empty_undecided_parameter_is_named(self) -> None:
        with self.assertRaises(StartupRefused) as caught:
            check_startup({"mail_events": ["present"], "undecided": ""})
        self.assertEqual(caught.exception.parameter, "undecided")

    def test_real_path_absent_record_names_the_parameter(self) -> None:
        for absent in (None, "", "  ", ()):
            with self.subTest(absent=absent):
                with self.assertRaises(StartupRefused) as caught:
                    start_real(absent)
                self.assertEqual(caught.exception.parameter, "key_rights_record")

    def test_recorded_rights_pass_startup_check(self) -> None:
        check_startup(
            {"key_rights_record": "recorded", "mail_events": ["undecided-name"]}
        )

    def test_real_path_with_record_passes(self) -> None:
        start_real("recorded")

    def test_default_start_ignores_missing_rights_record(self) -> None:
        start()


if __name__ == "__main__":
    unittest.main()
