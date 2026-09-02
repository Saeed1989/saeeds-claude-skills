# Deriving architecture from a codebase

The goal is a diagram of the **running system**, not of the source tree. A
directory listing redrawn as boxes is worthless: it tells the reader something
they could get from `ls`, and it hides the only thing they cannot get from
`ls` — what calls what, over which protocol, and what breaks when one part
stops.

Read in this order. Stop when you can answer: *what processes run, what state
do they own, and what crosses the network between them?*

## 1. Deployment descriptors — the highest-signal source

These describe the system as it actually runs, and they name the real boundaries.

| File | What it settles |
| --- | --- |
| `docker-compose.yml` | every service, its image, `depends_on`, exposed ports, shared volumes, env pointing one service at another |
| `k8s/*.yaml`, Helm `templates/`, `values.yaml` | Deployments (processes), Services (network names), Ingress (entry points), StatefulSets (state), namespaces (boundaries), ConfigMap/Secret keys naming downstream hosts |
| `*.tf`, `*.tfvars` | managed infrastructure: RDS, S3, SQS, Lambda, load balancers, VPCs/subnets, IAM edges |
| `serverless.yml`, `template.yaml` (SAM) | functions and their event sources — the triggers *are* the edges |
| `Procfile`, `fly.toml`, `app.yaml`, `render.yaml` | process types: web vs worker vs scheduler |
| `.github/workflows/*`, `.gitlab-ci.yml` | what gets built and deployed where; distinguishes real deployables from libraries |
| `nginx.conf`, `Caddyfile`, gateway/route configs | the true front door and its upstreams |

A `depends_on`, an Ingress rule, or an SQS trigger is **evidence of an edge**.
This is where most of the diagram comes from.

## 2. Entrypoints

Find where processes start and where requests enter:

- `main.go`, `cmd/*/main.go`, `if __name__ == "__main__"`, `app.py`,
  `src/index.ts`, `Program.cs`, `Application.java`
- `package.json` `scripts.start`, `Dockerfile` `CMD`/`ENTRYPOINT`
- Route registration: `app.get(...)`, `@RestController`, `urls.py`,
  `router.HandleFunc`, OpenAPI/`*.proto` files
- Background work: queue consumers, cron/schedule registrations, event handlers

Each distinct entrypoint is usually a distinct box. Two entrypoints in one repo
(an API and a worker) are two nodes, not one — a monorepo is not a monolith,
and a "microservices" repo with one entrypoint is not microservices.

## 3. Outbound calls and state

Grep for what leaves the process:

- HTTP clients, gRPC stubs, SDK clients (`boto3`, `@aws-sdk`, `stripe`)
- Database connections, ORM configs, migration directories (`migrations/`,
  `alembic/`, `prisma/schema.prisma`) — migrations name the datastore *and*
  reveal the entities for an ER diagram
- Queue/topic producers and consumers, cache clients
- Base URLs and hostnames in env config: `.env.example`, `config/*.yaml`,
  Helm values. Env var names like `BILLING_SERVICE_URL` are direct edge evidence.

## 4. Only then, folder structure

Useful for *naming* things and for finding module boundaries in a monolith —
never as the diagram's skeleton. In a monolith with one deployable, internal
modules can be worth drawing as a component diagram, but say so on the page and
draw the edges from imports, not from adjacency in the tree.

## Mapping table: finding → diagram element

| Finding in the repo | Diagram element |
| --- | --- |
| compose service / k8s Deployment | `component` node, one per service |
| k8s namespace, VPC, compose project, cluster | group (swimlane) |
| Ingress, gateway route, load balancer | `service` node at the top of the page |
| RDS/Postgres/Mongo config, migrations dir | `database` node |
| SQS/Kafka/RabbitMQ/Pub-Sub topic | `queue` node |
| Redis / Memcached | `database` node, labelled as cache |
| S3 bucket, blob container | `database` node (or `document` for reports) |
| Lambda / Cloud Function | `service` node; its trigger is an inbound edge |
| Cron job, scheduler entry | `process` node, edge labelled with the schedule |
| Third-party SDK (Stripe, Twilio, Auth0) | `external` node, dashed edge |
| CDN / edge config | `cloud` node |
| Browser or mobile app in the repo | `actor` node |
| `depends_on`, service URL env var | edge, labelled with the protocol |
| Queue producer → consumer pair | edge through the queue node, dashed |
| REST route consumed by another service | edge labelled `METHOD /path` |
| DB migration table definitions | ER diagram entities |
| Repository/DAO class | edge from its service to the datastore |

## Rules about edges

Edges are the claims a diagram makes; wrong ones are worse than missing ones
because readers act on them.

1. **Draw an edge only with evidence in the repo.** A config value, an import
   of a client, a `depends_on`, a route registration, a trigger. "These two
   services probably talk" is not evidence.
2. **Direction is who initiates.** `orders → pg`, not `pg → orders`. For a
   queue, producer → queue → consumer, so the arrow follows the data even
   though the consumer initiated the connection.
3. **A shared library is not an edge.** Both services importing `common/` means
   they share code, not that they call each other. Draw it only if the diagram
   is about build/dependency structure, and say so.
4. **A database used by two services is two edges to one node** — never a
   service-to-service edge. That shared datastore is usually the most important
   coupling on the page.
5. **Do not invent a message bus** because the code has an `EventEmitter`.
   In-process events are not network edges.
6. **Say when you are unsure.** If a connection is inferred rather than found,
   either leave it out or mark it dashed and add a `note` naming the
   assumption. Then tell the user which edges are inferred so they can confirm.
7. **Dead code and legacy paths.** If a service exists in the tree but nothing
   deploys it, either omit it or draw it `gray` and label it clearly. Check the
   deploy config before believing a directory.

## Suggested pass

```bash
# 1. deployment truth
ls docker-compose*.y*ml k8s/ helm/ terraform/ infra/ 2>/dev/null
cat docker-compose.yml 2>/dev/null

# 2. deployables and entrypoints
find . -name "main.go" -o -name "Dockerfile" -o -name "Procfile" \
       -o -name "serverless.yml" | grep -v node_modules

# 3. edges
grep -rn --include="*.env*" --include="*.yaml" --include="*.yml" -iE \
     "_URL|_HOST|_ENDPOINT|_DSN|DATABASE_URL|BROKER|QUEUE" . | grep -v node_modules

# 4. state
ls migrations/ alembic/ prisma/ db/migrate/ 2>/dev/null
```

Then confirm the node list with the user before generating: naming a system's
parts wrongly is the failure they will notice first, and it is cheap to fix
before the layout exists.
