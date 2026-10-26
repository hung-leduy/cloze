"""Reference monitor: the only dual-homed service in the system.

Every byte leaving the trusted zone passes through here, and the forwarding
path to the cloud is open only behind the full inspection chain. One chain,
one implementation, used by both the dry-run `/inspect` and the live proxy;
two copies of a security check drift, and the copy on the live path is the
one nobody re-reads.

Decode before you inspect, and inspect only what was decoded
-------------------------------------------------------------
The core sends JSON, and `json.dumps` escapes non-ASCII by default, so the
private string "Nguyễn Thị Lan" arrives on the wire as `Nguy\\u1ec5n Th\\u1ecb
Lan`. A containment filter run over the raw body sees the tokens `nguy`,
`u1ec5n`, `th`, `u1ecb`, `lan`, and misses. Measured: raw bytes -> not blocked;
decoded strings -> blocked. So every inspection here parses the body as JSON
when it can, walks every string in it — keys as well as values — and inspects
the decoded text. Unicode escaping is therefore not an evasion. When the body
does not parse, the raw text is what gets inspected.

Text that is not a string in the parsed body is not inspected here, and cannot
usefully be: an array of per-character integers carries no words for a
word-shingle filter to match. That is an encoding, in the same class as hex
and base64, and it is listed among what this system does not protect rather
than implied away.

One chain, one session, one continuous stream
---------------------------------------------
Shingles are contiguous, so a filter shown one request at a time cannot see a
span split across requests: measured, a 26-token passage sent as seven 4-token
requests crossed 7/7. The pipeline already issues one request per section, so
that traffic shape is the normal one rather than an exotic attack. The monitor
therefore carries the tail of each inspected egress payload into the next, and
inspects the join. The carry is reset when a new filter is sealed, which is
what starts a session. Single-user and single-session is a scope decision
(D1), and this is one of the places it shows: a multi-user monitor would need
one carry per session.

Direction asymmetry, stated
---------------------------
Outbound refusals block. Inbound findings do not: by the time a response
arrives the egress has already happened, and the trusted core needs to see a
canary in a reply in order to abort the session. A canary in a response is
logged CRITICAL and delivered; a containment hit in a response is logged and
delivered, since the cloud can only echo what it was given or guess a common
phrase, and either is a finding for the audit trail rather than a leak to
stop.

Non-streaming only. A streamed response would have to be released chunk by
chunk before the whole of it had been inspected. For a ten-page paper on a
short clock, whole-response inspection is the safer property and the simpler
one; `stream: true` is refused with a typed reason rather than silently
downgraded, so nobody discovers the limit by accident.

Audit before forwarding
-----------------------
No audit line, no delivery. Every record is one JSON line with sizes,
verdicts, upstream status and timing, and never content; every record of one
request carries the same random `request_id`.

* A refused request leaves one record (`verdict: "refused"`) and is never
  forwarded. If that record cannot be written the answer is 503
  `AUDIT_UNAVAILABLE` instead of the refusal, and it is still not forwarded.
* A request that passes the chain leaves a pre-forward record
  (`verdict: "forwarding"`) BEFORE the upstream is called. If that write fails
  the answer is 503 `AUDIT_UNAVAILABLE` and the upstream is never called.
* After the upstream answers, or fails, a second record gives the outcome
  under the same `request_id`: `allowed` with status, bytes and duration, or
  `upstream_error` / `proxy_error` with the exception's type name. If that
  write fails the reply is withheld from the core (503 `AUDIT_UNAVAILABLE`),
  but the pre-forward record already exists, so the log still shows that the
  request may have reached the cloud.

What this does not give: an outcome record for every pre-forward record. If
the second write fails, or the process dies or the request is cancelled
while the upstream call is in flight, the pre-forward record stands alone. A
reader must count a `forwarding` record with no outcome as a request that may
have been delivered, with its outcome unknown. A record counts as written
when the append has been closed without an OSError; it is not fsynced, and
the log is not tamper-evident. One writer per process is assumed (D1).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from linters.canary_matcher import CanaryMatcher
from linters.entropy_linter import scan_payload
from linters.regex_rules import RegexScreen
from pydantic import BaseModel

from shared.shingle_filter import ShingleFilter, tokenize

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("reference-monitor")

app = FastAPI(title="PrivDeep Reference Monitor", version="0.2.0")

ENTROPY_THRESHOLD = float(os.environ.get("SHANNON_ENTROPY_THRESHOLD", "4.85"))
STRICT_FAIL_CLOSED = os.environ.get("STRICT_FAIL_CLOSED", "true").lower() == "true"
SHINGLE_N_MIN = int(os.environ.get("SHINGLE_N_MIN", "5"))
SHINGLE_N_MAX = int(os.environ.get("SHINGLE_N_MAX", "8"))
SHINGLE_HIT_THRESHOLD = int(os.environ.get("SHINGLE_HIT_THRESHOLD", "1"))
# Shared out-of-band with the core (both read it from the environment). The
# sealed filter is useless without it and must never travel in-band.
SHINGLE_HMAC_SALT = os.environ.get("SHINGLE_HMAC_SALT", "").encode("utf-8")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
ANTHROPIC_VERSION = os.environ.get("ANTHROPIC_VERSION", "2023-06-01")
UPSTREAM_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "300"))
AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "/data/audit_eventlog.jsonl")

# The containment filter is populated by the core over internal IPC at session
# start. Until it is sealed, egress is refused under fail-closed: an empty
# filter would otherwise pass everything, which is the failure mode this whole
# component exists to prevent.
_shingle: ShingleFilter | None = None

# Per-JSON-path tails of the content seen so far, so a verbatim span split
# across requests is still shingled as one run. Written only by the live proxy
# path: `/inspect` is a dry run and must not be able to steer what the next
# real request is judged against. Insertion-ordered, evicted oldest-first.
_carry: dict[str, list[str]] = {}
# The value that produced each path's carry, so a schema constant repeated on
# every request (`"role": "user"`) is not chained to itself into a phantom run.
_carry_last: dict[str, str] = {}
_CARRY_MAX_PATHS = 64

# Active canaries, registered by the core at session start
# (CanaryInjector.register). An empty matcher blocks nothing; the unsealed-
# filter refusal is what keeps egress closed until session setup is done.
_canaries = CanaryMatcher()

# Additional deterministic screens plug in here as callables returning an
# object with .blocked and .reason. Kept as a list so the chain stays in one
# place and the order is visible. The regex screen catches what entropy and
# containment structurally cannot: short or low-entropy credentials and
# identifiers (API keys, JWTs, emails, national ids).
_EXTRA_SCREENS: list[Callable[[str], Any]] = [RegexScreen().scan]

# Upstream client. Created lazily so tests can install one with a mock
# transport before the first request; never created at import.
_upstream: httpx.AsyncClient | None = None


def _get_upstream() -> httpx.AsyncClient:
    global _upstream
    if _upstream is None:
        _upstream = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT)
    return _upstream


# --------------------------------------------------------------------------- inspection


@dataclass(frozen=True, slots=True)
class Refusal:
    reason: str
    level: int = logging.WARNING


def _string_leaves(obj: Any) -> Iterator[str]:
    """Every string in a decoded JSON structure, depth-first: keys as well as values.

    Keys were once skipped as "schema, not content". They are not: a JSON key
    is an attacker-chosen string in every request that carries a tool
    definition, and the Messages API has several such positions (a tool's
    `input_schema.properties`, `metadata`). Measured against the earlier
    values-only walker, a private sentence placed in a key yielded an inspected
    text of `'string'` and passed the whole chain — canary matcher, entropy
    screen, regex screen and containment filter alike, since all four are
    downstream of this function. Schema keys are short, low-entropy and
    unremarkable to every screen, so inspecting them costs nothing.
    """
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from _string_leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _string_leaves(v)


def _decoded_text(raw: bytes) -> tuple[str, Any]:
    """(text to inspect, parsed JSON or None). Falls back to the raw body as text."""
    body_text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body_text)
    except json.JSONDecodeError:
        return body_text, None
    # Decoded strings only, once the body parses, and not the serialisation:
    # the false-positive instrument measured the entropy screen refusing
    # 100/100 compact abstract payloads, because braces, quotes and hex slot
    # ids with no whitespace form one long high-entropy token. Decoding removes
    # the request envelope's own serialisation from that token, but NOT a
    # compact payload carried inside one message string: that is still one
    # long token once decoded, and the same instrument run through this chain
    # (EXP5) still refused 100/100. Decoding is also what closes the \uXXXX
    # evasion; the raw text is still what is inspected when the body is not JSON.
    #
    # What this does NOT see, stated so the limit is not rediscovered as a
    # finding: non-string scalars. A payload can carry text as an array of
    # per-character integers and arrive with nothing for these screens to read.
    # That is the same class as hex or base64 — an encoding, not a verbatim
    # span — and no word-shingle filter can catch it. It is recorded in
    # THREAT_MODEL.md under what is not protected, rather than papered over.
    return "\n".join(_string_leaves(parsed)), parsed


def _value_paths(obj: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    """Every string *value* with the JSON path it sits at.

    List indices collapse to `[]`, so `messages[0].content` and
    `messages[1].content` are one path. The path is the channel identity used
    to chain content across requests; see `_containment`.
    """
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _value_paths(v, f"{path}.{k}" if isinstance(k, str) else path)
    elif isinstance(obj, list):
        for v in obj:
            yield from _value_paths(v, path + "[]")


def _key_strings(obj: Any) -> Iterator[str]:
    """Every string *key*: schema positions, which an attacker also chooses."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from _key_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _key_strings(v)


