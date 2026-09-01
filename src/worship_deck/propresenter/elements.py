"""``Graphics.Element`` constructors for generated ``.pro`` slides (v3 migration, #172).

Every visible thing on a ProPresenter slide is a ``Slide.Element`` wrapping a
``Graphics.Element``: text runs, shapes (the 네이비 프레임 box, gold rules, the blur
backdrop), images (봉헌 hymn pages, lead sheets) and web content.
The field recipes below were read off real PP 21.4 documents — the ones that bite:

* every element carries a closed unit-square ``path`` with ``shape.type = TYPE_RECTANGLE``;
* ``fill.enable`` / ``stroke.enable`` are the gates — an image with ``fill.media`` but no
  ``fill.enable`` simply never draws;
* ``Slide.Element.info`` is a bitmask: ``3`` (template|text) for text, ``1`` for shapes;
* ``text.attributes`` duplicates the font/color/alignment that ``rtf_data`` also encodes,
  so both are written from the same ``styles.Style``.
"""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

# isort: off
from . import pb  # noqa: F401 -- side effect: puts pb/ on sys.path for the bare *_pb2 imports

import color_pb2
import graphicsData_pb2
import slide_pb2
import url_pb2

# isort: on

if TYPE_CHECKING:
    from .styles import Style

_Graphics = graphicsData_pb2.Graphics
_ALIGNMENT = {
    "left": _Graphics.Text.Attributes.ALIGNMENT_LEFT,
    "center": _Graphics.Text.Attributes.ALIGNMENT_CENTER,
    "right": _Graphics.Text.Attributes.ALIGNMENT_RIGHT,
}
_VERTICAL = {
    "top": _Graphics.Text.VERTICAL_ALIGNMENT_TOP,
    "middle": _Graphics.Text.VERTICAL_ALIGNMENT_MIDDLE,
    "bottom": _Graphics.Text.VERTICAL_ALIGNMENT_BOTTOM,
}

Rect = tuple[float, float, float, float]  # x, y, width, height in canvas points
Rgba = tuple[int, int, int, float]


def new_uuid() -> str:
    """ProPresenter writes canonical UPPERCASE UUIDs everywhere; match it."""
    return str(_uuid.uuid4()).upper()


def set_color(target: color_pb2.Color, rgb, alpha: float = 1.0) -> None:
    """Fill a ``Color`` from a 0–255 ``(r, g, b)`` or ``(r, g, b, alpha)`` tuple."""
    if len(rgb) == 4:
        rgb, alpha = rgb[:3], rgb[3]
    target.red, target.green, target.blue = (c / 255 for c in rgb)
    target.alpha = alpha


def _element(slide: slide_pb2.Slide, rect: Rect, *, info: int = 0) -> slide_pb2.Slide.Element:
    """Append a positioned, unit-square-path element — the base every kind of element shares."""
    wrapper = slide.elements.add()
    wrapper.info = info
    element = wrapper.element
    element.uuid.string = new_uuid()
    element.opacity = 1.0
    element.bounds.origin.x, element.bounds.origin.y = rect[0], rect[1]
    element.bounds.size.width, element.bounds.size.height = rect[2], rect[3]
    element.path.closed = True
    element.path.shape.type = _Graphics.Path.Shape.TYPE_RECTANGLE
    for x, y in ((0, 0), (1, 0), (1, 1), (0, 1)):
        point = element.path.points.add()
        point.point.x = point.q0.x = point.q1.x = x
        point.point.y = point.q0.y = point.q1.y = y
    return wrapper


def text(
    slide: slide_pb2.Slide,
    rect: Rect,
    rtf_data: bytes,
    style: Style,
    *,
    valign: str = "middle",
    name: str = "",
) -> slide_pb2.Slide.Element:
    """Add a text element carrying ``rtf_data`` (built by ``rtf.document``).

    ``style`` supplies the element-level attributes, which ProPresenter uses for anything the
    RTF doesn't pin down (and for what it shows in the inspector), so keep the two in sync.
    """
    wrapper = _element(slide, rect, info=3)  # IS_TEMPLATE_ELEMENT | IS_TEXT_ELEMENT
    element = wrapper.element
    element.name = name or "Text"
    body = element.text
    body.rtf_data = rtf_data
    body.vertical_alignment = _VERTICAL[valign]
    body.attributes.font.name = style.font
    body.attributes.font.family = style.family
    body.attributes.font.size = style.size
    body.attributes.font.bold = style.bold
    set_color(body.attributes.text_solid_fill, style.rgb)
    body.attributes.paragraph_style.alignment = _ALIGNMENT[style.align]
    body.attributes.paragraph_style.line_height_multiple = 1.0
    body.attributes.paragraph_style.line_spacing = style.line_spacing
    body.attributes.kerning = style.tracking
    return wrapper


