"""응답 직렬화에 쓰는 공용 marshmallow 필드."""

from datetime import timezone

from marshmallow import fields


class UtcDateTime(fields.DateTime):
    """UTC 표기('+00:00')를 붙여 직렬화하는 DateTime 필드.

    DB에는 UTC 기준의 naive datetime이 저장되므로, 그대로 내보내면 클라이언트가 로컬 시각으로
    오해한다. naive 값은 UTC로 간주하고 aware 값은 UTC로 변환해 ISO 8601로 내보낸다.
    마이크로초는 값에 있을 때만 출력한다(datetime.isoformat 동작). None은 None으로 유지한다.
    """

    def _serialize(self, value, attr, obj, **kwargs):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
