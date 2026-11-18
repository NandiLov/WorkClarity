"""PDF rendering (Linux & macOS compatible) and optional image preprocessing utilities."""

from __future__ import annotations

import base64
import ctypes
import ctypes.util
import io
import math
import shutil
import struct
import subprocess
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

IMAGE_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({*IMAGE_MIME_TYPES.keys(), ".pdf"})
DEFAULT_PDF_DPI = 200


@dataclass(frozen=True, slots=True)
class ImagePreprocessingDiagnostics:
    """Audit trail for image orientation estimation, transformations, and byte preservation."""

    original_width: int
    original_height: int
    output_width: int
    output_height: int
    exif_orientation: int
    estimated_angle_degrees: float | None
    angle_confidence_ratio: float
    orientation_reliable: bool
    rotation_applied_degrees: float
    preserved_original_bytes: bool
    backend_used: str
    applied_transformations: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class PreparedDocumentPage:
    """Single image payload ready to attach to a multimodal model request."""

    page_number: int
    total_pages: int
    mime_type: str
    image_bytes: bytes
    base64_data: str
    preprocessing_applied: tuple[str, ...] = field(default_factory=tuple)
    preprocessing_diagnostics: ImagePreprocessingDiagnostics | None = None

    @property
    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64_data}"


def _encode_rgba_png(width: int, height: int, rgba_bytes: bytes) -> bytes:
    """Encode tight 4-byte RGBA pixel bytes into a valid PNG byte stream."""
    expected_len = width * height * 4
    if len(rgba_bytes) != expected_len:
        raise ValueError(
            f"Expected {expected_len} RGBA bytes for {width}x{height}, got {len(rgba_bytes)}"
        )

    def _chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag)
        crc = zlib.crc32(payload, crc) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    stride = width * 4
    mv = memoryview(rgba_bytes)
    raw_scanlines = b"".join(
        b"\x00" + mv[row * stride : (row + 1) * stride].tobytes()
        for row in range(height)
    )
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(raw_scanlines, level=6)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", idat),
            _chunk(b"IEND", b""),
        ]
    )


def _render_pdf_with_pypdfium2(pdf_path: Path, dpi: int) -> list[bytes] | None:
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except ImportError:
        return None

    scale = dpi / 72.0
    pages: list[bytes] = []
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for index in range(len(doc)):
            page = doc[index]
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            pages.append(buf.getvalue())
    finally:
        doc.close()
    return pages


def _render_pdf_with_pymupdf(pdf_path: Path, dpi: int) -> list[bytes] | None:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError:
        return None

    pages: list[bytes] = []
    doc = fitz.open(str(pdf_path))
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            pages.append(pix.tobytes("png"))
    finally:
        doc.close()
    return pages


