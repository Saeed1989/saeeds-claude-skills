# OpenAPI 3.1 reference

Targets **3.1.0**, which is a strict superset of JSON Schema 2020-12. The
differences from 3.0 are small in number and large in consequence — most specs
that "look fine but break the tooling" are 3.0 habits in a 3.1 document.

## Document structure

```yaml
openapi: 3.1.0
info:
  title: Orders API          # required
  version: 1.4.0             # required — the API version, not the spec's
  description: |
    Markdown. Renders above the endpoint list in Swagger UI.
servers:
  - url: https://api.example.com
  - url: https://sandbox.example.com
tags:
  - name: orders
    description: Create, read and cancel orders.
security:                    # document-wide default; operations may override
  - bearerAuth: []
paths:
  /v1/orders:
    get: { ... }
components:
  schemas: { ... }
  parameters: { ... }
  responses: { ... }
  securitySchemes: { ... }
```

`paths` may be omitted in 3.1 only if `webhooks` or `components` is present.
In practice: always have `paths`.

## Operations

```yaml
paths:
  /v1/orders/{orderId}:
    parameters:              # applies to every method on this path
      - name: orderId
        in: path
        required: true       # in:path is ALWAYS required:true
        schema: { type: string }
    get:
      operationId: getOrder  # unique across the document
      summary: Fetch one order
      tags: [orders]
      responses:
        '200':               # QUOTED — see the pitfalls section
          description: The order.
          content:
            application/json:
              schema: { $ref: '#/components/schemas/Order' }
        '404': { $ref: '#/components/responses/NotFound' }
```

`operationId` is what code generators turn into a method name, so it is a
public identifier: changing it renames the method in every generated SDK.

## Components and `$ref`

Anything reused twice belongs in `components`. A `$ref` is a JSON Pointer:

```yaml
$ref: '#/components/schemas/Order'
$ref: '#/components/responses/NotFound'
$ref: '#/components/parameters/Page'
```

Rules that bite:

- **A `$ref` object's siblings are ignored** in 3.0. In 3.1 you may place
  `description` and `summary` alongside a `$ref`, but nothing else — put
  overrides in the target, not next to the pointer.
- Refs are case-sensitive and must match the component key exactly.
- `~1` escapes `/` and `~0` escapes `~` inside a pointer segment.
- Circular refs are legal (a tree node, a comment with replies). Tools handle
  them; infinite *inline* nesting is what breaks.

## Parameters vs requestBody

| Where the data lives | Use |
| --- | --- |
| In the URL template — `/orders/{orderId}` | `in: path`, `required: true` |
| After the `?` — `?page=2&status=paid` | `in: query` |
| An HTTP header — `X-Request-Id` | `in: header` |
| A cookie | `in: cookie` |
| The message body — JSON, form, upload | `requestBody`, **not** a parameter |

A body is never a parameter in OpenAPI 3.x (that was Swagger 2.0's
`in: body`). Full parameter object:

```yaml
- name: status
  in: query
  required: false            # default is false; path params must be true
  description: Return only orders in this state.
  schema: { $ref: '#/components/schemas/OrderStatus' }
  explode: true              # for arrays/objects: how repeats are serialised
  style: form                # form (query default), simple (path default)
```

Array query parameters need `style`/`explode` to be unambiguous:
`?tag=a&tag=b` is `style: form, explode: true`; `?tag=a,b` is
`style: form, explode: false`.

`requestBody`:

```yaml
requestBody:
  required: true             # default is FALSE — say true or the body is optional
  content:
    application/json:
      schema: { $ref: '#/components/schemas/CreateOrderBody' }
```

## Security schemes

```yaml
components:
  securitySchemes:
    bearerAuth:              # HTTP bearer (JWT and friends)
      type: http
      scheme: bearer
      bearerFormat: JWT
    basicAuth:
      type: http
      scheme: basic
    apiKeyAuth:              # header, query or cookie
      type: apiKey
      in: header
      name: X-API-Key
    oauth2:
      type: oauth2
      flows:
        authorizationCode:
          authorizationUrl: https://auth.example.com/authorize
          tokenUrl: https://auth.example.com/token
          scopes:
            orders:read: Read orders
            orders:write: Create and cancel orders
    oidc:
      type: openIdConnect
      openIdConnectUrl: https://auth.example.com/.well-known/openid-configuration
```

Applying them:

```yaml
security:                    # document default
  - bearerAuth: []
paths:
  /v1/health:
    get:
      security: []           # [] means PUBLIC — overrides the default
  /v1/orders:
    post:
      security:
        - oauth2: [orders:write]     # scopes go in the array, only for oauth2/oidc
```

A list of requirement objects is **OR** (any one suffices); multiple keys
*inside* one object is **AND** (all required). `security: []` on an operation
is the only way to mark it public when a document default exists — omitting the
key inherits the default.

## `example` vs `examples`

```yaml
schema:
  type: string
  example: ord_12345                 # a single inline value

content:
  application/json:
    schema: { $ref: '#/components/schemas/Order' }
    examples:                        # named, each wrapping its value
      paid:
        summary: A paid order
        value: { id: ord_1, status: paid }
      cancelled:
        summary: A cancelled order
        value: { id: ord_2, status: cancelled }
```

`example` (singular) is a bare value. `examples` (plural) is a map of named
Example Objects, each with the payload under `value` — forgetting `value` is
the single most common examples bug, and it renders as an empty sample. Do not
set both on the same node; Swagger UI shows only one.

In 3.1 the JSON Schema keyword `examples` (an *array*) is also valid inside a
schema. Keep them apart: named map at the media-type level, array inside a
schema.

## Nullability in 3.1

`nullable: true` **does not exist in 3.1** — it was a 3.0 extension. Use a type
array:

```yaml
# 3.1 — correct
note:
  type: [string, 'null']

# 3.0 — wrong here; silently ignored by 3.1 tools, so the field looks non-null
note:
  type: string
  nullable: true
```

Quote `'null'` in YAML, or it parses as an actual null and the type array
becomes `[string, None]`.

Optional and nullable are different axes: absent from `required` means the key
may be missing; `'null'` in the type means the key may be present with a null
value. Say which you mean — clients handle them differently.

## Other 3.1 changes worth knowing

- `webhooks` is a new top-level key for outbound callbacks.
- `info.summary` (short) sits alongside `info.description` (Markdown).
- Full JSON Schema 2020-12: `$defs`, `const`, `if`/`then`/`else`,
  `unevaluatedProperties`, `prefixItems` all work.
- `exclusiveMinimum`/`exclusiveMaximum` are **numbers**, not booleans as in 3.0.
- A path item can be `$ref`'d, and `components.pathItems` exists.

## What breaks Swagger UI

| Symptom | Cause |
| --- | --- |
| Endpoint missing from the page | response code written unquoted in YAML — `200:` parses as the integer `200`, and the responses map wants strings |
| "Could not resolve reference" | `$ref` typo, wrong case, or the component was never defined |
| Blank "Example Value" | `examples` entry missing its `value:` wrapper |
| Field shows as required when it is not | `required:` is a **list on the parent object**, not a boolean on the property |
| Body ignored on GET/DELETE | many clients, proxies and caches strip it — move the data to query parameters |
| Everything renders but the "Authorize" button is missing | `securitySchemes` defined but never referenced by a `security` block |
| Duplicate operation warnings in codegen | two operations share an `operationId` |
| A `nullable` field never accepts null | 3.0 `nullable: true` in a 3.1 document |
| Path parameter shown as a text box that does nothing | `{orderId}` in the URL with no matching parameter object, or a name mismatch |

`scripts/validate_openapi.py` checks every row of that table.
