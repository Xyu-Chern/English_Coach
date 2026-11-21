// Packaged with a generated ASSETS map by build_site.py.
const BOX = "coach/current",
  PULSE = "coach/online";
const pendingAge = 90_000,
  runningAge = 30 * 60_000,
  resultAge = 3 * 60_000;
function json(body, status = 200) {
  return Response.json(body, {
    status,
    headers: { "cache-control": "no-store" },
  });
}
function error(detail, status) {
  return json({ detail }, status);
}
async function read(bucket, key) {
  const object = await bucket.get(key);
  return object
    ? { value: await object.json(), etag: object.etag }
    : { value: { state: "idle" }, etag: null };
}
function swap(bucket, key, before, value) {
  return bucket.put(key, JSON.stringify(value), {
    onlyIf: before.etag
      ? { etagMatches: before.etag }
      : { etagDoesNotMatch: "*" },
  });
}
function expires(job) {
  const age =
    { queued: pendingAge, running: runningAge, done: resultAge }[job.state] ||
    0;
  return Date.now() - (job.time || 0) > age;
}
async function equalSecret(a, b) {
  if (!a || !b) return false;
  const hash = (s) =>
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  const [x, y] = await Promise.all([hash(a), hash(b)]);
  let diff = 0;
  const X = new Uint8Array(x),
    Y = new Uint8Array(y);
  for (let i = 0; i < X.length; i++) diff |= X[i] ^ Y[i];
  return diff === 0;
}
async function api(req, env, path) {
  const bucket = env.BUCKET;
  if (!bucket) return error("relay_storage_unavailable", 503);
  const service = await equalSecret(
    req.headers.get("x-coach-relay"),
    env.COACH_RELAY_SECRET,
  );
  const owner =
    req.headers.get("oai-authenticated-user-id") ||
    (service ? "relay-test" : null);
  if (!owner) return error("sign_in_required", 401);
  const origin = req.headers.get("Origin");
  if (origin && origin !== new URL(req.url).origin)
    return error("origin_denied", 403);
  const current = await read(bucket, BOX),
    job = current.value;
  if (path.startsWith("/api/relay/")) {
    if (!service || req.method !== "POST") return error("forbidden", 403);
    if (path.endsWith("/claim")) {
      const pulse = await bucket.head(PULSE);
      if (!pulse || Date.now() - pulse.uploaded.getTime() > 25_000)
        await bucket.put(PULSE, "1");
      if (job.state !== "idle" && expires(job))
        await swap(bucket, BOX, current, { state: "idle" });
      else if (job.state === "queued") {
        const next = {
          ...job,
          state: "running",
          time: Date.now(),
          lease: crypto.randomUUID(),
        };
        if (await swap(bucket, BOX, current, next))
          return json({
            id: job.id,
            lease: next.lease,
            question: job.question,
            context: job.context,
          });
      }
      return json({});
    }
    if (path.endsWith("/finish")) {
      const body = await req.json();
      if (
        job.state === "done" &&
        body.id === job.id &&
        body.lease === job.lease
      )
        return json({ ok: true });
      if (
        job.state !== "running" ||
        body.id !== job.id ||
        body.lease !== job.lease
      )
        return error("stale", 409);
      const completed = {
        owner: job.owner,
        id: job.id,
        lease: job.lease,
        state: "done",
        time: Date.now(),
        result: body.result,
        status: body.status,
      };
      return (await swap(bucket, BOX, current, completed))
        ? json({ ok: true })
        : error("stale", 409);
    }
    return error("not_found", 404);
  }
  if (path === "/api/search" && req.method === "POST") {
    const body = await req.json(),
      q = body.question,
      c = body.context || "";
    if (
      typeof q !== "string" ||
      !q.trim() ||
      q.length > 1800 ||
      typeof c !== "string" ||
      c.length > 600
    )
      return error("invalid_input", 422);
    if (job.state !== "idle" && !expires(job)) return error("coach_busy", 429);
    const pulse = await bucket.head(PULSE);
    if (!pulse || Date.now() - pulse.uploaded.getTime() > 90_000)
      return error("coach_offline", 503);
    const next = {
      id: crypto.randomUUID(),
      owner,
      question: q.trim(),
      context: c,
      state: "queued",
      time: Date.now(),
    };
    return (await swap(bucket, BOX, current, next))
      ? json({ id: next.id }, 202)
      : error("coach_busy", 429);
  }
  if (
    req.method === "GET" &&
    path === "/api/search/" + job.id &&
    job.owner === owner &&
    !expires(job)
  ) {
    if (job.state === "done") return json(job.result, job.status);
    return json({ state: job.state }, 202);
  }
  if (
    req.method === "DELETE" &&
    path === "/api/search/" + job.id &&
    job.owner === owner &&
    job.state === "done"
  ) {
    await swap(bucket, BOX, current, { state: "idle" });
    return json({ ok: true });
  }
  return error("not_found", 404);
}
export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path.startsWith("/api/")) {
      try {
        return await api(request, env, path);
      } catch {
        return error("relay_unavailable", 503);
      }
    }
    const asset = ASSETS[path === "/" ? "/index.html" : path];
    if (!asset || !["GET", "HEAD"].includes(request.method))
      return new Response("Not found", { status: 404 });
    const bytes = Uint8Array.from(atob(asset[1]), (c) => c.charCodeAt(0));
    return new Response(request.method === "HEAD" ? null : bytes, {
      headers: { "content-type": asset[0], "cache-control": "no-cache" },
    });
  },
};
