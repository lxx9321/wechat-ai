from typing import BinaryIO


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)


class InvalidImageUpload(ValueError):
    """上传内容不是受支持的有效图片。"""


class ImageTooLarge(InvalidImageUpload):
    """上传图片超过允许大小。"""


def has_valid_image_signature(image_bytes: bytes, mime_type: str) -> bool:
    if mime_type == "image/jpeg":
        return image_bytes.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/webp":
        return (
            len(image_bytes) >= 12
            and image_bytes.startswith(b"RIFF")
            and image_bytes[8:12] == b"WEBP"
        )
    return False


def read_and_validate_image(
    stream: BinaryIO,
    mime_type: str,
) -> tuple[bytes, str]:
    normalized_mime_type = mime_type.strip().lower()
    if normalized_mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise InvalidImageUpload("unsupported image MIME type")

    try:
        image_bytes = stream.read(MAX_IMAGE_BYTES + 1)
    except Exception as exc:
        raise InvalidImageUpload("image read failed") from exc

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ImageTooLarge("image is too large")
    if not image_bytes:
        raise InvalidImageUpload("image is empty")
    if not has_valid_image_signature(image_bytes, normalized_mime_type):
        raise InvalidImageUpload("image signature does not match MIME type")

    return bytes(image_bytes), normalized_mime_type