def _render_pdf_with_pdftoppm(pdf_path: Path, dpi: int) -> list[bytes] | None:
    """Linux/Cloud Run compatible PDF rasterization via poppler's pdftoppm binary."""
    pdftoppm_bin = shutil.which("pdftoppm")
    if not pdftoppm_bin:
        return None

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_prefix = Path(tmp_dir) / "page"
        proc = subprocess.run(
            [pdftoppm_bin, "-png", "-r", str(dpi), str(pdf_path), str(out_prefix)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"pdftoppm failed for {pdf_path} (exit {proc.returncode}): {proc.stderr.strip()}"
            )
        page_files = sorted(Path(tmp_dir).glob("page-*.png"))
        if not page_files:
            raise RuntimeError(f"pdftoppm produced no PNG pages for {pdf_path}")
        return [p.read_bytes() for p in page_files]


def _render_pdf_with_coregraphics(pdf_path: Path, dpi: int) -> list[bytes] | None:
    cg_path = ctypes.util.find_library("CoreGraphics")
    if not cg_path:
        return None

    cg = ctypes.cdll.LoadLibrary(cg_path)

    class _CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    class _CGSize(ctypes.Structure):
        _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

    class _CGRect(ctypes.Structure):
        _fields_ = [("origin", _CGPoint), ("size", _CGSize)]

    cg.CGDataProviderCreateWithFilename.argtypes = [ctypes.c_char_p]
    cg.CGDataProviderCreateWithFilename.restype = ctypes.c_void_p
    cg.CGDataProviderRelease.argtypes = [ctypes.c_void_p]

    cg.CGPDFDocumentCreateWithProvider.argtypes = [ctypes.c_void_p]
    cg.CGPDFDocumentCreateWithProvider.restype = ctypes.c_void_p
    cg.CGPDFDocumentRelease.argtypes = [ctypes.c_void_p]

    cg.CGPDFDocumentGetNumberOfPages.argtypes = [ctypes.c_void_p]
    cg.CGPDFDocumentGetNumberOfPages.restype = ctypes.c_size_t
    cg.CGPDFDocumentGetPage.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    cg.CGPDFDocumentGetPage.restype = ctypes.c_void_p
    cg.CGPDFPageGetBoxRect.argtypes = [ctypes.c_void_p, ctypes.c_int]
    cg.CGPDFPageGetBoxRect.restype = _CGRect

    cg.CGColorSpaceCreateDeviceRGB.argtypes = []
    cg.CGColorSpaceCreateDeviceRGB.restype = ctypes.c_void_p
    cg.CGColorSpaceRelease.argtypes = [ctypes.c_void_p]

    cg.CGBitmapContextCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    cg.CGBitmapContextCreate.restype = ctypes.c_void_p
    cg.CGContextRelease.argtypes = [ctypes.c_void_p]

    cg.CGContextSetRGBFillColor.argtypes = [
        ctypes.c_void_p,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
    ]
    cg.CGContextFillRect.argtypes = [ctypes.c_void_p, _CGRect]
    cg.CGContextScaleCTM.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
    cg.CGContextTranslateCTM.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
    cg.CGContextDrawPDFPage.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    provider = cg.CGDataProviderCreateWithFilename(str(pdf_path).encode("utf-8"))
    if not provider:
        raise RuntimeError(f"Unable to open PDF data provider for {pdf_path}")

    doc = None
    color_space = None
    try:
        doc = cg.CGPDFDocumentCreateWithProvider(provider)
        if not doc:
            raise RuntimeError(f"Unable to parse PDF document: {pdf_path}")

        page_count = int(cg.CGPDFDocumentGetNumberOfPages(doc))
        if page_count <= 0:
            raise RuntimeError(f"PDF document contains no pages: {pdf_path}")

        color_space = cg.CGColorSpaceCreateDeviceRGB()
        scale = dpi / 72.0
        rendered_pages: list[bytes] = []

        for page_num in range(1, page_count + 1):
            page = cg.CGPDFDocumentGetPage(doc, page_num)
            if not page:
                raise RuntimeError(f"Failed to read page {page_num} of {pdf_path}")

            # 0 = kCGPDFMediaBox
            rect = cg.CGPDFPageGetBoxRect(page, 0)
            width = max(1, int(round(rect.size.width * scale)))
            height = max(1, int(round(rect.size.height * scale)))
            pixel_buf = ctypes.create_string_buffer(width * height * 4)

            # 1 = kCGImageAlphaPremultipliedLast (RGBA byte order)
            ctx = cg.CGBitmapContextCreate(
                pixel_buf, width, height, 8, width * 4, color_space, 1
            )
            if not ctx:
                raise RuntimeError(f"Failed to allocate bitmap context for {pdf_path}")
            try:
                cg.CGContextSetRGBFillColor(ctx, 1.0, 1.0, 1.0, 1.0)
                cg.CGContextFillRect(
                    ctx, _CGRect(_CGPoint(0.0, 0.0), _CGSize(float(width), float(height)))
                )
                cg.CGContextScaleCTM(ctx, scale, scale)
                if rect.origin.x or rect.origin.y:
                    cg.CGContextTranslateCTM(ctx, -rect.origin.x, -rect.origin.y)
                cg.CGContextDrawPDFPage(ctx, page)
                rendered_pages.append(_encode_rgba_png(width, height, pixel_buf.raw))
            finally:
                cg.CGContextRelease(ctx)

        return rendered_pages
    finally:
        if color_space:
            cg.CGColorSpaceRelease(color_space)
        if doc:
            cg.CGPDFDocumentRelease(doc)
        cg.CGDataProviderRelease(provider)


def render_pdf_to_png_pages(
    file_path: str | Path,
    *,
    dpi: int = DEFAULT_PDF_DPI,
) -> list[bytes]:
    """
    Render every page of a PDF file into high-resolution PNG bytes.

    Backend priority supports Linux Cloud Run containers (pypdfium2, pymupdf, poppler pdftoppm)
    and macOS development workstations (CoreGraphics).
    """
    if dpi < 72 or dpi > 600:
        raise ValueError(f"PDF rendering dpi must be between 72 and 600, got {dpi}")
    pdf_path = Path(file_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    for backend in (
        _render_pdf_with_pypdfium2,
        _render_pdf_with_pymupdf,
        _render_pdf_with_pdftoppm,
        _render_pdf_with_coregraphics,
    ):
        pages = backend(pdf_path, dpi)
        if pages is not None:
            return pages

    raise RuntimeError(
        "No PDF rendering backend available. Install pypdfium2, pymupdf, or poppler-utils (pdftoppm) on Linux, "
        "or run on macOS CoreGraphics."
    )


def _horizontal_projection_variance(gray_rows: list[list[int]]) -> float:
    """Measure horizontal line alignment sharpness via row-sum variance."""
    if not gray_rows:
        return 0.0
    row_sums = [sum(255 - px for px in row) for row in gray_rows]
    mean = sum(row_sums) / len(row_sums)
    return sum((val - mean) ** 2 for val in row_sums) / len(row_sums)


def _read_jpeg_exif_orientation(image_bytes: bytes) -> int:
    """Read EXIF Orientation tag (1..8) from JPEG APP1 without external dependencies."""
    if len(image_bytes) < 4 or image_bytes[:2] != b"\xff\xd8":
        return 1
    offset = 2
    n = len(image_bytes)
    while offset + 4 <= n:
        if image_bytes[offset] != 0xFF:
            break
        while offset < n and image_bytes[offset] == 0xFF:
            offset += 1
        if offset >= n:
            break
        marker = image_bytes[offset]
        offset += 1
        if marker in (0xD9, 0xDA) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            break
        if offset + 2 > n:
            break
        seg_len = int.from_bytes(image_bytes[offset : offset + 2], "big")
        if seg_len < 2 or offset + seg_len > n:
            break
        if marker == 0xE1 and seg_len >= 16 and image_bytes[offset + 2 : offset + 8] == b"Exif\x00\x00":
            tiff_start = offset + 8
            byte_order = image_bytes[tiff_start : tiff_start + 2]
            endian = "<" if byte_order == b"II" else (">" if byte_order == b"MM" else "")
            if endian and tiff_start + 8 <= n:
                ifd0_rel = struct.unpack_from(endian + "I", image_bytes, tiff_start + 4)[0]
                ifd0 = tiff_start + ifd0_rel
                if ifd0 + 2 <= n:
                    count = struct.unpack_from(endian + "H", image_bytes, ifd0)[0]
                    for i in range(count):
                        entry_off = ifd0 + 2 + i * 12
                        if entry_off + 12 > n:
                            break
                        tag, typ, cnt = struct.unpack_from(endian + "HHI", image_bytes, entry_off)
                        if tag == 0x0112 and typ == 3 and cnt >= 1:
                            val = struct.unpack_from(endian + "H", image_bytes, entry_off + 8)[0]
                            return val if 1 <= val <= 8 else 1
            return 1
        offset += seg_len
    return 1


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _decode_png_rgba(image_bytes: bytes) -> tuple[int, int, bytes] | None:
    """Decode standard 8-bit non-interlaced PNG bytes into (width, height, rgba_bytes)."""
    if len(image_bytes) < 24 or image_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    n = len(image_bytes)
    width = height = bit_depth = color_type = interlace = -1
    idat_parts: list[bytes] = []
    palette: list[tuple[int, int, int, int]] = []
    trns_chunk: bytes | None = None

    while pos + 12 <= n:
        length = int.from_bytes(image_bytes[pos : pos + 4], "big")
        ctype = image_bytes[pos + 4 : pos + 8]
        data_start = pos + 8
        data_end = data_start + length
        if data_end + 4 > n:
            return None
        payload = image_bytes[data_start:data_end]
        if ctype == b"IHDR":
            if length != 13:
                return None
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif ctype == b"PLTE":
            palette = [
                (payload[i], payload[i + 1], payload[i + 2], 255)
                for i in range(0, len(payload) - (len(payload) % 3), 3)
            ]
        elif ctype == b"tRNS":
            trns_chunk = payload
        elif ctype == b"IDAT":
            idat_parts.append(payload)
        elif ctype == b"IEND":
            break
        pos = data_end + 4

    if width <= 0 or height <= 0 or bit_depth != 8 or interlace != 0:
        return None
    bpp_map = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    bpp = bpp_map.get(color_type)
    if bpp is None or not idat_parts:
        return None
    if color_type == 3 and trns_chunk:
        palette = [
            (r, g, b, trns_chunk[idx] if idx < len(trns_chunk) else 255)
            for idx, (r, g, b, _a) in enumerate(palette)
        ]

    try:
        raw = zlib.decompress(b"".join(idat_parts))
    except zlib.error:
        return None

    stride = width * bpp
    if len(raw) < height * (stride + 1):
        return None

    prev_row = bytearray(stride)
    rgba = bytearray(width * height * 4)
    in_off = 0
    out_off = 0

    for _y in range(height):
        filt = raw[in_off]
        in_off += 1
        cur = bytearray(raw[in_off : in_off + stride])
        in_off += stride
        if filt == 1:
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif filt == 2:
            for i in range(stride):
                cur[i] = (cur[i] + prev_row[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev_row[i]) >> 1)) & 0xFF
        elif filt == 4:
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                up_left = prev_row[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + _paeth_predictor(left, up, up_left)) & 0xFF
        elif filt != 0:
            return None

        if color_type == 6:
            rgba[out_off : out_off + width * 4] = cur
            out_off += width * 4
        elif color_type == 2:
            for x in range(width):
                si = x * 3
                rgba[out_off] = cur[si]
                rgba[out_off + 1] = cur[si + 1]
                rgba[out_off + 2] = cur[si + 2]
                rgba[out_off + 3] = 255
                out_off += 4
        elif color_type == 0:
            for x in range(width):
                g = cur[x]
                rgba[out_off] = g
                rgba[out_off + 1] = g
                rgba[out_off + 2] = g
                rgba[out_off + 3] = 255
                out_off += 4
        elif color_type == 4:
            for x in range(width):
                g = cur[x * 2]
                rgba[out_off] = g
                rgba[out_off + 1] = g
                rgba[out_off + 2] = g
                rgba[out_off + 3] = cur[x * 2 + 1]
                out_off += 4
        elif color_type == 3:
            for x in range(width):
                idx = cur[x]
                r, g, b, a = palette[idx] if idx < len(palette) else (0, 0, 0, 255)
                rgba[out_off] = r
                rgba[out_off + 1] = g
                rgba[out_off + 2] = b
                rgba[out_off + 3] = a
                out_off += 4

        prev_row = cur

    return width, height, bytes(rgba)


def _decode_image_with_coregraphics(image_bytes: bytes) -> tuple[int, int, bytes] | None:
    """Decode JPEG/PNG into raw RGBA bytes using macOS ImageIO + CoreGraphics."""
    cg_path = ctypes.util.find_library("CoreGraphics")
    iio_path = ctypes.util.find_library("ImageIO")
    cf_path = ctypes.util.find_library("CoreFoundation")
    if not (cg_path and iio_path and cf_path):
        return None

    cg = ctypes.cdll.LoadLibrary(cg_path)
    iio = ctypes.cdll.LoadLibrary(iio_path)
    cf = ctypes.cdll.LoadLibrary(cf_path)

    cf.CFDataCreate.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long]
    cf.CFDataCreate.restype = ctypes.c_void_p
    cf.CFRelease.argtypes = [ctypes.c_void_p]

    iio.CGImageSourceCreateWithData.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    iio.CGImageSourceCreateWithData.restype = ctypes.c_void_p
    iio.CGImageSourceCreateImageAtIndex.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
    ]
    iio.CGImageSourceCreateImageAtIndex.restype = ctypes.c_void_p

    cg.CGImageGetWidth.argtypes = [ctypes.c_void_p]
    cg.CGImageGetWidth.restype = ctypes.c_size_t
    cg.CGImageGetHeight.argtypes = [ctypes.c_void_p]
    cg.CGImageGetHeight.restype = ctypes.c_size_t
    cg.CGImageRelease.argtypes = [ctypes.c_void_p]

    cg.CGColorSpaceCreateDeviceRGB.argtypes = []
    cg.CGColorSpaceCreateDeviceRGB.restype = ctypes.c_void_p
    cg.CGColorSpaceRelease.argtypes = [ctypes.c_void_p]
    cg.CGBitmapContextCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    cg.CGBitmapContextCreate.restype = ctypes.c_void_p
    cg.CGContextRelease.argtypes = [ctypes.c_void_p]

    class _CGRect(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_double),
            ("y", ctypes.c_double),
            ("w", ctypes.c_double),
            ("h", ctypes.c_double),
        ]

    cg.CGContextDrawImage.argtypes = [ctypes.c_void_p, _CGRect, ctypes.c_void_p]

    cf_data = cf.CFDataCreate(None, image_bytes, len(image_bytes))
    if not cf_data:
        return None
    src = img = cs = ctx = None
    try:
        src = iio.CGImageSourceCreateWithData(cf_data, None)
        if not src:
            return None
        img = iio.CGImageSourceCreateImageAtIndex(src, 0, None)
        if not img:
            return None
        width = int(cg.CGImageGetWidth(img))
        height = int(cg.CGImageGetHeight(img))
        if width <= 0 or height <= 0:
            return None
        buf = ctypes.create_string_buffer(width * height * 4)
        cs = cg.CGColorSpaceCreateDeviceRGB()
        # 1 = kCGImageAlphaPremultipliedLast (RGBA byte order)
        ctx = cg.CGBitmapContextCreate(buf, width, height, 8, width * 4, cs, 1)
        if not ctx:
            return None
        cg.CGContextDrawImage(ctx, _CGRect(0.0, 0.0, float(width), float(height)), img)
        return width, height, buf.raw
    finally:
        if ctx:
            cg.CGContextRelease(ctx)
        if cs:
            cg.CGColorSpaceRelease(cs)
        if img:
            cg.CGImageRelease(img)
        if src:
            cf.CFRelease(src)
        cf.CFRelease(cf_data)