def _containment(
    shingle: ShingleFilter, text: str, parsed: Any, advance_carry: bool
) -> Refusal | None:
    """Containment over per-channel content streams, plus the key stream.

    A shingle is a contiguous run, so what counts as "contiguous" decides what
    this check can see. Three attempts, and only the third survives contact:

    1. Whole decoded text per request. A passage split one chunk per request
       crosses untouched; measured 7/7 at four tokens a chunk.
    2. One rolling buffer over all string values. Better, but still 7/7 on a
       realistic body, because `model` and `role` are string values too and
       their tokens land between the chunks, breaking the run at every join.
    3. One buffer per JSON path. `$.messages[].content` accumulates only what
       was ever sent as message content, so the chunks chain and the fifth
       token of the run meets the first four, and `$.model` cannot break it.
       But a stream keyed by path is a stream the sender names: a review split
       the same passage four tokens per field across twenty invented top-level
       keys and it crossed in **one** request, which attempt 1 would have
       caught. Per-path chaining alone is a regression, not an improvement.

    So both, and a hit in either refuses:

    * **The whole-body content stream**, all string values concatenated in
      document order, per request and with no carry. This is attempt 1 minus
      the keys, and it is what catches a span scattered across fields however
      they are named.
    * **The per-path streams**, each chained to the same path in previous
      requests. This is what catches a span spread over several requests.

    Keys are a third stream, checked alone: they are sender-chosen, so skipping
    them let a private sentence cross as an object key, but they sit between
    content fields, so folding them into a content stream reintroduces the
    breakage of attempt 2.

    What this still does not close: a sender who both moves a span between
    paths *and* spreads it over requests, or who floods more than
    `_CARRY_MAX_PATHS` distinct paths to evict the path in use. Both require
    the sender to choose the request structure, which is the core — a
    compromised local tier, out of scope by §6 of the threat model. It is
    recorded in §5 rather than left implied.

    The path map is capped and evicted oldest-first, so a payload inventing
    thousands of distinct paths costs bounded memory.
    """
    global _carry, _carry_last
    carry = dict(_carry)

    if parsed is None:
        # Not JSON, or a caller handing us plain text: one anonymous channel.
        leaves: list[tuple[str, str]] = [("$", text)]
        keys = ""
    else:
        leaves = list(_value_paths(parsed))
        keys = "\n".join(_key_strings(parsed))

    blocked: Refusal | None = None

    # Stream one: the whole body's content, in document order, this request
    # only. Catches a span scattered across fields whatever they are called.
    whole = tokenize("\n".join(leaf for _, leaf in leaves))
    if whole:
        v = shingle.inspect_tokens(whole)
        if v.blocked:
            blocked = Refusal(v.reason)

    # Stream two: one per path, chained to earlier requests on the same path.
    last_value: dict[str, str] = _carry_last
    seen_value = dict(last_value)
    for path, leaf in leaves:
        toks = tokenize(leaf)
        if not toks:
            continue
        # A value identical to the one that produced this path's carry cannot
        # continue a run; it can only manufacture a join. `"role": "user"` is
        # sent on every request, and chaining it to itself built a five-token
        # run out of nothing and refused the session permanently.
        prior = [] if seen_value.get(path) == leaf else carry.get(path, [])
        stream = prior + toks
        seen_value[path] = leaf
        carry.pop(path, None)
        carry[path] = shingle.carry_tokens(stream)   # re-inserted: newest last
        if len(carry) > _CARRY_MAX_PATHS:
            oldest = next(iter(carry))
            carry.pop(oldest)
            seen_value.pop(oldest, None)
        if blocked is None:
            v = shingle.inspect_tokens(stream)
            if v.blocked:
                blocked = Refusal(v.reason)

    if blocked is None and keys:
        v = shingle.inspect_tokens(tokenize(keys))
        if v.blocked:
            blocked = Refusal(v.reason)

    # Only a payload that is actually delivered joins the stream. A refused one
    # never crossed, so counting it would be wrong twice: it would report a span
    # as having left when it did not, and it would leave the refused tokens in
    # the carry to collide with the next legitimate request, turning one refusal
    # into a cascade of them.
    if advance_carry and blocked is None:
        _carry = carry
        _carry_last = seen_value
    return blocked


