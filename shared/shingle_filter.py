"""Deterministic containment check for raw C_user at the egress boundary.

Why this exists
---------------
The harness spec enforces the Zero-Raw-Context Egress Invariant with an entropy
linter, a regex ruleset and a canary matcher. None of the three can recognise
raw user text:

* the entropy linter fires only on whitespace tokens longer than 24 characters
  with H(X) > 4.85 bits/char, and ordinary private prose has no token that
  long, so it is never scored at all: `scan_payload` returns an empty
  `worst_token` and `blocked=False`. (The document-level entropy of such prose
  is about 4.2 bits/char, under the threshold as well, but that is not the
  quantity the linter computes and not the reason prose passes.)
* the regex rules match API keys, UUIDs and IP addresses, which is not what the
  invariant protects;
* the canary matcher matches only tokens the system itself planted.

So the sentence "Project Zephyr's Q3 revenue fell 12% after the Hanoi pilot was
cancelled" crosses the reference monitor unexamined, and the only thing standing
between the corpus and the network is a 14B model asked nicely to redact. That
is a probabilistic mechanism carrying an absolute invariant.

This module supplies the missing deterministic half.

How it works
------------
At ingest, every overlapping word n-gram of C_user (n in [n_min, n_max]) is
normalised, HMAC'd under a per-install secret salt, and inserted into a Bloom
filter. The gateway holds the filter and the salt, never the corpus: it needs
the salt to shingle the outbound payload the same way. At egress, that
shingling is applied and the filter is queried; a hit count at or above the
threshold blocks the request.

What this buys, stated precisely
--------------------------------
* **Deterministic for verbatim spans.** Any contiguous run of n_min or more
  words copied from the corpus is caught, with no model in the loop and no
  nondeterminism. This is CI-testable and a referee can re-run it.
* **Does not put the corpus on the gateway, but is a membership oracle there.**
  The filter stores salted HMAC digests in a bit array. Without the salt it
  cannot be inverted or enumerated. The gateway is not without the salt: it
  reads SHINGLE_HMAC_SALT from its environment, because it must shingle the
  payload exactly as the core shingled the corpus. So whoever holds the salt,
  including an attacker who compromises the monitor, can test any guessed
  shingle (a run of n_min..n_max words) for membership in C_user, up to the
  filter's false-positive rate. The filter does not enumerate the corpus, but
  it confirms guesses: with the surrounding words known or guessed, one slot
  drawn from a small space (a figure, a date, a name from a short list) is
  confirmed or refuted by one filter lookup per candidate. That is still much
  less than the obvious alternative, shipping C_user to the gateway so it can
  substring-match, which would place the private corpus itself on the only
  dual-homed container in the system.
* **Nothing more.** It does not catch paraphrase, translation, summary or
  arithmetic derivation. Invariant 1 must therefore be restated honestly:
  deterministic for verbatim spans, best-effort for everything else. Claiming
  otherwise is the overclaim the audit flagged.

What "verbatim" has to mean for that to be true
-----------------------------------------------
An exact-match filter is only as good as its notion of sameness, and the naive
one is much narrower than a reader's. Four classes of rewrite leave the text
looking identical and were measured crossing earlier versions of this filter: a
different Unicode normal form (NFD Vietnamese tokenises as `nguye` + `n`), a
confusable letter from another script, a compatibility form such as fullwidth
Latin, and any default-ignorable character placed inside a word. `tokenize`
folds all four, and the ignorable set is the whole
Default_Ignorable_Code_Point range rather than the obvious members: a review
put a combining grapheme joiner in every word and moved the corpus across a
version that enumerated only zero-width space and soft hyphen.

Where the span sits is a separate question from how it is spelled, and not one
tokenisation can answer. Splitting a run across requests, or across fields
within a request, is handled by the monitor, which inspects several token
streams per payload; see `gateway/main.py` `_containment` and §4.1 of
THREAT_MODEL.md for which shapes that does and does not cover.

Still not caught, and not claimed to be: any encoding of the text (hex, base64,
per-character integers) — the bytes no longer contain the words, so no
word-shingle filter can see them, and the entropy screen is the mechanism
nominally responsible there. Reordering, and interleaving filler between every
few words, also survive; both are cheap for a model to perform and neither is
paraphrase, so the "verbatim" claim should be read as covering contiguous runs
in reading order.

False positives are real and are the operating cost: a legitimate payload that
happens to reproduce n_min consecutive words of the corpus is refused. The rate
is a function of filter sizing and n_min and is measured, not assumed. See
`estimated_fp_rate` and the tests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import struct
import unicodedata
from dataclasses import dataclass, field

__all__ = ["BloomFilter", "ShingleFilter", "ShingleVerdict", "tokenize"]

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Unicode's Default_Ignorable_Code_Point set, pinned as a literal rather than
# derived from `unicodedata` at import: the gateway and the core must tokenise
# identically or every lookup silently misses, and a derived set would make
# that depend on each container's Unicode data version.
#
# These render as nothing, so a reader sees the same words. Most are `\W` to
# the word regex and split one token into two; U+115F, U+1160, U+3164 and
# U+FFA0 are the opposite case, word characters that insert a phantom letter.
# Either way the token no longer matches the index, so all of them are removed
# before tokenising, never after, because the split happens at match time.
#
# An earlier version enumerated only the obvious ranges and missed U+034F,
# U+061C, the variation selectors and the Mongolian selectors; a review put one
# of those inside every word and moved the whole corpus across.
_IGNORABLE_RE = re.compile(
    "["
    "\u00ad"                    # SOFT HYPHEN
    "\u034f"                    # COMBINING GRAPHEME JOINER
    "\u061c"                    # ARABIC LETTER MARK
    "\u115f\u1160"              # HANGUL CHOSEONG/JUNGSEONG FILLER
    "\u17b4\u17b5"              # KHMER VOWEL INHERENT AQ/AA
    "\u180b-\u180f"             # MONGOLIAN FREE VARIATION SELECTORS
    "\u200b-\u200f"             # ZERO WIDTH SPACE .. RIGHT-TO-LEFT MARK
    "\u202a-\u202e"             # BIDI EMBEDDING / OVERRIDE CONTROLS
    "\u2060-\u206f"             # WORD JOINER .. NOMINAL DIGIT SHAPES
    "\u3164"                    # HANGUL FILLER
    "\ufe00-\ufe0f"             # VARIATION SELECTOR-1 .. 16
    "\ufeff"                    # ZERO WIDTH NO-BREAK SPACE / BOM
    "\uffa0"                    # HALFWIDTH HANGUL FILLER
    "\ufff0-\ufff8"             # unassigned, default-ignorable
    "\U0001bca0-\U0001bca3"     # SHORTHAND FORMAT CONTROLS
    "\U0001d173-\U0001d17a"     # MUSICAL SYMBOL BEGIN/END controls
    "\U000e0000-\U000e0fff"     # TAGS, VARIATION SELECTORS SUPPLEMENT
    "]"
)

# Confusable folding, applied after casefolding. Cyrillic and Greek letters
# that are visually identical to Latin ones survive NFKC, because they are
# distinct characters with distinct meanings, not compatibility variants. One
# substituted character defeats an exact-match filter while leaving the text
# readable, which makes this the cheapest evasion of the lot.
#
# This is a subset of the Latin-confusable set, not UTS #39: the Cyrillic,
# Greek and Armenian homoglyphs reachable from a keyboard. It does not cover
# the full confusables table, and there is no mixed-script detection. Note the
# threshold interacts with the coverage: at hit_threshold=1 a single unfolded
# homoglyph is not enough to cross, because the untouched shingles elsewhere in
# the span still hit — an evader has to break every n_min window, which means
# one confusable in every five-word run.
_CONFUSABLES = str.maketrans({
    # Cyrillic -> Latin
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m",
    "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "ѕ": "s", "і": "i", "ј": "j",
    "һ": "h", "ё": "e", "ԛ": "q", "ԝ": "w", "ѵ": "v",
    # Greek -> Latin
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i",
    "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
    "υ": "y", "χ": "x", "ϲ": "c", "ϳ": "j", "ϱ": "p",
    # Armenian -> Latin
    "օ": "o", "ո": "n", "ս": "u", "զ": "q", "ց": "g",
    "գ": "g", "հ": "h", "լ": "l", "ք": "f",
    # Latin letters that are themselves confusables for other Latin letters
    "ɑ": "a", "ɡ": "g", "ɩ": "i", "ɔ": "o",
})


def tokenize(text: str) -> list[str]:
    """Words, normalised and casefolded. Punctuation and whitespace are separators.

    Four normalisations, each closing a measured evasion of an exact-match
    filter. All of them preserve what a human reads, which is the test for
    whether a transformation belongs here:

    * **NFKC.** Folds compatibility variants, so fullwidth ``Ｐｒｏｊｅｃｔ``
      is ``project``. It also composes, so a corpus stored NFC and a payload
      sent NFD agree. That case is not hypothetical here: the corpus is
      Vietnamese, ``ingest.md`` preserves whichever form the file was saved in,
      and decomposed diacritics are ``\\W``, so ``Nguyễn`` tokenises as
      ``nguye`` + ``n`` and misses the index entirely.
    * **Casefold** before confusable folding, so the table needs one case.
    * **Confusable folding**, see ``_CONFUSABLES``.
    * **Default-ignorable stripping**, so a zero-width space inside a word does
      not split it.

    Normalisation stops here. Stemming or stopword removal would start matching
    paraphrase, and every step in that direction trades a lower miss rate for a
    higher false-refusal rate on innocent payloads.

    Both sides of the boundary import this function from this module, and the
    module is mounted byte-identical into the gateway, so the index and the
    lookup cannot disagree about what a token is.
    """
    t = unicodedata.normalize("NFKC", text).casefold()
    t = t.translate(_CONFUSABLES)
    t = _IGNORABLE_RE.sub("", t)
    return _WORD_RE.findall(t)


# Retained for the modules and tests that imported the private name before it
# was part of the interface.
_tokenize = tokenize


class BloomFilter:
    """Bit-array Bloom filter with HMAC-derived hashes.

    Hand-rolled rather than pulled from a dependency so that a referee can read
    the whole mechanism in one screen, and so the digest construction is
    explicitly keyed. `k` indices come from slicing one HMAC-SHA256 digest,
    which is standard practice and avoids k separate hash passes.
    """

    __slots__ = ("m_bits", "k", "_salt", "_bits", "_n_added")

    def __init__(self, m_bits: int, k: int, salt: bytes) -> None:
        if m_bits <= 0 or k <= 0:
            raise ValueError("m_bits and k must be positive")
        if not salt:
            raise ValueError("salt must be non-empty; an unsalted filter is invertible by guessing")
        self.m_bits = m_bits
        self.k = k
        self._salt = salt
        self._bits = bytearray((m_bits + 7) // 8)
        self._n_added = 0

    @staticmethod
    def sized_for(n_items: int, fp_rate: float, salt: bytes) -> BloomFilter:
        """Size for `n_items` at a target false-positive rate.

        m = -n ln(p) / (ln 2)^2 and k = (m/n) ln 2 are the standard optima.
        """
        if n_items <= 0:
            n_items = 1
        if not (0.0 < fp_rate < 1.0):
            raise ValueError("fp_rate must be in (0, 1)")
        m = math.ceil(-n_items * math.log(fp_rate) / (math.log(2) ** 2))
        k = max(1, round((m / n_items) * math.log(2)))
        return BloomFilter(m_bits=m, k=k, salt=salt)

    def _indices(self, item: bytes):
        # One keyed digest, sliced into k indices. Extend the digest only if k
        # is large enough to exhaust 32 bytes.
        need = self.k * 4
        digest = b""
        counter = 0
        while len(digest) < need:
            digest += hmac.new(
                self._salt, item + counter.to_bytes(2, "big"), hashlib.sha256
            ).digest()
            counter += 1
        for i in range(self.k):
            yield int.from_bytes(digest[i * 4 : i * 4 + 4], "big") % self.m_bits

    def add(self, item: bytes) -> None:
        for idx in self._indices(item):
            self._bits[idx >> 3] |= 1 << (idx & 7)
        self._n_added += 1

    def __contains__(self, item: bytes) -> bool:
        return all(self._bits[idx >> 3] & (1 << (idx & 7)) for idx in self._indices(item))

    @property
    def n_added(self) -> int:
        return self._n_added

    @property
    def bits_set(self) -> int:
        return sum(bin(b).count("1") for b in self._bits)

    def estimated_fp_rate(self) -> float:
        """FP rate implied by the bits actually set, not by the design target."""
        frac = self.bits_set / self.m_bits if self.m_bits else 0.0
        return frac**self.k

    # Wire format. The core builds the filter inside the partition and ships the
    # sealed bits to the gateway; the salt never travels in-band (both sides read
    # it from the environment). No MAC: the seal request crosses only
    # privdeep-internal, and an adversary who can tamper there is already inside
    # the trusted zone, where this filter is not the thing protecting anything.
    _MAGIC = b"PDBF"
    _VERSION = 1
    _HEADER = struct.Struct("!4sBQHQ")  # magic, version, m_bits, k, n_added

    def to_bytes(self) -> bytes:
        header = self._HEADER.pack(self._MAGIC, self._VERSION, self.m_bits, self.k, self._n_added)
        return header + bytes(self._bits)

    @classmethod
    def from_bytes(cls, data: bytes, salt: bytes) -> BloomFilter:
        if len(data) < cls._HEADER.size:
            raise ValueError("bloom wire data truncated")
        magic, version, m_bits, k, n_added = cls._HEADER.unpack_from(data)
        if magic != cls._MAGIC:
            raise ValueError("bloom wire data has wrong magic")
        if version != cls._VERSION:
            raise ValueError(f"bloom wire version {version} unsupported")
        bits = data[cls._HEADER.size :]
        if len(bits) != (m_bits + 7) // 8:
            raise ValueError("bloom wire data length does not match m_bits")
        bf = cls(m_bits=m_bits, k=k, salt=salt)
        bf._bits = bytearray(bits)
        bf._n_added = n_added
        return bf


@dataclass(frozen=True)
class ShingleVerdict:
    """Outcome of one egress inspection."""

    blocked: bool
    hit_count: int
    threshold: int
    matched_shingles: tuple[str, ...] = field(default=())

    @property
    def reason(self) -> str:
        if not self.blocked:
            return "OK"
        return f"RAW_CONTEXT_CONTAINMENT: {self.hit_count} shingle hit(s) >= {self.threshold}"


class ShingleFilter:
    """Blocks egress payloads containing verbatim spans of C_user."""

    def __init__(
        self,
        salt: bytes,
        n_min: int = 5,
        n_max: int = 8,
        hit_threshold: int = 1,
        target_fp_rate: float = 1e-7,
    ) -> None:
        if n_min < 2:
            # Below ~5 the false-refusal rate on ordinary English becomes
            # unusable; 2 is the absolute floor the code will accept at all.
            raise ValueError("n_min must be >= 2")
        if n_max < n_min:
            raise ValueError("n_max must be >= n_min")
        if hit_threshold < 1:
            # A threshold of 0 blocks everything and a negative one is
            # meaningless, but the case that matters is the large value: this
            # parameter arrives over the wire in `from_wire`, and an unchecked
            # 10**9 seals cleanly, reports healthy, and passes every payload.
            # The gateway overrides it with its own policy anyway; this is the
            # floor under that.
            raise ValueError("hit_threshold must be >= 1")
        self.n_min = n_min
        self.n_max = n_max
        self.hit_threshold = hit_threshold
        self._salt = salt
        self._target_fp = target_fp_rate
        self._bloom: BloomFilter | None = None
        self._pending: list[bytes] = []

    @staticmethod
    def _shingles(tokens: list[str], n_min: int, n_max: int):
        for n in range(n_min, n_max + 1):
            if len(tokens) < n:
                continue
            for i in range(len(tokens) - n + 1):
                yield " ".join(tokens[i : i + n])

    def index_document(self, text: str) -> int:
        """Register one document's shingles. Returns how many were added."""
        if self._bloom is not None:
            raise RuntimeError("filter is sealed; index every document before sealing")
        tokens = _tokenize(text)
        before = len(self._pending)
        for sh in self._shingles(tokens, self.n_min, self.n_max):
            self._pending.append(sh.encode("utf-8"))
        return len(self._pending) - before

    def seal(self) -> None:
        """Build the Bloom filter. Sizing needs the final count, so it happens once."""
        self._bloom = BloomFilter.sized_for(len(self._pending) or 1, self._target_fp, self._salt)
        for item in self._pending:
            self._bloom.add(item)
        self._pending.clear()

    def inspect(self, payload: str, *, collect: bool = False) -> ShingleVerdict:
        """Inspect an outbound payload.

        `collect` returns the offending shingles for the audit log. It is off by
        default because those strings ARE corpus text: writing them into a log
        the gateway can reach would reintroduce the leak this class prevents.
        Enable it only for local forensics inside the trusted zone.
        """
        return self.inspect_tokens(tokenize(payload), collect=collect)

    def inspect_tokens(self, tokens: list[str], *, collect: bool = False) -> ShingleVerdict:
        """Inspect an already-tokenised payload.

        Separate from `inspect` so the caller can prepend carry-over tokens
        from the previous payload. Shingling is contiguous within one call, so
        a filter that only ever sees one request at a time cannot catch a span
        split across requests: measured, a 26-token passage sent as seven
        4-token requests crossed 7/7 with n_min=5. The monitor supplies that
        continuity; see `carry_tokens`.
        """
        if self._bloom is None:
            raise RuntimeError("filter not sealed; call seal() after indexing")
        hits = 0
        matched: list[str] = []
        for sh in self._shingles(tokens, self.n_min, self.n_max):
            if sh.encode("utf-8") in self._bloom:
                hits += 1
                if collect:
                    matched.append(sh)
                if not collect and hits >= self.hit_threshold:
                    break  # fail closed as soon as the verdict is decided
        return ShingleVerdict(
            blocked=hits >= self.hit_threshold,
            hit_count=hits,
            threshold=self.hit_threshold,
            matched_shingles=tuple(matched),
        )

    def carry_tokens(self, tokens: list[str]) -> list[str]:
        """The tail to prepend to the next payload, so a span split across two
        payloads is still shingled as one contiguous run.

        `n_max - 1` tokens is exactly enough: any shingle straddling the join
        has at most `n_max - 1` tokens on the earlier side.
        """
        return tokens[-(self.n_max - 1):] if self.n_max > 1 else []

    @property
    def sealed(self) -> bool:
        return self._bloom is not None

    @property
    def bloom(self) -> BloomFilter:
        if self._bloom is None:
            raise RuntimeError("filter not sealed")
        return self._bloom

    # Wire form for POST /containment/seal: one JSON header line carrying the
    # shingling parameters the gateway must reproduce exactly, then the bloom
    # bytes. If n_min/n_max differed between the two sides, every lookup would
    # silently miss, so they travel with the filter rather than being assumed.
    def to_wire(self) -> bytes:
        header = json.dumps(
            {"n_min": self.n_min, "n_max": self.n_max, "hit_threshold": self.hit_threshold}
        ).encode("utf-8")
        return header + b"\n" + self.bloom.to_bytes()

    @classmethod
    def from_wire(
        cls,
        data: bytes,
        salt: bytes,
        *,
        hit_threshold: int | None = None,
        require_n: tuple[int, int] | None = None,
        require_non_empty: bool = False,
    ) -> ShingleFilter:
        """Rebuild a sealed filter from the wire.

        The three keyword arguments exist because the party that sends this
        wire is the party the filter constrains. A reference monitor that takes
        its decision policy from the monitored side is not enforcing anything,
        so the gateway passes its own configured values here:

        * `hit_threshold` overrides whatever the header carries. It is a policy
          number, not a construction parameter, so the monitor owns it.
        * `require_n` refuses a header whose shingle lengths differ from the
          monitor's policy. Unlike the threshold this cannot be overridden: the
          bits were built for a specific n, so looking up a different n would
          silently miss on every query. Refusing is the only safe response.
        * `require_non_empty` refuses a filter with nothing in it, which would
          otherwise seal, report healthy, and admit every payload.
        """
        nl = data.find(b"\n")
        if nl == -1:
            raise ValueError("shingle wire data missing header")
        try:
            h = json.loads(data[:nl].decode("utf-8"))
            n_min, n_max, thr = int(h["n_min"]), int(h["n_max"]), int(h["hit_threshold"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("shingle wire header malformed") from exc
        if require_n is not None and (n_min, n_max) != require_n:
            raise ValueError(
                f"shingle parameters {(n_min, n_max)} do not match monitor policy {require_n}"
            )
        f = cls(salt=salt, n_min=n_min, n_max=n_max,
                hit_threshold=thr if hit_threshold is None else hit_threshold)
        f._bloom = BloomFilter.from_bytes(data[nl + 1 :], salt)
        if require_non_empty and f._bloom.n_added <= 0:
            raise ValueError("shingle filter is empty; refusing to seal a filter matching nothing")
        return f