def _decode_image_with_pillow(image_bytes: bytes) -> tuple[int, int, bytes] | None:
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return None

    with Image.open(io.BytesIO(image_bytes)) as opened:
        rgba = opened.convert("RGBA")
        w, h = rgba.size
        return w, h, rgba.tobytes()


def _apply_exif_orientation_rgba(
    width: int,
    height: int,
    rgba_bytes: bytes,
    orientation: int,
) -> tuple[int, int, bytes]:
    """Re-orient decoded RGBA pixels according to EXIF orientation tag (1..8)."""
    if orientation == 1:
        return width, height, rgba_bytes

    mv = memoryview(rgba_bytes)
    new_w, new_h = (height, width) if orientation in (5, 6, 7, 8) else (width, height)
    out = bytearray(new_w * new_h * 4)

    for y in range(height):
        for x in range(width):
            if orientation == 2:
                nx, ny = width - 1 - x, y
            elif orientation == 3:
                nx, ny = width - 1 - x, height - 1 - y
            elif orientation == 4:
                nx, ny = x, height - 1 - y
            elif orientation == 5:
                nx, ny = y, x
            elif orientation == 6:
                nx, ny = height - 1 - y, x
            elif orientation == 7:
                nx, ny = height - 1 - y, width - 1 - x
            elif orientation == 8:
                nx, ny = y, width - 1 - x
            else:
                nx, ny = x, y
            si = (y * width + x) * 4
            di = (ny * new_w + nx) * 4
            out[di : di + 4] = mv[si : si + 4]

    return new_w, new_h, bytes(out)