def _inspect_text(
    text: str, *, parsed: Any = None, advance_carry: bool = False
) -> Refusal | None:
    """The chain. Returns the first refusal, or None if the payload may leave.

    Containment runs over two streams rather than one, because contiguity and
    coverage pull in opposite directions here:

    * **The content stream** is the string *values* in document order, joined
      to the tail of the previous payload's content. Values are prose, so
      shingles must run continuously through them — across fields and across
      requests — or per-section drafting alone defeats the filter.
    * **The key stream** is the string *keys*, checked on their own. Keys are
      attacker-choosable too, so they cannot be skipped; but they are schema
      sitting between content fields, so folding them into the content stream
      would insert noise tokens at every field boundary and break exactly the
      contiguity the carry exists to restore. Measured: with keys interleaved,
      a passage split one chunk per request crossed 7/7 even with the carry in
      place.

    The other three screens see the whole decoded text, keys included; none of
    them depends on contiguity.

    `advance_carry` is set by the live egress path only. `/inspect` leaves the
    carry alone, so a dry run can neither be poisoned nor poison the next real
    request.
    """
    global _carry
    # Canaries first. A planted token on the wire is proof of a context leak,
    # the highest-severity finding this monitor can make; no other verdict may
    # mask it.
    canary = _canaries.scan(text)
    if canary.blocked:
        return Refusal(canary.reason, logging.CRITICAL)

    entropy = scan_payload(text, threshold=ENTROPY_THRESHOLD)
    if entropy.blocked:
        return Refusal(entropy.reason)

    for screen in _EXTRA_SCREENS:
        v = screen(text)
        if v.blocked:
            return Refusal(v.reason)

    if _shingle is None or not _shingle.sealed:
        if STRICT_FAIL_CLOSED:
            return Refusal("CONTAINMENT_FILTER_UNSEALED: refusing under fail-closed")
        return None
    return _containment(_shingle, text, parsed, advance_carry)


