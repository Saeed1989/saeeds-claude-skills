# Diagram types and their conventions

Each type has a vocabulary readers already know. Following it means the diagram
explains itself; inventing your own means every reader has to decode it first.

Common to all of them:

- **One idea per page.** If two questions need answering, make two pages.
- **Label every edge that is not obvious.** An unlabelled arrow between two
  services asserts a relationship without saying what it is.
- **Colour carries meaning or nothing.** Pick one axis — ownership, criticality,
  layer, sync/async — and hold it for the whole page. Rainbow diagrams read as
  decoration.
- **State the direction.** An arrow means "calls", "sends to", or "depends on";
  pick one convention per page and say so in a note if it is ambiguous.

---

## Architecture (system / deployment)

**Question it answers:** what runs where, and what talks to what.

| Element | Shape | Colour |
| --- | --- | --- |
| Service we own | `component` or `service` | one colour for all of them |
| Datastore | `database` | a second colour, consistent |
| Queue / topic | `queue` | same as datastore family or its own |
| Third-party system | `external` (dashed) | `yellow` |
| Browser / mobile / CLI client | `actor` | `white` |
| CDN, managed edge | `cloud` | `gray` |
| Deployment boundary (VPC, namespace, cluster) | group | `gray` |

Direction `vertical`: clients on top, edge/gateway, services, then datastores at
the bottom. Edges labelled with the **protocol and the operation** —
`POST /orders`, `gRPC GetUser`, `publish order.created` — not just "uses".
Dashed for anything asynchronous or third-party; say which in a legend note.

Group by deployment boundary (what ships and scales together), never by source
folder. 8–20 nodes; above 25, split by boundary into pages.

**Worked example**

```json
{
  "name": "Order path",
  "direction": "vertical",
  "nodes": [
    {"id": "web",     "label": "Web client",  "shape": "actor",     "color": "white"},
    {"id": "gw",      "label": "API gateway", "shape": "service",   "color": "blue"},
    {"id": "orders",  "label": "orders-svc",  "shape": "component", "color": "green"},
    {"id": "billing", "label": "billing-svc", "shape": "component", "color": "green"},
    {"id": "events",  "label": "order.created\n(Kafka)", "shape": "queue", "color": "orange"},
    {"id": "pg",      "label": "PostgreSQL",  "shape": "database",  "color": "purple"},
    {"id": "stripe",  "label": "Stripe",      "shape": "external",  "color": "yellow"}
  ],
  "edges": [
    {"from": "web", "to": "gw", "label": "HTTPS"},
    {"from": "gw", "to": "orders", "label": "POST /orders"},
    {"from": "orders", "to": "pg", "label": "read/write"},
    {"from": "orders", "to": "events", "label": "publish"},
    {"from": "events", "to": "billing", "label": "consume", "dashed": true},
    {"from": "billing", "to": "stripe", "label": "charge", "dashed": true}
  ],
  "groups": [
    {"id": "cluster", "label": "EKS: prod-1", "members": ["gw", "orders", "billing"]}
  ]
}
```

---

## C4

**Question:** the same system at a chosen zoom level. Do not mix levels on one
page — that is the whole discipline.

- **Context (L1):** your system as one box, plus users and external systems.
  Nothing internal. Usually under 10 nodes.
- **Container (L2):** deployable/runnable units — apps, services, databases,
  queues. This is the level that earns its keep most often.
- **Component (L3):** the parts inside one container. Only for a container that
  is genuinely complex.
- **Code (L4):** skip it; a class diagram generated on demand is better.

Every box gets **name + technology + one-line responsibility** as a multi-line
label (`orders-svc\n[Go]\nOwns order lifecycle`). Every edge gets a description
and a protocol (`Reads from\n[SQL/TCP]`). People are `actor` in `white`; systems
you do not own are `external`. Say the level in the page name: `C4 L2 —
Containers`.

---

## Flowchart

**Question:** what happens, in what order, under which conditions.

| Element | Shape |
| --- | --- |
| Start / end | `start` / `end` (one start, and label the terminal states) |
| Action | `process` |
| Branch | `decision` |
| Input/output or artifact | `document` |
| Sub-process | `package` |