def shadow(
    wrapper: slide_pb2.Slide.Element,
    rgba: Rgba = (0, 0, 0, 0.75),
    *,
    angle: float = 315.0,
    offset: float = 4.0,
    radius: float = 8.0,
    on_text: bool = True,
) -> None:
    """Drop-shadow a text or shape element — the legibility trick every keyed graphic uses (#234).

    White type over a live camera needs *some* separation from the shot, and a shadow is what
    real broadcasts reach for instead of a container: 더사랑의교회 sets its ``[대표기도] 이창훈
    장로`` key label as bare shadowed type with no box at all.

    ``Graphics.Text`` has its own ``shadow`` slot distinct from the element's, and for a text
    element it is the one that renders the glyphs' shadow rather than the (invisible) box's —
    hence ``on_text``. Shapes take the element-level one.
    """
    target = wrapper.element.text.shadow if on_text else wrapper.element.shadow
    target.style = _Graphics.Shadow.STYLE_DROP
    target.angle, target.offset, target.radius = angle, offset, radius
    set_color(target.color, rgba)
    target.opacity = rgba[3] if len(rgba) == 4 else 1.0
    target.enable = True


def line_strip(
    wrapper: slide_pb2.Slide.Element, rgba: Rgba, *, pad: tuple[float, float]
) -> None:
    """Option A (검정 스트립): fill each *line* of text rather than the whole box.

    ``LINE_MASK_STYLE_LINE_WIDTH`` is ProPresenter's native per-line text-hugging background —
    the same effect the Hillsong reference uses — so the strips track the text as it wraps.
    """
    element = wrapper.element
    set_color(element.fill.color, rgba)
    element.fill.enable = True
    mask = element.text_line_mask
    mask.enabled = True
    mask.mask_style = _Graphics.Text.LineFillMask.LINE_MASK_STYLE_LINE_WIDTH
    mask.width_offset, mask.height_offset = pad[0] * 2, pad[1] * 2


def shape(
    slide: slide_pb2.Slide,
    rect: Rect,
    *,
    fill: Rgba | None = None,
    stroke: tuple[Rgba, float] | None = None,
    roundness: float | None = None,
) -> slide_pb2.Slide.Element:
    """Add a shape: the 네이비 프레임 box, a gold rule, a tint layer.

    Note there is deliberately no background-blur option. ``Fill.backgroundEffect``
    (``backgroundBlur``) looked like a free way to get the blurred backdrop, but ProPresenter
    21.4 renders it as an unrendered placeholder and **crashes** when the slide is selected,
    so the 네이비 프레임 backdrop needs a real (pre-blurred) background image instead — #224.

    ``Fill`` is a oneof that also offers ``gradient``, and ``Graphics.Element`` has a ``feather``
    slot; both were wired up for the #234 bake-off and taken out again when the keyed label went
    with a PNG plate. Neither was ever confirmed to render in PP 21.4 — as ``backgroundEffect``
    shows, a field existing in the schema is not evidence it draws.
    """
    wrapper = _element(slide, rect, info=1)  # IS_TEMPLATE_ELEMENT
    element = wrapper.element
    if roundness is not None:
        element.path.shape.type = _Graphics.Path.Shape.TYPE_ROUNDED_RECTANGLE
        element.path.shape.rounded_rectangle.roundness = roundness
    if fill is not None:
        set_color(element.fill.color, fill)
        element.fill.enable = True
    if stroke is not None:
        rgba, width = stroke
        element.stroke.style = _Graphics.Stroke.STYLE_SOLID_LINE
        element.stroke.width = width
        set_color(element.stroke.color, rgba)
        element.stroke.enable = True
    return wrapper


def _media(element: graphicsData_pb2.Graphics.Element) -> graphicsData_pb2.Media:
    media = element.fill.media
    media.uuid.string = new_uuid()
    element.fill.enable = True  # without this the media never draws
    return media


def image(
    slide: slide_pb2.Slide, rect: Rect, path: str, *, fill_frame: bool = True
) -> slide_pb2.Slide.Element:
    """Add an image element (봉헌 hymn pages #179, band lead sheets) from a local file path."""
    wrapper = _element(slide, rect)
    element = wrapper.element
    element.name = Path(path).stem
    media = _media(element)
    media.url.absolute_string = "file://" + quote(str(Path(path).resolve()))
    media.url.platform = url_pb2.URL.PLATFORM_MACOS
    media.image.drawing.natural_size.width = rect[2]
    media.image.drawing.natural_size.height = rect[3]
    media.image.drawing.scale_behavior = (
        graphicsData_pb2.Media.SCALE_BEHAVIOR_FILL
        if fill_frame
        else graphicsData_pb2.Media.SCALE_BEHAVIOR_FIT
    )
    return wrapper


def web(slide: slide_pb2.Slide, rect: Rect, url: str) -> slide_pb2.Slide.Element:
    """Add a web (iframe) element.

    **Nothing in the generator calls this.** It was built for Glossa live translation, but #177
    settled that Glossa is a ProPresenter *Prop* — its own layer, toggled by the operator over
    whatever is on screen, and stored per-machine outside any ``.pro`` (see ``build.py``'s NOTE).
    Kept as a #172 primitive because the format slot is real and correct; if you are reaching for
    it to put a translation on a slide, read that NOTE first.
    """
    wrapper = _element(slide, rect)
    element = wrapper.element
    element.name = "Web"
    media = _media(element)
    media.url.absolute_string = url
    media.url.platform = url_pb2.URL.PLATFORM_MACOS
    media.web_content.url.absolute_string = url
    media.web_content.url.platform = url_pb2.URL.PLATFORM_MACOS
    media.web_content.drawing.natural_size.width = rect[2]
    media.web_content.drawing.natural_size.height = rect[3]
    return wrapper