def _downsample_luma(width: int, height: int, rgba_bytes: bytes, max_dim: int = 480) -> tuple[int, int, bytearray]:
    """Produce a fast strided grayscale canvas with max dimension <= max_dim."""
    scale = min(1.0, float(max_dim) / max(1, width, height))
    sw = max(1, int(round(width * scale)))
    sh = max(1, int(round(height * scale)))
    luma = bytearray(sw * sh)
    mv = memoryview(rgba_bytes)
    for oy in range(sh):
        sy = min(height - 1, int((oy + 0.5) * height / sh))
        row_src = sy * width * 4
        row_dst = oy * sw
        for ox in range(sw):
            sx = min(width - 1, int((ox + 0.5) * width / sw))
            si = row_src + sx * 4
            r, g, b = mv[si], mv[si + 1], mv[si + 2]
            luma[row_dst + ox] = (77 * r + 150 * g + 29 * b) >> 8
    return sw, sh, luma


def estimate_skew_angle_from_rgba(
    width: int,
    height: int,
    rgba_bytes: bytes,
    *,
    max_angle: float = 12.0,
    min_confidence_ratio: float = 3.5,
) -> tuple[float | None, float, bool]:
    """
    Estimate corrective rotation angle in degrees without hardcoding sample angles.

    Returns (estimated_angle_degrees, confidence_ratio, orientation_reliable).
    Positive angle rotates counter-clockwise; negative angle rotates clockwise.
    """
    if width < 16 or height < 16:
        return None, 0.0, False

    sw, sh, luma = _downsample_luma(width, height, rgba_bytes, max_dim=480)
    mx = max(2, int(sw * 0.10))
    my = max(2, int(sh * 0.10))
    if sw - mx <= mx + 1 or sh - my <= my + 1:
        return None, 0.0, False

    # Collect directional horizontal-edge pixels (text baselines and horizontal table borders)
    grad: list[tuple[float, float, int]] = []
    half_w = sw * 0.5
    half_h = sh * 0.5
    for y in range(my, sh - my):
        row_up = (y - 1) * sw
        row_dn = (y + 1) * sw
        row_cur = y * sw
        dy = y - half_h
        for x in range(mx, sw - mx):
            gy = abs(luma[row_dn + x] - luma[row_up + x])
            gx = abs(luma[row_cur + x + 1] - luma[row_cur + x - 1])
            val = gy - (gx >> 1)
            if val > 20:
                grad.append((x - half_w, dy, val))

    if len(grad) < 120:
        return None, 0.0, False

    if len(grad) > 6000:
        step_stride = max(1, len(grad) // 6000)
        grad = grad[::step_stride]

    bin_count = int(math.ceil(math.hypot(sw, sh))) + 40
    offset = bin_count // 2

    def _projection_sharpness(angle_deg: float) -> float:
        rad = math.radians(angle_deg)
        s_a = math.sin(rad)
        c_a = math.cos(rad)
        bins = [0] * bin_count
        for dx, dy, val in grad:
            ry = int(round(-dx * s_a + dy * c_a)) + offset
            if 0 <= ry < bin_count:
                bins[ry] += val
        return float(
            sum((bins[i + 1] - bins[i]) ** 2 for i in range(bin_count - 1))
        )

    scores: dict[float, float] = {}
    best_angle = 0.0
    best_score = _projection_sharpness(0.0)
    scores[0.0] = best_score

    coarse_steps = int(round(max_angle * 2))
    for i in range(-coarse_steps, coarse_steps + 1):
        cand = round(i * 0.5, 2)
        if cand in scores:
            continue
        sc = _projection_sharpness(cand)
        scores[cand] = sc
        if sc > best_score:
            best_score = sc
            best_angle = cand

    coarse_center = best_angle
    for delta in range(-6, 7):
        cand = round(coarse_center + delta * 0.1, 2)
        if abs(cand) > max_angle + 0.5 or cand in scores:
            continue
        sc = _projection_sharpness(cand)
        scores[cand] = sc
        if sc > best_score:
            best_score = sc
            best_angle = cand

    sorted_vals = sorted(scores.values())
    median_score = sorted_vals[len(sorted_vals) // 2] if sorted_vals else 1.0
    confidence_ratio = best_score / max(1.0, median_score)
    reliable = confidence_ratio >= min_confidence_ratio
    return round(best_angle, 2), round(confidence_ratio, 2), reliable


def _rotate_rgba_expanded_coregraphics(
    width: int,
    height: int,
    rgba_bytes: bytes,
    angle_degrees: float,
    fill_rgba: tuple[int, int, int, int] = (245, 245, 245, 255),
) -> tuple[int, int, bytes] | None:
    cg_path = ctypes.util.find_library("CoreGraphics")
    cf_path = ctypes.util.find_library("CoreFoundation")
    if not (cg_path and cf_path):
        return None

    cg = ctypes.cdll.LoadLibrary(cg_path)
    cf = ctypes.cdll.LoadLibrary(cf_path)

    cf.CFDataCreate.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long]
    cf.CFDataCreate.restype = ctypes.c_void_p
    cf.CFRelease.argtypes = [ctypes.c_void_p]

    cg.CGDataProviderCreateWithCFData.argtypes = [ctypes.c_void_p]
    cg.CGDataProviderCreateWithCFData.restype = ctypes.c_void_p
    cg.CGDataProviderRelease.argtypes = [ctypes.c_void_p]

    cg.CGColorSpaceCreateDeviceRGB.argtypes = []
    cg.CGColorSpaceCreateDeviceRGB.restype = ctypes.c_void_p
    cg.CGColorSpaceRelease.argtypes = [ctypes.c_void_p]

    cg.CGImageCreate.argtypes = [
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_bool,
        ctypes.c_int,
    ]
    cg.CGImageCreate.restype = ctypes.c_void_p
    cg.CGImageRelease.argtypes = [ctypes.c_void_p]

    cg.CGBitmapContextCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    cg.CGBitmapContextCreate.restype = ctypes.c_void_p
    cg.CGContextRelease.argtypes = [ctypes.c_void_p]
    cg.CGContextSetRGBFillColor.argtypes = [
        ctypes.c_void_p,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
    ]
    cg.CGContextTranslateCTM.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
    cg.CGContextRotateCTM.argtypes = [ctypes.c_void_p, ctypes.c_double]
    cg.CGContextSetInterpolationQuality.argtypes = [ctypes.c_void_p, ctypes.c_int]

    class _CGRect(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_double),
            ("y", ctypes.c_double),
            ("w", ctypes.c_double),
            ("h", ctypes.c_double),
        ]

    cg.CGContextFillRect.argtypes = [ctypes.c_void_p, _CGRect]
    cg.CGContextDrawImage.argtypes = [ctypes.c_void_p, _CGRect, ctypes.c_void_p]

    rad = math.radians(angle_degrees)
    cos_a = abs(math.cos(rad))
    sin_a = abs(math.sin(rad))
    new_w = max(width, int(math.ceil(width * cos_a + height * sin_a)))
    new_h = max(height, int(math.ceil(width * sin_a + height * cos_a)))

    cf_data = cf.CFDataCreate(None, rgba_bytes, len(rgba_bytes))
    if not cf_data:
        return None
    provider = cs = cg_img = ctx = None
    try:
        provider = cg.CGDataProviderCreateWithCFData(cf_data)
        cs = cg.CGColorSpaceCreateDeviceRGB()
        cg_img = cg.CGImageCreate(
            width,
            height,
            8,
            32,
            width * 4,
            cs,
            1,  # kCGImageAlphaPremultipliedLast
            provider,
            None,
            True,
            0,
        )
        if not cg_img:
            return None
        out_buf = ctypes.create_string_buffer(new_w * new_h * 4)
        ctx = cg.CGBitmapContextCreate(out_buf, new_w, new_h, 8, new_w * 4, cs, 1)
        if not ctx:
            return None
        cg.CGContextSetRGBFillColor(
            ctx,
            fill_rgba[0] / 255.0,
            fill_rgba[1] / 255.0,
            fill_rgba[2] / 255.0,
            fill_rgba[3] / 255.0,
        )
        cg.CGContextFillRect(ctx, _CGRect(0.0, 0.0, float(new_w), float(new_h)))
        cg.CGContextSetInterpolationQuality(ctx, 3)
        cg.CGContextTranslateCTM(ctx, new_w / 2.0, new_h / 2.0)
        cg.CGContextRotateCTM(ctx, rad)
        cg.CGContextDrawImage(
            ctx,
            _CGRect(-width / 2.0, -height / 2.0, float(width), float(height)),
            cg_img,
        )
        return new_w, new_h, out_buf.raw
    finally:
        if ctx:
            cg.CGContextRelease(ctx)
        if cg_img:
            cg.CGImageRelease(cg_img)
        if cs:
            cg.CGColorSpaceRelease(cs)
        if provider:
            cg.CGDataProviderRelease(provider)
        cf.CFRelease(cf_data)