Direction `vertical`. Every edge out of a `decision` **must** be labelled
(`yes`/`no`, or the condition) — an unlabelled branch is the single most common
flowchart defect. Two branches out of a diamond, not five; chain diamonds
instead. Phrase decisions as questions and actions as imperative verbs
(`Charge card`, not `Charging of card`). Loops point back to the step being
retried, and get a label saying what bounds them (`retry ≤ 5x`).

---

## Sequence

**Question:** the order of messages between participants over time.

Lifelines across the top, time strictly downward. Every message's `y` must
exceed the previous one's — the one rule that makes a sequence diagram
readable. Solid line + filled arrow for a call, dashed + open arrow for a
return; only draw returns that carry meaning. Activation bars show who holds
control. Loops/alternatives are labelled frames (a rectangle behind the region,
`fillColor=none`, label in the corner).

3–6 participants; more and the page becomes a wall of crossing lines. Styles
are in `xml-format.md` §10 — this is the one type the builder's layered layout
does **not** fit; place lifelines by pinning `x`/`y`, or write the XML directly
from the template.

---

## ER (entity relationship)

**Question:** what data exists and how records relate.

One box per entity, with attribute rows (UML class-box style, `xml-format.md`
§10) — PK/FK marked. Direction `horizontal`; entities are peers. Edges use
`edgeStyle=entityRelationEdgeStyle` and carry **cardinality at both ends**
(`1`, `0..1`, `1..*`, `*`) — an ER edge without cardinality says almost
nothing. Crow's foot: `endArrow=ERmany;startArrow=ERone;`.

Include the join tables; hiding them hides where the real constraints live.
Above ~15 entities, split by subject area (billing, identity, catalogue) into
pages.

---

## State machine

**Question:** which states a thing can be in and what moves it between them.

Nodes are states (`process`, rounded — noun or adjective: `Pending`,
`Shipped`), plus one `start` (filled dot) and terminal `end` states. Edges are
**events, not actions**: `payment_received`, `timeout after 30m`,
`cancel()`. Add a guard in brackets where it matters:
`submit [cart not empty]`.

Every state needs a way in and, unless it is terminal, a way out — a state with
no exit is either a bug or a missing edge. Self-transitions are legitimate;
draw them as a loop with a clear label. Direction `vertical`.

---

## Network

**Question:** how boxes and segments connect physically or logically.

Zones (DMZ, VPC, subnet, VLAN) are groups; hosts and appliances are nodes;
links are usually **undirected** — set `startArrow=none;endArrow=none;` since a
cable has no direction. Label links with the segment detail that matters:
CIDR, VLAN id, port, bandwidth. Firewalls and load balancers get their own
shapes and sit *on* the boundary between zones. Use the AWS/Azure/GCP stencils
when the audience knows them (`xml-format.md` §9).

---

## Data pipeline

**Question:** where data comes from, what transforms it, where it lands.

Direction `horizontal`: sources → ingest → transform → storage → consumers.
Sources and sinks are `database`/`external`, transforms are `process`, buffers
are `queue`, outputs (reports, extracts) are `document`.

Label edges with **format and volume/cadence** — `Avro, ~2M/day`, `CSV,
hourly`, `CDC stream`. That is what readers of a pipeline diagram actually need
and almost never get. Distinguish batch from streaming: dashed for streaming
(or the reverse — just declare it in a legend note).

---

## Class

**Question:** the types in a module and their relationships.

Class boxes with attribute and method rows (`xml-format.md` §10), visibility
markers (`+ - #`), types after the colon. Relationships: inheritance (hollow
triangle), implementation (hollow triangle, dashed), composition (filled
diamond at the owner), aggregation (hollow diamond), plain association with
multiplicities.

Direction `horizontal`, superclasses above subclasses. Show the members that
matter to the relationships being illustrated, not every getter. Above ~12
classes, split by package.

---

## Org chart

**Question:** who reports to whom.

Direction `vertical`, one `process` box per person or role, `name\ntitle`.
Edges are plain lines, no arrowheads and no labels — hierarchy is carried by
position. Dashed for dotted-line/matrix reporting; that is the one exception
worth annotating. Group by department when the tree gets wide. Vacant roles as
dashed boxes.
