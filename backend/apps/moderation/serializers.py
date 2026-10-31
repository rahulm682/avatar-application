from rest_framework import serializers


class ReportSerializer(serializers.Serializer):
    email_hash = serializers.RegexField(r"^[0-9a-f]{64}$", help_text="The 64-character hash from the picture's address.")
    reason = serializers.CharField(min_length=3, max_length=500)