def _rotate_rgba_expanded_python(
    width: int,
    height: int,
    rgba_bytes: bytes,
    angle_degrees: float,
    fill_rgba: tuple[int, int, int, int] = (245, 245, 245, 255),
) -> tuple[int, int, bytes]:
    """Portable pure-Python expanded-canvas bilinear rotation fallback."""
    rad = math.radians(angle_degrees)
    cos_t = math.cos(rad)
    sin_t = math.sin(rad)
    new_w = max(width, int(math.ceil(width * abs(cos_t) + height * abs(sin_t))))
    new_h = max(height, int(math.ceil(width * abs(sin_t) + height * abs(cos_t))))

    src_cx = (width - 1) / 2.0
    src_cy = (height - 1) / 2.0
    dst_cx = (new_w - 1) / 2.0
    dst_cy = (new_h - 1) / 2.0

    fill_bytes = bytes(fill_rgba)
    out = bytearray(fill_bytes * (new_w * new_h))
    mv = memoryview(rgba_bytes)

    for oy in range(new_h):
        ody = oy - dst_cy
        base_x = -ody * sin_t + src_cx
        base_y = ody * cos_t + src_cy
        row_off = oy * new_w * 4
        for ox in range(new_w):
            odx = ox - dst_cx
            sx = odx * cos_t + base_x
            sy = odx * sin_t + base_y
            x0 = int(math.floor(sx))
            y0 = int(math.floor(sy))
            if 0 <= x0 < width - 1 and 0 <= y0 < height - 1:
                fx = sx - x0
                fy = sy - y0
                w00 = (1.0 - fx) * (1.0 - fy)
                w10 = fx * (1.0 - fy)
                w01 = (1.0 - fx) * fy
                w11 = fx * fy
                i00 = (y0 * width + x0) * 4
                i10 = i00 + 4
                i01 = ((y0 + 1) * width + x0) * 4
                i11 = i01 + 4
                di = row_off + ox * 4
                out[di] = int(mv[i00] * w00 + mv[i10] * w10 + mv[i01] * w01 + mv[i11] * w11 + 0.5)
                out[di + 1] = int(mv[i00 + 1] * w00 + mv[i10 + 1] * w10 + mv[i01 + 1] * w01 + mv[i11 + 1] * w11 + 0.5)
                out[di + 2] = int(mv[i00 + 2] * w00 + mv[i10 + 2] * w10 + mv[i01 + 2] * w01 + mv[i11 + 2] * w11 + 0.5)
                out[di + 3] = 255
            elif 0 <= round(sx) < width and 0 <= round(sy) < height:
                rx, ry = int(round(sx)), int(round(sy))
                si = (ry * width + rx) * 4
                di = row_off + ox * 4
                out[di : di + 4] = mv[si : si + 4]

    return new_w, new_h, bytes(out)


