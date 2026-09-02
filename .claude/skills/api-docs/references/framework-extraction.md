# Finding routes, types, and auth per framework

**Read the router registration, not the filenames.** A file at
`src/routes/orders.ts` may register nothing; a route may be registered in a
loop, from a config array, or by a decorator three directories away. The full
URL is almost never visible in the handler file — it is assembled at the mount
point. Every framework below has the same three questions:

1. **Where are routes registered, and what prefix are they mounted under?**
2. **Where do the request and response shapes come from?**
3. **How is auth applied, and to which routes?**

## Prefixes: the mistake that ruins a whole spec

Handlers declare `/orders`; the app mounts the router at `/v1`; the real path is
`/v1/orders`. Miss it and every path in the spec is wrong. Trace it in the
composition root — `app.ts`, `main.py`, `urls.py`, `routes.rb`, `main.go` — and
watch for nesting more than one level deep, plus a reverse proxy or API gateway
that adds another prefix outside the codebase entirely.

---

## Express (Node/TypeScript)

**Routes.** `app.get/post/put/patch/delete(path, ...handlers)` and
`router.<method>(...)`. Mounting: `app.use('/v1', ordersRouter)`. Follow every
`app.use` and `router.use` with a path argument — they nest.

```ts
app.use('/v1', ordersRouter);                 // prefix
ordersRouter.get('/orders/:orderId', handler) // -> GET /v1/orders/{orderId}
```

Path params are `:name`; optional `:name?`; wildcards `*`. Convert `:name` to
`{name}` for OpenAPI.

**Shapes.** TypeScript interfaces are the best available source: the body type
in `req.body as CreateOrderBody`, the generic in
`Request<Params, ResBody, ReqBody, Query>`, and the type of whatever reaches
`res.json(...)`. If validation middleware is present (zod, joi, yup,
class-validator, express-validator), **that schema is the truth** — it is what
actually rejects requests, and it carries the required/optional split that TS
optionality only hints at. Query params always arrive as strings; note the
coercion (`Number(req.query.page)`) rather than documenting them as integers
without saying so.

**Auth.** Middleware, applied at three levels: globally (`app.use(auth)`), per
router (`router.use(requireBearer)` — covers every route registered *after* it
in that file), or per route (`router.get('/x', requireBearer, handler)`). Read
the middleware to learn the scheme: `Authorization: Bearer` → `http/bearer`,
`req.header('x-api-key')` → `apiKey`. Routes registered *before* a
`router.use(auth)` line are not protected by it — order matters.

## NestJS

**Routes.** Decorators: `@Controller('orders')` sets the prefix,
`@Get(':orderId')` the rest. Also check `setGlobalPrefix('v1')` in `main.ts`
and any `RouterModule.register` — both add segments invisible from the
controller.

**Shapes.** DTO classes with `class-validator` decorators (`@IsString()`,
`@IsOptional()`, `@Min()`) — these map almost one-to-one onto JSON Schema.
Return types come from the method signature.

**Auth.** `@UseGuards(JwtAuthGuard)` on a controller or method; `APP_GUARD` in
a module makes it global; `@Public()` (a custom decorator paired with a
reflector check) is the usual opt-out. If `@nestjs/swagger` decorators
(`@ApiProperty`, `@ApiResponse`) are present, prefer them — they are the
authors' own documentation intent.

## FastAPI (Python)

The highest-fidelity source of all: FastAPI *generates* OpenAPI itself.

**Routes.** `@app.get("/orders")`, `@router.post("/orders")`, mounted with
`app.include_router(router, prefix="/v1", tags=["orders"])`. Path params are
`{name}` already, and the function signature types them.

**Shapes.** Pydantic models. The request model is the body parameter's
annotation; the response is `response_model=OrderOut` (which wins over the
return annotation) or the return type. Optionality is real: `field: str` is
required, `field: str | None = None` is optional and nullable, `Field(...)`
carries constraints and descriptions. Query params are non-Pydantic scalar
arguments with defaults; `Query(...)` adds validation.

**Auth.** `Depends(get_current_user)`, or `dependencies=[Depends(auth)]` on
the router/app. The scheme object itself (`OAuth2PasswordBearer`,
`HTTPBearer`, `APIKeyHeader`) names the OpenAPI scheme directly.

**Shortcut:** if the app runs, `GET /openapi.json` returns the framework's own
generated spec. Use it as the baseline, then add the prose it cannot know.
Verify it against the code rather than trusting it blindly — `response_model`
is often missing, and then FastAPI documents an empty response.

## Flask

**Routes.** `@app.route("/orders", methods=["GET", "POST"])` — one decorator
often covers several methods, so split them into separate operations.
Blueprints carry the prefix:
`app.register_blueprint(orders_bp, url_prefix="/v1")`. Also
`add_url_rule(...)` for programmatic registration.

Converters are `<int:order_id>`, `<uuid:id>`, `<path:subpath>` — the converter
gives you the type: `int` → `integer`, `uuid` → `string/format: uuid`.

**Shapes.** Plain Flask has no types. Look for marshmallow schemas,
`flask-pydantic`, or `@validate` decorators; failing that, read `request.json`
key access and `jsonify(...)` construction in the handler body and mark the
result as inferred. Flask-RESTX/`apispec` projects have decorators that
already document the shape.

**Auth.** `@login_required`, `@jwt_required()`, a custom `@requires_auth`
decorator, or a `@app.before_request` hook that checks a header. A
`before_request` guard applies to everything in that blueprint — easy to miss.

## Django REST Framework