def _inbound_findings(text: str) -> list[str]:
    """Findings on a response. Logged, never blocking (see module docstring)."""
    out: list[str] = []
    c = _canaries.scan(text)
    if c.blocked:
        out.append(f"CANARY_IN_RESPONSE: {c.hits}")
        log.critical("canary token(s) present in an upstream RESPONSE: %d", c.hits)
    if _shingle is not None and _shingle.sealed:
        v = _shingle.inspect(text)
        if v.blocked:
            out.append(f"CONTAINMENT_HIT_IN_RESPONSE: {v.hit_count}")
            log.warning("containment hit(s) in an upstream response: %d", v.hit_count)
    return out


# --------------------------------------------------------------------------- audit


class AuditWriteError(RuntimeError):
    pass


def _audit(record: dict[str, Any]) -> None:
    """Append one JSON line. Raises if it cannot; the caller then does not forward
    (pre-forward record) or withholds the reply (outcome record)."""
    record.setdefault("ts", time.time())
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.error("AUDIT WRITE FAILED (%s); egress cannot be accounted for", exc)
        raise AuditWriteError(str(exc)) from exc


# --------------------------------------------------------------------------- control plane


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "reference-monitor",
        "containment_filter": "sealed" if (_shingle and _shingle.sealed) else "unsealed",
        "fail_closed": STRICT_FAIL_CLOSED,
        "canaries": len(_canaries),
        "extra_screens": len(_EXTRA_SCREENS),
        "upstream": ANTHROPIC_BASE_URL,
        "api_key_present": bool(ANTHROPIC_API_KEY),
    }