def _enhance_contrast_rgba(width: int, height: int, rgba_bytes: bytes) -> bytes:
    """Apply gentle 1%-cutoff linear histogram stretch across RGB channels."""
    total_pixels = width * height
    if total_pixels == 0:
        return rgba_bytes
    mv = memoryview(rgba_bytes)
    out = bytearray(rgba_bytes)
    cutoff_cnt = max(0, int(total_pixels * 0.01))

    for ch in range(3):
        hist = [0] * 256
        for idx in range(ch, total_pixels * 4, 4):
            hist[mv[idx]] += 1
        lo = 0
        seen = 0
        while lo < 255 and seen + hist[lo] <= cutoff_cnt:
            seen += hist[lo]
            lo += 1
        hi = 255
        seen = 0
        while hi > lo and seen + hist[hi] <= cutoff_cnt:
            seen += hist[hi]
            hi -= 1
        if hi <= lo:
            continue
        scale = 255.0 / float(hi - lo)
        lut = [
            0 if v <= lo else (255 if v >= hi else int((v - lo) * scale + 0.5))
            for v in range(256)
        ]
        for idx in range(ch, total_pixels * 4, 4):
            out[idx] = lut[mv[idx]]
    return bytes(out)


def inspect_and_preprocess_image(
    image_bytes: bytes,
    *,
    mime_type: str,
    deskew: bool = True,
    perspective_correct: bool = False,
    enhance_contrast: bool = False,
    min_deskew_angle_deg: float = 0.5,
    min_confidence_ratio: float = 3.5,
) -> tuple[bytes, str, ImagePreprocessingDiagnostics]:
    """
    Estimate orientation and optionally apply non-destructive in-memory preprocessing.

    Preserves the exact original image_bytes when orientation cannot be estimated reliably
    or no transformations are required. Never modifies files on disk.
    """
    exif_orientation = (
        _read_jpeg_exif_orientation(image_bytes) if mime_type == "image/jpeg" else 1
    )

    backend_used = "none"
    decoded = _decode_image_with_pillow(image_bytes)
    if decoded is not None:
        backend_used = "pillow"
    else:
        decoded = _decode_image_with_coregraphics(image_bytes)
        if decoded is not None:
            backend_used = "coregraphics"
        else:
            decoded = _decode_png_rgba(image_bytes)
            if decoded is not None:
                backend_used = "pure_python_png"

    if decoded is None:
        diag = ImagePreprocessingDiagnostics(
            original_width=0,
            original_height=0,
            output_width=0,
            output_height=0,
            exif_orientation=exif_orientation,
            estimated_angle_degrees=None,
            angle_confidence_ratio=0.0,
            orientation_reliable=False,
            rotation_applied_degrees=0.0,
            preserved_original_bytes=True,
            backend_used="unavailable",
            applied_transformations=(
                "preprocessing_skipped:image_decoder_unavailable",
                "preserved_original_image",
            ),
        )
        return image_bytes, mime_type, diag

    orig_w, orig_h, rgba_bytes = decoded
    cur_w, cur_h = orig_w, orig_h
    transformed = False
    applied: list[str] = []

    if exif_orientation in (2, 3, 4, 5, 6, 7, 8):
        cur_w, cur_h, rgba_bytes = _apply_exif_orientation_rgba(
            cur_w, cur_h, rgba_bytes, exif_orientation
        )
        transformed = True
        applied.append(f"exif_orientation:{exif_orientation}")

    est_angle: float | None = None
    conf_ratio = 0.0
    reliable = False
    rotation_applied = 0.0

    if deskew:
        est_angle, conf_ratio, reliable = estimate_skew_angle_from_rgba(
            cur_w, cur_h, rgba_bytes, min_confidence_ratio=min_confidence_ratio
        )
        if not reliable or est_angle is None:
            if est_angle is not None:
                applied.append(f"deskew_est:{est_angle:+.2f}deg(conf={conf_ratio:.2f})")
            applied.append("deskew_skipped:unreliable_orientation")
        else:
            applied.append(f"deskew_est:{est_angle:+.2f}deg(conf={conf_ratio:.2f})")
            if abs(est_angle) >= min_deskew_angle_deg:
                rotated: tuple[int, int, bytes] | None = None
                if backend_used == "pillow":
                    try:
                        from PIL import Image  # type: ignore[import-not-found]

                        pil_img = Image.frombytes("RGBA", (cur_w, cur_h), rgba_bytes)
                        rot_img = pil_img.rotate(
                            est_angle,
                            expand=True,
                            resample=Image.BICUBIC,
                            fillcolor=(245, 245, 245, 255),
                        )
                        rotated = (*rot_img.size, rot_img.tobytes())
                    except Exception:
                        rotated = None
                elif backend_used == "coregraphics":
                    rotated = _rotate_rgba_expanded_coregraphics(
                        cur_w, cur_h, rgba_bytes, est_angle
                    )
                if rotated is None:
                    rotated = _rotate_rgba_expanded_python(
                        cur_w, cur_h, rgba_bytes, est_angle
                    )
                pre_w, pre_h = cur_w, cur_h
                cur_w, cur_h, rgba_bytes = rotated
                rotation_applied = est_angle
                transformed = True
                applied.append(f"deskew_applied:{est_angle:+.2f}deg")
                applied.append(f"canvas_expanded:{pre_w}x{pre_h}->{cur_w}x{cur_h}")
            else:
                applied.append("deskew_skipped:within_threshold")

    if perspective_correct:
        applied.append("perspective_correct:not_implemented")

    if enhance_contrast:
        rgba_bytes = _enhance_contrast_rgba(cur_w, cur_h, rgba_bytes)
        transformed = True
        applied.append("contrast_enhanced:cutoff1pct")

    if not transformed:
        applied.append("preserved_original_image")
        diag = ImagePreprocessingDiagnostics(
            original_width=orig_w,
            original_height=orig_h,
            output_width=orig_w,
            output_height=orig_h,
            exif_orientation=exif_orientation,
            estimated_angle_degrees=est_angle,
            angle_confidence_ratio=conf_ratio,
            orientation_reliable=reliable,
            rotation_applied_degrees=0.0,
            preserved_original_bytes=True,
            backend_used=backend_used,
            applied_transformations=tuple(applied),
        )
        return image_bytes, mime_type, diag

    out_bytes = _encode_rgba_png(cur_w, cur_h, rgba_bytes)
    diag = ImagePreprocessingDiagnostics(
        original_width=orig_w,
        original_height=orig_h,
        output_width=cur_w,
        output_height=cur_h,
        exif_orientation=exif_orientation,
        estimated_angle_degrees=est_angle,
        angle_confidence_ratio=conf_ratio,
        orientation_reliable=reliable,
        rotation_applied_degrees=rotation_applied,
        preserved_original_bytes=False,
        backend_used=backend_used,
        applied_transformations=tuple(applied),
    )
    return out_bytes, "image/png", diag


