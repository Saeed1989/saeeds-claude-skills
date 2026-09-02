# House conventions

**This file is meant to be edited.** It ships with defaults that suit most
HTTP APIs; replace any rule with your team's own and the skill will follow this
file rather than its defaults. If your API already has a convention that
contradicts something here, change the text — consistency with the existing API
beats consistency with this document.

## One shared Error schema

Every non-2xx response references the same schema. Clients write one error
handler instead of one per endpoint.

```yaml
components:
  schemas:
    Error:
      type: object
      required: [code, message]
      properties:
        code:
          type: string
          description: Stable, machine-readable. Clients branch on this.
        message:
          type: string
          description: Human-readable. May change without notice; do not parse.
        details:
          type: array
          items: { type: string }
          description: Per-field validation messages, when applicable.
  responses:
    Unauthorized:
      description: The bearer token is missing, expired or malformed.
      content:
        application/json:
          schema: { $ref: '#/components/schemas/Error' }
    NotFound:
      description: No resource with that identifier.
      content:
        application/json:
          schema: { $ref: '#/components/schemas/Error' }
    ValidationFailed:
      description: The request body failed validation.
      content:
        application/json:
          schema: { $ref: '#/components/schemas/Error' }
```

Operations then reference the response, not the schema:

```yaml
responses:
  '404': { $ref: '#/components/responses/NotFound' }
```

`code` values are part of the contract — changing one is a breaking change.
`message` is not; say so in its description so nobody parses it.

Document, at minimum: every auth failure (401/403), every validation failure
(400/422), and every lookup failure (404). An operation with only a 2xx
documented is an operation nobody can write a client for.

## Pagination

Pick **one** shape and use it for every list endpoint. The default here is
offset pagination with an envelope:

```yaml
OrderPage:
  type: object
  required: [items, page, limit, total]
  properties:
    items:
      type: array
      items: { $ref: '#/components/schemas/Order' }
    page:  { type: integer, description: 1-based page number. }
    limit: { type: integer, description: Items per page. }
    total: { type: integer, description: Total matching items across all pages. }
```

with shared parameters so every list endpoint agrees:

```yaml
components:
  parameters:
    Page:
      name: page
      in: query
      required: false
      schema: { type: integer, minimum: 1, default: 1 }
    Limit:
      name: limit
      in: query
      required: false
      schema: { type: integer, minimum: 1, maximum: 100, default: 20 }
```

If the API uses cursor pagination instead, replace the block above with the
cursor shape (`items`, `nextCursor`, `hasMore`) and delete this sentence. The
rule that matters is that there is exactly one shape, and that `default` and
`maximum` on `limit` reflect what the server actually enforces — a documented
maximum the code does not apply is a lie clients will build on.

Never return a bare array for a list. It leaves no room to add pagination
metadata later without a breaking change.

## Describing an endpoint in one line

`summary` is a **verb phrase, sentence case, no trailing period**, under about
60 characters. It is what appears in the collapsed endpoint list.

| Good | Bad | Why |
| --- | --- | --- |
| `Cancel an order` | `Order cancellation endpoint` | says what the caller does |
| `List orders, newest first` | `Get orders` | adds the ordering, which the caller cannot guess |
| `Reserve stock for an order` | `POST /reservations` | never restate the method and path |
| `Fetch one order` | `This endpoint fetches an order by its id` | no filler |

Use `description` for everything that does not fit: side effects, idempotency,
rate limits, what happens on retry, which fields are ignored on update, and
anything the caller would otherwise discover in production. `description` is
Markdown and can be several paragraphs — this is the part of the spec humans
actually read, and the part a regeneration must never overwrite.

## Tags

One tag per operation. Tags are the section headings in the rendered docs, so
they should match how a **consumer** groups the API — by resource (`orders`,
`customers`, `webhooks`), not by internal module or team ownership.

Declare every tag at the top level with a description; an undeclared tag still
renders but has no explanatory text:

```yaml
tags:
  - name: orders
    description: Create, read and cancel orders.
```

Rules of thumb: 3–10 tags for a typical service; if a tag has one operation,
merge it; if it has thirty, split it. Operational endpoints (`/health`,
`/metrics`) go under a `system` tag so they sort away from the business API.

## Versioning

- The version lives **in the URL path** — `/v1/orders`. It is visible in logs,
  curl commands and dashboards, unlike a header.
- `info.version` is the **API's** version, not the spec file's revision. Use
  semver: bump the major for breaking changes, minor for additive ones. Keep
  the URL major and `info.version` major in step.
- Additive changes ship in place. Breaking changes get a new path version, with
  the old one kept and marked `deprecated: true` until it is retired.
- Deprecate rather than delete: `deprecated: true` on the operation plus a
  `description` naming the replacement and the removal date. Removing an
  operation outright is what `diff_openapi.py` flags as BREAKING, and it should
  never be a surprise.

## Naming

- **Paths**: lowercase, plural nouns, hyphens for multi-word segments —
  `/v1/payment-methods`. No verbs (`/v1/orders/{id}/cancel` is acceptable when
  the action is genuinely not a resource; prefer it to `/cancelOrder`).
- **Fields**: match what the API actually puts on the wire. If the code emits
  `amount_cents`, document `amount_cents` — never "tidy" it to camelCase in the
  spec. Consistency is the code's job; the spec's job is accuracy.
- **operationId**: `camelCase`, verb + resource, unique — `listOrders`,
  `getOrder`, `createOrder`, `cancelOrder`. This becomes the method name in
  generated clients, so treat a rename as a breaking change.
- **Schemas**: `PascalCase`, singular — `Order`, `CreateOrderBody`, `OrderPage`.
  Suffix request bodies with `Body` and paginated envelopes with `Page` so the
  component list stays scannable.

## Money, times and ids

- Money as **integer minor units** with an explicit currency field
  (`amountCents: 1250`, `currency: "GBP"`). Never a float.
- Timestamps as `type: string, format: date-time`, RFC 3339, UTC. Dates without
  a time use `format: date`.
- Ids as strings even when the datastore uses integers — it leaves room to
  change the datastore, and JSON's number type loses precision above 2^53.
- Enums for closed sets, with every value listed. Adding a value is additive;
  removing one is breaking.