class CanaryRegistration(BaseModel):
    tokens: list[str]


@app.post("/canaries")
def register_canaries(body: CanaryRegistration) -> JSONResponse:
    """Add this session's canary tokens to the active set. Values are never logged."""
    try:
        _canaries.add(body.tokens)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    registered = len(set(body.tokens))
    log.info("registered %d canary token(s); %d active", registered, len(_canaries))
    return JSONResponse({"registered": registered, "active": len(_canaries)})


@app.post("/containment/seal")
async def seal_containment(request: Request) -> JSONResponse:
    """Install the core's sealed containment filter. Body = ShingleFilter.to_wire().

    Refuses to seal without a salt: an unsalted filter would install cleanly
    and then match nothing, which is the one failure mode worse than staying
    unsealed. The wire carries the shingling parameters, so a mismatch between
    the two sides is impossible rather than merely unlikely.

    The monitor does not take its decision policy from the party it monitors.
    Three things follow, and all three were reachable before they were added:

    * `hit_threshold` comes from this service's own configuration, not from the
      header. A wire carrying `10**9` used to seal cleanly, leave `n_added`
      untouched so the core's own confirmation check passed, report `sealed`
      on `/health`, and admit every verbatim span.
    * `n_min`/`n_max` must equal this service's policy. These cannot be
      overridden the way the threshold can — the bits were built for a specific
      n, so querying a different one would silently miss every lookup — so a
      mismatch is refused instead.
    * An empty filter is refused. It too used to seal and report healthy.

    Sealing starts a session, so it also clears the cross-request carry.
    """
    global _shingle, _carry, _carry_last
    if not SHINGLE_HMAC_SALT:
        log.error("seal refused: SHINGLE_HMAC_SALT is not set on the gateway")
        return JSONResponse({"sealed": False, "reason": "NO_SALT"}, status_code=503)
    try:
        f = ShingleFilter.from_wire(
            await request.body(),
            salt=SHINGLE_HMAC_SALT,
            hit_threshold=SHINGLE_HIT_THRESHOLD,
            require_n=(SHINGLE_N_MIN, SHINGLE_N_MAX),
            require_non_empty=True,
        )
    except ValueError as exc:
        return JSONResponse({"sealed": False, "reason": f"BAD_WIRE: {exc}"}, status_code=422)
    _shingle = f
    _carry = {}
    _carry_last = {}
    b = f.bloom
    log.info("containment filter sealed: %d shingles, %d bits, k=%d, fp~%.1e, n=%d..%d",
             b.n_added, b.m_bits, b.k, b.estimated_fp_rate(), f.n_min, f.n_max)
    return JSONResponse({
        "sealed": True, "n_added": b.n_added, "m_bits": b.m_bits, "k": b.k,
        "n_min": f.n_min, "n_max": f.n_max, "hit_threshold": f.hit_threshold,
    })


# --------------------------------------------------------------------------- data plane


@app.post("/inspect")
async def inspect(request: Request) -> JSONResponse:
    """Dry run of the chain on an arbitrary payload. Refusal is the default outcome."""
    try:
        text, parsed = _decoded_text(await request.body())
        r = _inspect_text(text, parsed=parsed)  # dry run: never advances the carry
        if r:
            return _refuse(r)
        return JSONResponse({"allowed": True})
    except Exception:
        log.exception("inspection raised; refusing")
        return _refuse(Refusal("INSPECTION_ERROR: refusing under fail-closed"))