def preprocess_image_bytes(
    image_bytes: bytes,
    *,
    mime_type: str,
    deskew: bool = True,
    perspective_correct: bool = False,
    enhance_contrast: bool = False,
    min_deskew_angle_deg: float = 0.5,
) -> tuple[bytes, str, tuple[str, ...]]:
    """
    Optionally apply non-destructive automatic deskewing/contrast preprocessing in memory.

    Never alters the original source file on disk and preserves original bytes whenever
    orientation cannot be estimated reliably or no transformation is warranted.
    """
    out_bytes, out_mime, diag = inspect_and_preprocess_image(
        image_bytes,
        mime_type=mime_type,
        deskew=deskew,
        perspective_correct=perspective_correct,
        enhance_contrast=enhance_contrast,
        min_deskew_angle_deg=min_deskew_angle_deg,
    )
    return out_bytes, out_mime, diag.applied_transformations


def _prepare_page_from_bytes(
    raw_bytes: bytes,
    *,
    mime_type: str,
    page_number: int,
    total_pages: int,
    preprocess_images: bool,
    deskew: bool,
    perspective_correct: bool,
    enhance_contrast: bool,
) -> PreparedDocumentPage:
    steps: tuple[str, ...] = ()
    diag: ImagePreprocessingDiagnostics | None = None
    out_bytes = raw_bytes
    out_mime = mime_type
    if preprocess_images:
        out_bytes, out_mime, diag = inspect_and_preprocess_image(
            raw_bytes,
            mime_type=mime_type,
            deskew=deskew,
            perspective_correct=perspective_correct,
            enhance_contrast=enhance_contrast,
        )
        steps = diag.applied_transformations
    return PreparedDocumentPage(
        page_number=page_number,
        total_pages=total_pages,
        mime_type=out_mime,
        image_bytes=out_bytes,
        base64_data=base64.b64encode(out_bytes).decode("ascii"),
        preprocessing_applied=steps,
        preprocessing_diagnostics=diag,
    )