**Routes.** `urls.py` is authoritative: `path()`/`re_path()` entries plus
`include()` for nesting (the prefix lives in the parent `urls.py`). Routers
(`DefaultRouter().register(r'orders', OrderViewSet)`) generate a **set** of
routes from one line: list `GET /orders/`, create `POST /orders/`, retrieve
`GET /orders/{pk}/`, update `PUT/PATCH /orders/{pk}/`, destroy
`DELETE /orders/{pk}/`, plus any `@action(detail=True)` methods. Enumerate them
explicitly. Note DRF's **trailing slashes**.

**Shapes.** Serializers. Field classes give types and constraints;
`required=False`, `allow_null=True`, `read_only=True` (response-only) and
`write_only=True` (request-only) are exactly the distinctions a spec needs.
`ModelSerializer` with `fields = '__all__'` means reading the model.

**Auth.** `permission_classes` and `authentication_classes` on the view, and
the `DEFAULT_PERMISSION_CLASSES` / `DEFAULT_AUTHENTICATION_CLASSES` defaults in
`settings.py` — a view with no explicit classes inherits those.
`AllowAny` marks a public endpoint.

## Spring Boot (Java/Kotlin)

**Routes.** `@RestController` plus `@RequestMapping("/v1/orders")` at class
level, and `@GetMapping("/{orderId}")` at method level — the full path is the
concatenation. Watch `server.servlet.context-path` in
`application.properties`/`.yml`, which prefixes everything.

**Shapes.** DTO records/classes. `@RequestBody` marks the body,
`@PathVariable`, `@RequestParam` (with `required` and `defaultValue`) the
parameters. `ResponseEntity<OrderDto>` gives the response type; the status
comes from `@ResponseStatus` or from `ResponseEntity.status(...)` in the body.
Bean Validation annotations (`@NotNull`, `@Size`, `@Pattern`) map to schema
constraints. Jackson annotations (`@JsonProperty`, `@JsonIgnore`,
`@JsonInclude`) change the wire names — document the wire name, not the field
name.

**Auth.** A `SecurityFilterChain` bean (or older `WebSecurityConfigurerAdapter`)
holds the URL-pattern rules — `requestMatchers("/v1/public/**").permitAll()`,
`.anyRequest().authenticated()`. Method-level `@PreAuthorize("hasScope('...')")`
gives per-endpoint scopes. If springdoc/swagger annotations exist, prefer them.

## Go — chi, gin, echo

**Routes.** All three build the path from nested groups; the handler file never
shows the full URL.

```go
// chi
r.Route("/v1", func(r chi.Router) {
    r.Route("/orders", func(r chi.Router) {
        r.Get("/{orderID}", getOrder)          // GET /v1/orders/{orderID}
    })
})
// gin:  v1 := r.Group("/v1"); v1.GET("/orders/:id", h)   -> :id
// echo: g := e.Group("/v1");  g.GET("/orders/:id", h)    -> :id
```

chi uses `{name}` (already OpenAPI style); gin and echo use `:name` and `*name`.

**Shapes.** Structs with JSON tags — **the tag is the wire name**:
`json:"amount_cents"` documents as `amount_cents`, and `json:"-"` means the
field never appears. `omitempty` signals optional in responses. Find the struct
passed to `json.NewDecoder(r.Body).Decode(&req)` for the request, and the one
handed to `json.NewEncoder(w).Encode(resp)` / `c.JSON(200, resp)` for the
response. Validation tags (`validate:"required,min=1"`) give the required list.

**Auth.** Middleware: `r.Use(AuthMiddleware)` inside a group applies to that
group only; `chi`'s `r.Group(func(r chi.Router){ r.Use(auth); ... })` scopes it
to a subtree. Read the middleware for the header it inspects.

## Rails

**Routes.** `config/routes.rb` is the whole truth, and `rails routes` prints
the resolved table (method, path, controller#action) — the fastest accurate
inventory available in any framework here. `resources :orders` expands to seven
routes; `namespace :v1` and `scope` add prefixes; `only:`/`except:` trim the
set. Params are `:id`; the default format suffix `(.:format)` can be ignored.

**Shapes.** Usually no static types. Sources, in order: jbuilder/`.json.jbuilder`
views, ActiveModel serializers, `render json:` calls in the controller, and
strong parameters (`params.require(:order).permit(:customer_id, :amount_cents)`)
— **the permit list is the authoritative request field list**. Mark anything
beyond that as inferred.

**Auth.** `before_action :authenticate_user!` in a controller or
`ApplicationController` (inherited by everything), with
`skip_before_action :authenticate_user!, only: [:index]` marking the public
holes.

## Laravel

**Routes.** `routes/api.php` (already prefixed `/api` by
`RouteServiceProvider`, and often versioned on top).
`Route::get('/orders/{order}', [OrderController::class, 'show'])`;
`Route::prefix('v1')->group(...)`; `Route::apiResource('orders', ...)` expands
to five routes. Params are `{name}` and `{name?}` for optional.
`php artisan route:list` prints the resolved table.

**Shapes.** FormRequest classes (`rules()` returns the validation array —
`'currency' => 'required|string|size:3'` maps straight to a schema) for
requests; API Resources (`OrderResource::toArray()`) for responses. Both are
authoritative when present.

**Auth.** Middleware in the route group — `->middleware('auth:sanctum')`,
`'auth:api'`, `'abilities:orders-write'` — or in the controller constructor.
`routes/api.php` groups often wrap everything in one middleware call, so check
the group, not just the line.

---

## Recording what you find

Write `routes.json` as you go — one entry per route, before writing any spec:

```json
[{"method": "POST", "path": "/v1/orders",
  "handler": "src/routes/orders.ts:createOrder", "auth": "bearer"}]
```

`path` is the **full** path including every prefix. Use the framework's own
param syntax if you like; `check_coverage.py` normalises `:id`, `{id}`,
`<int:id>` and `$id` before matching. Then let that script prove nothing was
dropped between reading the code and writing the spec.
