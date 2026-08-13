import unittest

from voice_agent.conversation import LanguagePolicy


class LanguagePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = LanguagePolicy(confirmed_lang="hi-IN")

    def test_one_short_new_language_turn_does_not_switch(self) -> None:
        decision = self.policy.decide("en-IN", "hello there")
        self.assertEqual(decision.confirmed_lang, "hi-IN")
        self.assertEqual(decision.pending_count, 1)

    def test_two_consecutive_short_new_language_turns_switch(self) -> None:
        self.policy.decide("en-IN", "hello there")
        decision = self.policy.decide("en-IN", "please help")
        self.assertEqual(decision.confirmed_lang, "en-IN")
        self.assertTrue(decision.switched)
        self.assertEqual(decision.reason, "two_short_turns")

    def test_one_long_turn_switches_immediately(self) -> None:
        decision = self.policy.decide("en-IN", "I need help with my math homework today")
        self.assertEqual(decision.confirmed_lang, "en-IN")
        self.assertEqual(decision.reason, "long_turn")

    def test_explicit_request_switches_immediately(self) -> None:
        decision = self.policy.decide("en-IN", "speak English")
        self.assertEqual(decision.confirmed_lang, "en-IN")
        self.assertEqual(decision.reason, "explicit_request")

    def test_alternating_short_turns_do_not_accumulate(self) -> None:
        self.policy.decide("en-IN", "hello there")
        self.policy.decide("ta-IN", "vanakkam friend")
        self.policy.decide("en-IN", "please help")
        decision = self.policy.decide("ta-IN", "help me")
        self.assertEqual(decision.confirmed_lang, "hi-IN")
        self.assertEqual(decision.pending_count, 1)


if __name__ == "__main__":
    unittest.main()
