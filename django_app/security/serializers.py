from rest_framework import serializers

from .models import (
    BackupJobRecord,
    SecurityAlert,
    SecurityAsset,
    SecurityEvidenceContainer,
    SecurityEventRecord,
    SecurityKpiSnapshot,
    SecurityReport,
    SecuritySource,
    SourceType,
    SecurityVulnerabilityFinding,
)


class IngestMailboxMessageSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=255)
    body = serializers.CharField(allow_blank=True, required=False, default="")
    sender = serializers.EmailField(required=False, default="security@example.test")
    external_id = serializers.CharField(allow_blank=True, required=False, default="")


class IngestSourceFileSerializer(serializers.Serializer):
    original_name = serializers.CharField(max_length=255)
    content = serializers.CharField(allow_blank=True)
    file_type = serializers.ChoiceField(choices=SourceType.choices, required=False, default=SourceType.CSV)


class SecuritySourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecuritySource
        fields = "__all__"


class SecurityReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityReport
        fields = "__all__"


class SecurityEventRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityEventRecord
        fields = "__all__"


class SecurityAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityAlert
        fields = "__all__"


class SecurityEvidenceContainerSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityEvidenceContainer
        fields = "__all__"


class SecurityAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityAsset
        fields = "__all__"


class SecurityVulnerabilityFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityVulnerabilityFinding
        fields = "__all__"


class BackupJobRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupJobRecord
        fields = "__all__"


class SecurityKpiSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityKpiSnapshot
        fields = "__all__"
