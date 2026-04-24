from django.test import SimpleTestCase

from accounts.services import tokens


class TokenServiceTests(SimpleTestCase):
    def test_make_token_is_unique_enough(self):
        samples = {tokens.make_token() for _ in range(200)}
        self.assertEqual(len(samples), 200)

    def test_hash_is_deterministic(self):
        raw = tokens.make_token()
        self.assertEqual(tokens.hash_token(raw), tokens.hash_token(raw))

    def test_verify_accepts_correct(self):
        raw = tokens.make_token()
        self.assertTrue(tokens.verify_token(raw, tokens.hash_token(raw)))

    def test_verify_rejects_wrong(self):
        raw = tokens.make_token()
        self.assertFalse(tokens.verify_token(raw + "x", tokens.hash_token(raw)))
        self.assertFalse(tokens.verify_token("", tokens.hash_token(raw)))
        self.assertFalse(tokens.verify_token(raw, ""))

    def test_hash_token_type_guard(self):
        with self.assertRaises(TypeError):
            tokens.hash_token(b"bytes-not-accepted")