@app.post("/v1/messages")
async def proxy_messages(request: Request) -> Response:
    """The live egress path: inspect, audit, forward to the Messages API, inspect the reply.

    The order is the guarantee: the pre-forward record is written before the
    upstream is called, and a failed write means the upstream is never called.
    Every record after that point is an outcome for a request the cloud may
    already hold, and says so by sharing the pre-forward record's `request_id`.
    """
    t0 = time.time()
    raw = await request.body()
    rec: dict[str, Any] = {"direction": "egress", "path": "/v1/messages", "bytes_in": len(raw),
                           "request_id": uuid.uuid4().hex}
    forwarded = False

    def elapsed() -> int:
        return int((time.time() - t0) * 1000)

    try:
        text, parsed = _decoded_text(raw)
        rec["model"] = _audit_model(parsed.get("model")) if isinstance(parsed, dict) else None

        if not ANTHROPIC_API_KEY:
            rec.update(verdict="refused", reason="NO_API_KEY")
            _audit(rec)
            return _refuse(Refusal("NO_API_KEY: gateway has no cloud credential"), status=503)

        if isinstance(parsed, dict) and parsed.get("stream"):
            rec.update(verdict="refused", reason="STREAMING_NOT_SUPPORTED")
            _audit(rec)
            return _refuse(Refusal("STREAMING_NOT_SUPPORTED: whole-response inspection only"),
                           status=400)

        refusal = _inspect_text(text, parsed=parsed, advance_carry=True)
        if refusal:
            rec.update(verdict="refused", reason=refusal.reason, elapsed_ms=elapsed())
            _audit(rec)
            return _refuse(refusal)

        # No audit line, no delivery: this write raising AuditWriteError is the
        # 503 below, and the upstream is never called.
        _audit({**rec, "verdict": "forwarding", "elapsed_ms": elapsed()})
        forwarded = True
        up = await _get_upstream().post(
            f"{ANTHROPIC_BASE_URL}/v1/messages",
            content=raw,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )
        rec.update(upstream_status=up.status_code, bytes_out=len(up.content))
        resp_text, _ = _decoded_text(up.content)
        flags = _inbound_findings(resp_text)
        rec.update(verdict="allowed", response_flags=flags, elapsed_ms=elapsed())
        # The pre-forward record already exists. If this outcome record cannot
        # be written, the reply is withheld from the core (503 below).
        _audit(rec)
        return Response(
            content=up.content, status_code=up.status_code,
            media_type=up.headers.get("content-type", "application/json"),
        )
    except AuditWriteError:
        return _refuse(Refusal("AUDIT_UNAVAILABLE: egress cannot be accounted for"), status=503)
    except httpx.TransportError as exc:
        log.error("upstream transport error: %s", exc)
        _audit_best_effort(rec, verdict="upstream_error", reason=type(exc).__name__,
                           elapsed_ms=elapsed())
        return _refuse(Refusal(f"UPSTREAM_UNREACHABLE: {type(exc).__name__}"), status=502)
    except Exception as exc:
        log.exception("proxy raised; refusing")
        if forwarded:
            # The upstream may hold the request, or has answered it: an outcome.
            _audit_best_effort(rec, verdict="proxy_error", reason=type(exc).__name__,
                               elapsed_ms=elapsed())
        else:
            _audit_best_effort(rec, verdict="refused",
                               reason=f"PROXY_ERROR: {type(exc).__name__}", elapsed_ms=elapsed())
        return _refuse(Refusal("PROXY_ERROR: refusing under fail-closed"))


def _audit_best_effort(rec: dict[str, Any], **fields: Any) -> None:
    """Write a record on a path that is already refusing; a failed write is logged, not raised.

    Used only where the core gets no reply content either way, so a missing
    line here withholds nothing that would otherwise have been delivered.
    """
    rec.pop("ts", None)
    rec.update(fields)
    try:
        _audit(rec)
    except AuditWriteError:
        pass


def _refuse(r: Refusal, status: int = 403) -> JSONResponse:
    log.log(r.level, "egress refused: %s", r.reason)
    return JSONResponse({"allowed": False, "reason": r.reason}, status_code=status)


# --------------------------------------------------------------------------- audit fields

# The model ids the record may name: the one CloudClient sends, read from the
# same CLOUD_MODEL variable with the same default. The field is read from the
# request body before inspection, so it is written on refused records too, and
# copying a sender-chosen value would put whatever it carried, the private text
# a refusal was for included, into a log that holds no message text.
_AUDIT_MODEL_IDS = frozenset({os.environ.get("CLOUD_MODEL", "claude-sonnet-5")})


def _audit_model(value: Any) -> str | None:
    """The request's model for the audit record: a listed id, None when absent,
    and "unlisted" for any other value, whatever its type or length."""
    if value is None:
        return None
    if isinstance(value, str) and value in _AUDIT_MODEL_IDS:
        return value
    return "unlisted"
