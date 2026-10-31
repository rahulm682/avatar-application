from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from .emailhash import hash_email, normalize_email
from .models import User

# Verified independently with: python3 -c "import hashlib; print(hashlib.sha256(b'test@example.com').hexdigest())"
TEST_EMAIL_HASH = "973dfe463ec85785f5f95af5ba3906eedb2d931c24e69824a89ea65dba4e813b"


class EmailHashTests(SimpleTestCase):
    def test_normalize_trims_and_lowercases(self):
        self.assertEqual(normalize_email("  Test@Example.COM \n"), "test@example.com")

    def test_hash_known_value(self):
        self.assertEqual(hash_email("test@example.com"), TEST_EMAIL_HASH)

    def test_hash_ignores_case_and_whitespace(self):
        self.assertEqual(hash_email("  TEST@example.com "), TEST_EMAIL_HASH)

    def test_hash_is_64_lowercase_hex_characters(self):
        value = hash_email("someone@example.org")
        self.assertEqual(len(value), 64)
        self.assertEqual(value, value.lower())
        int(value, 16)  # raises ValueError if it is not hex


class UserModelTests(TestCase):
    def test_create_user_normalizes_email_and_sets_hash(self):
        user = User.objects.create_user("  Test@Example.com ", "a-long-password-123")
        self.assertEqual(user.email, "test@example.com")
        self.assertEqual(user.email_hash, TEST_EMAIL_HASH)

    def test_password_is_hashed_with_argon2(self):
        user = User.objects.create_user("test@example.com", "a-long-password-123")
        self.assertNotEqual(user.password, "a-long-password-123")
        self.assertTrue(user.password.startswith("argon2$"))
        self.assertTrue(user.check_password("a-long-password-123"))

    def test_new_user_is_unverified_and_not_staff(self):
        user = User.objects.create_user("test@example.com", "a-long-password-123")
        self.assertIsNone(user.email_verified_at)
        self.assertFalse(user.is_email_verified)
        self.assertFalse(user.is_staff)

    def test_email_is_unique_regardless_of_case(self):
        User.objects.create_user("test@example.com", "a-long-password-123")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user("TEST@example.com", "another-long-password-1")

    def test_changing_email_updates_hash(self):
        user = User.objects.create_user("test@example.com", "a-long-password-123")
        user.email = "New@Example.com"
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user.email_hash, hash_email("new@example.com"))
        self.assertNotEqual(user.email_hash, TEST_EMAIL_HASH)

    def test_changing_email_with_update_fields_also_saves_hash(self):
        user = User.objects.create_user("test@example.com", "a-long-password-123")
        user.email = "other@example.com"
        user.save(update_fields=["email"])
        user.refresh_from_db()
        self.assertEqual(user.email_hash, hash_email("other@example.com"))

    def test_create_user_requires_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user("   ", "a-long-password-123")

    def test_create_superuser_is_staff_and_already_verified(self):
        admin_user = User.objects.create_superuser("admin@example.com", "a-long-password-123")
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(admin_user.is_email_verified)

    def test_get_by_email_normalizes_input(self):
        user = User.objects.create_user("test@example.com", "a-long-password-123")
        self.assertEqual(User.objects.get_by_email("  TEST@Example.com"), user)