def load_document_pages(
    file_path: str | Path,
    *,
    dpi: int = DEFAULT_PDF_DPI,
    preprocess_images: bool = False,
    deskew: bool = True,
    perspective_correct: bool = False,
    enhance_contrast: bool = False,
) -> list[PreparedDocumentPage]:
    """Load PNG, JPG, or multi-page PDF documents into base64-encoded image pages."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Schedule document not found: {path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported schedule document format {ext!r}; supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    if ext in IMAGE_MIME_TYPES:
        raw_bytes = path.read_bytes()
        if not raw_bytes:
            raise ValueError(f"Image document is empty: {path}")
        return [
            _prepare_page_from_bytes(
                raw_bytes,
                mime_type=IMAGE_MIME_TYPES[ext],
                page_number=1,
                total_pages=1,
                preprocess_images=preprocess_images,
                deskew=deskew,
                perspective_correct=perspective_correct,
                enhance_contrast=enhance_contrast,
            )
        ]

    png_pages = render_pdf_to_png_pages(path, dpi=dpi)
    total = len(png_pages)
    return [
        _prepare_page_from_bytes(
            page_bytes,
            mime_type="image/png",
            page_number=idx,
            total_pages=total,
            preprocess_images=preprocess_images,
            deskew=deskew,
            perspective_correct=perspective_correct,
            enhance_contrast=enhance_contrast,
        )
        for idx, page_bytes in enumerate(png_pages, start=1)
    ]


def load_document_pages_from_bytes(
    file_bytes: bytes,
    *,
    file_name: str,
    dpi: int = DEFAULT_PDF_DPI,
    preprocess_images: bool = False,
    deskew: bool = True,
    perspective_correct: bool = False,
    enhance_contrast: bool = False,
) -> list[PreparedDocumentPage]:
    """Load PNG, JPG, or multi-page PDF documents directly from uploaded in-memory bytes."""
    if not file_bytes:
        raise ValueError(f"Document byte stream is empty: {file_name}")

    ext = Path(file_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported schedule document format {ext!r}; supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    if ext in IMAGE_MIME_TYPES:
        return [
            _prepare_page_from_bytes(
                file_bytes,
                mime_type=IMAGE_MIME_TYPES[ext],
                page_number=1,
                total_pages=1,
                preprocess_images=preprocess_images,
                deskew=deskew,
                perspective_correct=perspective_correct,
                enhance_contrast=enhance_contrast,
            )
        ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_pdf = Path(tmp_dir) / "upload_source.pdf"
        tmp_pdf.write_bytes(file_bytes)
        return load_document_pages(
            tmp_pdf,
            dpi=dpi,
            preprocess_images=preprocess_images,
            deskew=deskew,
            perspective_correct=perspective_correct,
            enhance_contrast=enhance_contrast,
        )
