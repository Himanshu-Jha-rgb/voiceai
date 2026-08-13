import unittest

from config import LANGUAGE_CODE_MAP
from voice_agent.conversation import (
    LANGUAGE_KEYWORDS,
    LanguagePolicy,
    extract_requested_language,
    has_language_signal,
)


class LanguagePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = LanguagePolicy(confirmed_lang="hi-IN")

    def test_every_keyword_maps_to_a_supported_code(self) -> None:
        unsupported = {
            keyword: code
            for keyword, code in LANGUAGE_KEYWORDS.items()
            if code not in LANGUAGE_CODE_MAP
        }
        self.assertEqual(unsupported, {})

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

    def test_requested_language_beats_detected_language(self) -> None:
        decision = self.policy.decide("hi-IN", "क्या तुम अंग्रेज़ी में बोल सकते हो")
        self.assertEqual(decision.confirmed_lang, "en-IN")
        self.assertEqual(decision.reason, "explicit_request")

    def test_hinglish_request_switches(self) -> None:
        decision = self.policy.decide("hi-IN", "english mein bolo please")
        self.assertEqual(decision.confirmed_lang, "en-IN")
        self.assertEqual(decision.reason, "explicit_request")

    def test_devanagari_english_request_switches(self) -> None:
        decision = self.policy.decide(
            "hi-IN", "और भाई इंग्लिश में बात करें ना।"
        )
        self.assertEqual(decision.confirmed_lang, "en-IN")
        self.assertEqual(decision.reason, "explicit_request")

    def test_external_request_hint_switches_immediately(self) -> None:
        decision = self.policy.decide("hi-IN", "कुछ बात करनी है", requested="en-IN")
        self.assertEqual(decision.confirmed_lang, "en-IN")
        self.assertEqual(decision.reason, "explicit_request")

    def test_unmatched_request_triggers_language_signal(self) -> None:
        self.assertTrue(has_language_signal("और भाई इंग्लिश में बात करें ना"))
        self.assertTrue(has_language_signal("what language do you speak"))
        self.assertFalse(has_language_signal("मैं खाना खा रहा हूँ"))

    def test_request_for_confirmed_language_stays_put(self) -> None:
        decision = self.policy.decide("hi-IN", "हिंदी में बोलो")
        self.assertEqual(decision.confirmed_lang, "hi-IN")
        self.assertFalse(decision.switched)

    def test_alternating_short_turns_do_not_accumulate(self) -> None:
        self.policy.decide("en-IN", "hello there")
        self.policy.decide("ta-IN", "vanakkam friend")
        self.policy.decide("en-IN", "please help")
        decision = self.policy.decide("ta-IN", "help me")
        self.assertEqual(decision.confirmed_lang, "hi-IN")
        self.assertEqual(decision.pending_count, 1)


if __name__ == "__main__":
    unittest.main()
