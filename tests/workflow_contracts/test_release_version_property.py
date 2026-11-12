"""Properties of the release version's pre-release classification.

``test_release_publish_steps.py`` pins the spellings this project uses. These
properties cover the wider PEP 440 space around them: any release segment with
any order-preserving combination of pre-release, post-release, development and
local segments. The expectation comes from the generated segments rather than
from the rendered string, so it is an independent oracle.
"""

from __future__ import annotations

import dataclasses as dc

from hypothesis import given, settings
from hypothesis import strategies as st

from scripts.release_version import is_prerelease

_SETTINGS = settings(max_examples=50, deadline=None)

_DIGITS = st.integers(min_value=0, max_value=99).map(str)
_RELEASE = st.lists(_DIGITS, min_size=1, max_size=3).map(".".join)
#: PEP 440 allows a hyphen, an underscore, or a dot before each segment.
_SEPARATOR = st.sampled_from(("", "-", "_", "."))
_PRE_LABELS = ("a", "b", "c", "rc", "alpha", "beta", "pre", "preview")
_POST_LABELS = ("post", "rev", "r")
#: A local segment never changes whether a version is a pre-release, so these
#: deliberately include labels that would otherwise look like one.
_LOCAL = st.one_of(
    st.none(),
    st.sampled_from(("+local", "+ubuntu.1", "+rc1", "+dev2", "+1.2.3")),
)


def _numbered(labels: tuple[str, ...]) -> st.SearchStrategy[str | None]:
    """Return a strategy for an optional separator, label, and number."""
    return st.one_of(
        st.none(),
        st.builds(
            lambda separator, label, number: f"{separator}{label}{number or ''}",
            _SEPARATOR,
            st.sampled_from(labels),
            st.one_of(st.none(), _DIGITS),
        ),
    )


@dc.dataclass(frozen=True, slots=True)
class _Segments:
    """The optional segments that may follow a release segment.

    PEP 440 orders them pre-release, post-release, then development, so
    ``render()`` can concatenate them in that order for any combination.
    """

    pre: str | None = None
    post: str | None = None
    dev: str | None = None

    def render(self) -> str:
        """Return the segments as they appear after the release segment."""
        return f"{self.pre or ''}{self.post or ''}{self.dev or ''}"

    @property
    def names_a_prerelease(self) -> bool:
        """Say whether the segments alone make the version a pre-release."""
        return self.pre is not None or self.dev is not None


_SEGMENTS = st.builds(
    _Segments,
    pre=_numbered(_PRE_LABELS),
    post=_numbered(_POST_LABELS),
    dev=_numbered(("dev",)),
)


@given(release=_RELEASE, segments=_SEGMENTS, local=_LOCAL)
@_SETTINGS
def test_a_version_is_a_prerelease_exactly_when_it_names_pre_or_dev(
    release: str, segments: _Segments, local: str | None
) -> None:
    """Every generated PEP 440 version is classified from its own segments."""
    version = f"{release}{segments.render()}{local or ''}"
    expected = segments.names_a_prerelease

    assert is_prerelease(version) is expected, (
        f"{version} must be classified as a pre-release={expected}"
    )


@given(release=_RELEASE, segments=_SEGMENTS, local=_LOCAL)
@_SETTINGS
def test_a_local_label_never_makes_a_release_a_prerelease(
    release: str, segments: _Segments, local: str | None
) -> None:
    """Stripping the local label must not change the public classification."""
    version = f"{release}{segments.render()}"
    labelled = f"{version}{local or ''}"

    assert is_prerelease(labelled) is is_prerelease(version), (
        f"{labelled} must be classified like its public part {version}"
    )
