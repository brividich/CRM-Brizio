from security.models import SecurityMailboxMessage, SecuritySource, SecuritySourceFile, SourceType


def get_or_create_source(name, vendor, source_type):
    source, _ = SecuritySource.objects.get_or_create(
        name=name,
        defaults={"vendor": vendor, "source_type": source_type},
    )
    return source


def ingest_mailbox_message(source, subject, body, sender="security@example.test", external_id=""):
    return SecurityMailboxMessage.objects.create(
        source=source,
        sender=sender,
        subject=subject,
        body=body,
        external_id=external_id,
    )


def ingest_source_file(source, original_name, content, file_type=SourceType.CSV):
    return SecuritySourceFile.objects.create(
        source=source,
        original_name=original_name,
        content=content,
        file_type=file_type,
    )
