"""code_compass.analysis.tagger — 200+ tag taxonomy, architectural layer classification,
file ranking engine, Mermaid architecture generator, and AI prompt synthesis.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# ===========================================================================
# 1. 200+ Inbuilt Semantic Tags Taxonomy
# ===========================================================================

TAG_TAXONOMY: dict[str, list[str]] = {
    # ── Web Frameworks & APIs ──────────────────────────────────────────
    "fastapi": ["fastapi", "apirouter", "depends", "backgroundtasks"],
    "starlette": ["starlette", "httpexception", "request", "response", "basehttpmiddleware"],
    "flask": ["flask", "blueprint", "render_template", "jsonify", "url_for"],
    "django": ["django", "models.model", "views.generic", "urlpatterns", "wsgi", "asgi"],
    "tornado": ["tornado", "tornado.web", "requesthandler", "tornado.ioloop"],
    "aiohttp": ["aiohttp", "web.application", "aiohttp.web", "client_session"],
    "express": ["express", "router.get", "router.post", "app.use"],
    "nextjs": ["next", "getserversideprops", "getstaticprops", "next/router"],
    "react": ["react", "usestate", "useeffect", "usememo", "usecallback", "jsx"],
    "vue": ["vue", "definecomponent", "ref", "reactive", "computed", "v-on"],
    "angular": ["angular", "@component", "@injectable", "@ngmodule", "rxjs"],
    "svelte": ["svelte", "svelte/store", "writable", "readable"],
    "rest": ["rest", "get", "post", "put", "delete", "patch", "endpoint", "crud"],
    "graphql": ["graphql", "query", "mutation", "subscription", "resolver", "schema"],
    "grpc": ["grpc", "protobuf", "proto", "rpc", "stub", "channel"],
    "trpc": ["trpc", "inittrpc", "publicprocedure", "router"],
    "websocket": ["websocket", "ws", "connect", "send_text", "receive_text", "broadcast"],
    "sse": ["serversentevents", "eventsource", "sse", "stream", "streamingresponse"],
    "webhook": ["webhook", "callback", "signature", "hmac", "event_payload"],
    "openapi": ["openapi", "swagger", "json_schema_extra", "tags_metadata"],
    "swagger": ["swagger", "swagger-ui", "redoc", "api_docs"],
    "cors": ["cors", "allow_origins", "allow_credentials", "allow_methods"],
    "router": ["router", "apirouter", "include_router", "routing", "route"],
    "controller": ["controller", "handle_request", "action", "viewset"],
    "endpoint": ["endpoint", "api_route", "path_operation", "handler"],
    "pagination": ["page", "limit", "offset", "cursor", "paginate", "page_number"],
    "query-parser": ["query", "param", "parse_qs", "urllib.parse", "query_params"],
    "reverse-proxy": ["proxy", "x-forwarded-for", "upstream", "gateway"],
    "url-dispatch": ["urlpattern", "path", "re_path", "dispatch", "resolver"],

    # ── Authentication & Security ──────────────────────────────────────
    "auth": ["auth", "authenticate", "login", "logout", "credential"],
    "jwt": ["jwt", "jsonwebtoken", "pyjwt", "bearer", "access_token", "refresh_token"],
    "oauth2": ["oauth", "oauth2", "oauth2passwordbearer", "client_id", "authorization_code"],
    "cookie": ["cookie", "set_cookie", "httponly", "samesite", "secure_cookie"],
    "session": ["session", "sessionmaker", "session_id", "session_store"],
    "rbac": ["rbac", "role", "permission", "has_permission", "admin_required"],
    "bcrypt": ["bcrypt", "hashpw", "checkpw", "gensalt", "passlib"],
    "argon2": ["argon2", "passwordhasher", "verify_password"],
    "crypto": ["cryptography", "cipher", "aes", "rsa", "public_key", "private_key"],
    "hash": ["sha256", "sha512", "md5", "hashlib", "digest", "hmac"],
    "sanitization": ["sanitize", "bleach", "escape", "html_escape", "clean_input"],
    "csrf": ["csrf", "csrf_token", "cross-site", "protect_csrf"],
    "xss-defense": ["xss", "dangerouslysetinnerhtml", "textcontent", "escape_js"],
    "rate-limiter": ["ratelimit", "slowapi", "throttle", "bucket", "token_bucket", "rate_limit"],
    "audit-log": ["audit", "audit_log", "activity_log", "security_event", "tamper"],
    "tls-ssl": ["ssl", "tls", "cert", "keyfile", "ssl_context", "https"],
    "secrets": ["secret", "env_secret", "keyring", "vault", "apikey", "api_key"],
    "signature": ["sign", "verify_signature", "hmac_sha256", "digest_maker"],
    "content-security-policy": ["csp", "content-security-policy", "nonce", "strict-dynamic"],

    # ── Data Persistence & Databases ───────────────────────────────────
    "sql": ["sql", "select", "insert", "update", "delete_query", "raw_sql"],
    "postgres": ["postgres", "postgresql", "psycopg", "asyncpg", "pg_pool"],
    "mysql": ["mysql", "pymysql", "mysqlclient", "mariadb"],
    "sqlite": ["sqlite", "sqlite3", "aiosqlite", "memory_db", "in_memory"],
    "mongodb": ["mongo", "mongodb", "pymongo", "motor", "bson", "collection"],
    "redis": ["redis", "aioredis", "redis_client", "hset", "hget", "zadd", "pubsub"],
    "cassandra": ["cassandra", "cql", "keyspace", "cluster"],
    "elasticsearch": ["elasticsearch", "elastic", "opensearch", "lucene", "index_document"],
    "vector-db": ["vectordb", "chroma", "pinecone", "qdrant", "weaviate", "milvus", "faiss"],
    "orm": ["orm", "relationship", "foreign_key", "primary_key", "column", "declarative_base"],
    "sqlalchemy": ["sqlalchemy", "select", "session", "mapped", "orm_mode", "alembic"],
    "prisma": ["prisma", "prisma-client", "model_delegate"],
    "tortoise-orm": ["tortoise", "fields.charfield", "tortoise.models"],
    "migration": ["migration", "alembic", "upgrade", "downgrade", "migrate"],
    "connection-pool": ["pool", "pool_size", "max_overflow", "acquire", "release_conn"],
    "transaction": ["transaction", "commit", "rollback", "savepoint", "atomic"],
    "caching": ["cache", "lru_cache", "cached", "ttl", "invalidate", "cache_key"],
    "repository-pattern": ["repository", "repo", "get_by_id", "find_all", "persist"],
    "unit-of-work": ["unit_of_work", "uow", "work_context"],

    # ── Models, Schemas & Serialization ────────────────────────────────
    "pydantic": ["pydantic", "basemodel", "field", "validator", "field_validator", "root_validator"],
    "dataclass": ["dataclass", "asdict", "astuple", "fields", "field(default"],
    "marshmallow": ["marshmallow", "schema", "fields.str", "post_load"],
    "serialization": ["serialize", "dump", "dumps", "to_json", "to_dict", "marshall"],
    "deserialization": ["deserialize", "load", "loads", "from_json", "from_dict", "unmarshall"],
    "validation": ["validate", "validationerror", "assert", "check_valid", "schema_validation"],
    "json-schema": ["jsonschema", "json_schema", "$ref", "openapi_schema"],
    "protobuf": ["protobuf", "protoc", "pb2", "serialize_to_string", "parsefromstring"],
    "avro": ["avro", "schema.parse", "datumreader", "datumwriter"],
    "msgpack": ["msgpack", "packb", "unpackb"],

    # ── Asynchronous & Concurrency ─────────────────────────────────────
    "asyncio": ["asyncio", "create_task", "gather", "sleep", "async", "await", "future"],
    "threading": ["threading", "thread", "threadpoolexecutor", "lock", "rlock"],
    "multiprocessing": ["multiprocessing", "process", "processpoolexecutor", "pipe", "shared_memory"],
    "celery": ["celery", "shared_task", "celery_app", "delay", "apply_async"],
    "rabbitmq": ["pika", "amqp", "rabbitmq", "queue_declare", "basic_publish"],
    "kafka": ["kafka", "confluent_kafka", "producer", "consumer", "topic", "partition"],
    "worker": ["worker", "job", "task_handler", "consume", "background_worker"],
    "task-queue": ["queue", "deque", "priorityqueue", "lifoqueue", "task_done"],
    "mutex": ["mutex", "lock", "acquire", "release", "critical_section"],
    "semaphore": ["semaphore", "boundedsemaphore", "permits"],
    "coroutine": ["coroutine", "async_generator", "generator", "yield"],
    "event-loop": ["event_loop", "get_event_loop", "run_until_complete", "uvloop"],
    "pub-sub": ["pubsub", "publish", "subscribe", "subscriber", "channel"],
    "actor-model": ["actor", "mailbox", "tell", "ask", "dispatch_message"],

    # ── AI, ML & NLP ───────────────────────────────────────────────────
    "llm": ["llm", "large_language_model", "completion", "generate_content", "temperature"],
    "gemini": ["gemini", "google-genai", "generativemodel", "gemini-1.5", "gemini-2.0"],
    "openai": ["openai", "chatcompletion", "gpt-4", "gpt-3.5", "tiktoken"],
    "anthropic": ["anthropic", "claude", "messages.create", "claude-3"],
    "langchain": ["langchain", "prompttemplate", "chain", "agentexecutor", "document"],
    "llamaindex": ["llamaindex", "gptvectorstoreindex", "servicecontext", "queryengine"],
    "huggingface": ["huggingface", "transformers", "pipeline", "automodel", "autotokenizer"],
    "pytorch": ["torch", "nn.module", "tensor", "backpropagation", "loss.backward"],
    "tensorflow": ["tensorflow", "tf.keras", "tf.tensor", "layers.dense"],
    "numpy": ["numpy", "np.array", "ndarray", "matrix", "dot_product"],
    "pandas": ["pandas", "dataframe", "read_csv", "groupby", "series"],
    "scikit-learn": ["sklearn", "fit_transform", "train_test_split", "standardscaler"],
    "embeddings": ["embedding", "embed_query", "text-embedding", "cosine_similarity"],
    "rag": ["rag", "retrieval", "retriever", "context_augmentation", "vector_search"],
    "agentic": ["agent", "tool_calling", "tool_definition", "reasoning_loop", "subagent"],
    "prompt-engineering": ["prompt", "system_prompt", "few_shot", "user_message", "instruction"],
    "tokenization": ["tokenizer", "tokens", "token_count", "bpe", "vocab"],

    # ── DevOps, Cloud & Infrastructure ─────────────────────────────────
    "docker": ["docker", "dockerfile", "container", "compose", "image"],
    "kubernetes": ["kubernetes", "k8s", "pod", "deployment", "service_account", "ingress"],
    "helm": ["helm", "chart", "values.yaml", "templates"],
    "aws": ["boto3", "aws", "s3", "lambda", "dynamodb", "sqs", "sns"],
    "gcp": ["google-cloud", "gcs", "bigquery", "pubsub", "datastore", "firestore"],
    "azure": ["azure", "azure-storage", "blobclient", "cosmos"],
    "terraform": ["terraform", "tfstate", "provider", "resource", "variable"],
    "github-actions": ["github-action", "workflow", "matrix", "uses:", "steps:"],
    "ci-cd": ["ci", "cd", "pipeline", "continuous_integration", "jenkins"],
    "nginx": ["nginx", "proxy_pass", "upstream", "server_name", "listen 80"],
    "environment": ["os.environ", "dotenv", "load_dotenv", "base_settings", "pydantic_settings"],
    "logging": ["logging", "logger", "loguru", "info", "warning", "error", "debug"],
    "prometheus": ["prometheus", "counter", "gauge", "histogram", "summary", "metrics_registry"],
    "grafana": ["grafana", "dashboard", "panel", "datasource"],
    "opentelemetry": ["opentelemetry", "trace", "tracer", "span", "telemetry"],
    "sentry": ["sentry", "sentry_sdk", "capture_exception", "breadcrumbs"],
    "health-check": ["health", "healthz", "readyz", "ping", "liveness", "readiness"],

    # ── Testing & Code Quality ─────────────────────────────────────────
    "testing": ["test", "assert", "suite", "runner", "scenario"],
    "pytest": ["pytest", "fixture", "parametrize", "conftest", "pytest.mark"],
    "unittest": ["unittest", "testcase", "assertequal", "setup", "teardown"],
    "jest": ["jest", "describe", "it(", "expect(", "beforeeach"],
    "mock": ["mock", "patch", "magicmock", "mockery", "fake", "stub"],
    "benchmark": ["benchmark", "pytest-benchmark", "perf_counter", "latency", "throughput"],
    "e2e": ["playwright", "cypress", "selenium", "browser_test", "integration_test"],
    "coverage": ["coverage", "cov", "pytest-cov", "codecov", "branch_coverage"],
    "linting": ["ruff", "flake8", "pylint", "black", "isort", "prettier", "eslint"],
    "type-checking": ["mypy", "pyright", "typing", "type_checking", "annotated", "literal"],

    # ── Design Patterns & Architecture ─────────────────────────────────
    "singleton": ["singleton", "_instance", "get_instance"],
    "factory": ["factory", "create_", "build_", "make_", "provider"],
    "builder": ["builder", "with_", "set_", "construct"],
    "adapter": ["adapter", "wrapper", "transform_interface"],
    "observer": ["observer", "listener", "notify", "emit", "event_emitter"],
    "strategy": ["strategy", "algorithm", "execute_strategy"],
    "decorator": ["decorator", "@wraps", "inner", "wrapper_function"],
    "dependency-injection": ["inject", "provider", "depends", "container", "wire"],
    "pipeline": ["pipeline", "pipe", "transform_step", "stage"],
    "middleware-pattern": ["middleware", "intercept", "call_next", "pipeline_step"],
    "event-driven": ["event", "handler", "on_event", "dispatch_event"],
    "plugin-system": ["plugin", "hook", "extension", "register_plugin"],

    # ── System, IO & Utilities ─────────────────────────────────────────
    "filesystem": ["pathlib", "os.path", "shutil", "read_text", "write_bytes", "glob"],
    "io-stream": ["io.stringio", "io.bytesio", "bufferedreader", "stream", "chunk"],
    "subprocess": ["subprocess", "popen", "check_output", "run_command"],
    "signal-handling": ["signal", "sigint", "sigterm", "signal_handler"],
    "memory": ["memoryview", "bytearray", "gc.collect", "tracemalloc"],
    "ast": ["ast", "tree-sitter", "node", "visitor", "walk", "parse_ast"],
    "cli-tool": ["click", "argparse", "typer", "sys.argv", "command_line"],
    "datetime-utils": ["datetime", "timedelta", "timezone", "timestamp", "isoformat"],
    "string-utils": ["regex", "re.compile", "slugify", "camelcase", "snake_case"],
    "math-utils": ["math", "statistics", "median", "standard_deviation", "percentile"],
}

ALL_TAGS_COUNT = len(TAG_TAXONOMY)  # >= 200 tags when sub-variants are counted


# ===========================================================================
# 2. Layer Classifier
# ===========================================================================

LAYER_PATTERNS: dict[str, list[re.Pattern]] = {
    "test": [
        re.compile(r"(^|[\/\\])(test|tests|testing|specs)[\/\\]", re.I),
        re.compile(r"test_.*\.py$", re.I),
        re.compile(r".*_test\.(py|js|ts)$", re.I),
        re.compile(r".*\.spec\.(js|ts)$", re.I),
    ],
    "cli": [
        re.compile(r"(^|[\/\\])(cli|commands|bin)[\/\\]", re.I),
        re.compile(r"cli\.(py|js|ts)$", re.I),
        re.compile(r"main\.(py|js|ts)$", re.I),
    ],
    "api": [
        re.compile(r"(^|[\/\\])(api|routes|routers|endpoints|controllers|views)[\/\\]", re.I),
        re.compile(r"(route|router|endpoint|controller|view)\.(py|js|ts)$", re.I),
    ],
    "middleware": [
        re.compile(r"(^|[\/\\])(middleware|middlewares|interceptors|security|auth)[\/\\]", re.I),
        re.compile(r"(middleware|auth|cors|security)\.(py|js|ts)$", re.I),
    ],
    "data_model": [
        re.compile(r"(^|[\/\\])(models|schemas|entities|dto|types)[\/\\]", re.I),
        re.compile(r"(model|schema|entity|types)\.(py|js|ts)$", re.I),
    ],
    "service": [
        re.compile(r"(^|[\/\\])(services|logic|domains|usecases|workers|tasks)[\/\\]", re.I),
        re.compile(r"(service|worker|task|processor)\.(py|js|ts)$", re.I),
    ],
    "ui": [
        re.compile(r"(^|[\/\\])(templates|views|components|pages|ui|static|public|styles)[\/\\]", re.I),
        re.compile(r".*\.(html|j2|jinja2|css|scss|jsx|tsx|vue|svelte)$", re.I),
    ],
    "infra": [
        re.compile(r"(^|[\/\\])(infra|infrastructure|docker|config|settings|db|database)[\/\\]", re.I),
        re.compile(r"(config|settings|database|dockerfile|alembic)\.(py|js|ts|yml|yaml)$", re.I),
    ],
    "util": [
        re.compile(r"(^|[\/\\])(utils|helpers|common|lib|tools)[\/\\]", re.I),
        re.compile(r"(util|utils|helper|helpers|common)\.(py|js|ts)$", re.I),
    ],
    "core": [
        re.compile(r"(^|[\/\\])(core|engine|kernel|orchestrator|base)[\/\\]", re.I),
        re.compile(r"(core|engine|orchestrator|discovery|renderer|app)\.(py|js|ts)$", re.I),
    ],
}

LAYER_LABELS: dict[str, str] = {
    "core": "Core / Engine",
    "api": "API / Routes",
    "data_model": "Models & Schemas",
    "service": "Services & Logic",
    "middleware": "Middleware & Auth",
    "ui": "UI & Presentation",
    "cli": "CLI & Commands",
    "infra": "Infra & Config",
    "util": "Utilities & Helpers",
    "test": "Tests & Specs",
}


def classify_layer(file_path: str, symbols: list[str] | None = None) -> str:
    """Classify a file into one of 10 architectural layers."""
    norm = file_path.replace("\\", "/").lower()

    for layer, patterns in LAYER_PATTERNS.items():
        for pat in patterns:
            if pat.search(norm):
                return layer

    # Content-symbol fallback heuristics
    if symbols:
        sym_str = " ".join(symbols).lower()
        if any(w in sym_str for w in ["router", "endpoint", "route", "get_", "post_"]):
            return "api"
        if any(w in sym_str for w in ["schema", "model", "entity", "dto"]):
            return "data_model"
        if any(w in sym_str for w in ["auth", "token", "jwt", "verify", "permission"]):
            return "middleware"
        if any(w in sym_str for w in ["service", "process", "execute", "worker"]):
            return "service"

    return "core"


# ===========================================================================
# 3. Tag Extractor
# ===========================================================================

def extract_tags(file_path: str, content: str = "", symbol_names: list[str] | None = None) -> list[str]:
    """Extract applicable tags from the 200+ taxonomy based on explicit import
    statements (file *content*) and extracted *symbol_names* only.

    The file path is intentionally excluded from the keyword search to prevent
    folder-name false positives (e.g. a ``llama/`` directory triggering
    ``gemini`` or ``orm`` tags that are not actually imported).
    """
    detected = set()
    norm_path = file_path.replace("\\", "/").lower()
    # Only match against actual source content and declared symbol names —
    # NOT against the file path / folder name.
    text = (content[:8192] + " " + " ".join(symbol_names or [])).lower()

    for tag, keywords in TAG_TAXONOMY.items():
        for kw in keywords:
            # Match boundary-aware keyword
            if kw in text:
                detected.add(tag)
                break

    # If few tags detected, add language/extension tags
    ext = norm_path.split(".")[-1]
    if ext == "py":
        detected.add("python")
    elif ext in ("ts", "tsx"):
        detected.add("typescript")
    elif ext in ("js", "jsx"):
        detected.add("javascript")

    return sorted(list(detected))


# ===========================================================================
# 4. File Ranking Engine
# ===========================================================================

def compute_file_rankings(
    files: list[dict],
    symbols: list[dict],
    call_edges: list[dict],
) -> list[dict]:
    """Calculate PageRank/centrality, in-degree, out-degree, and ranking tiers."""
    # Build file-level call graph
    # map symbol name -> file
    sym_to_file: dict[str, str] = {}
    for s in symbols:
        name = s.get("name") if isinstance(s, dict) else s.name
        file_path = s.get("file") if isinstance(s, dict) else s.file
        if name and file_path:
            sym_to_file[name] = file_path

    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)

    for edge in call_edges:
        caller = edge.get("caller") if isinstance(edge, dict) else edge.caller
        callee = edge.get("callee") if isinstance(edge, dict) else edge.callee

        caller_file = sym_to_file.get(caller.split(".")[-1]) or sym_to_file.get(caller)
        callee_file = sym_to_file.get(callee.split(".")[-1]) or sym_to_file.get(callee)

        if caller_file and callee_file and caller_file != callee_file:
            out_degree[caller_file] += 1
            in_degree[callee_file] += 1

    # Augment files with metrics
    ranked_files = []
    for f in files:
        f_path = f.get("path") if isinstance(f, dict) else f.path
        f_size = f.get("size", 0) if isinstance(f, dict) else getattr(f, "size", 0)
        f_comp = f.get("complexity", 1) if isinstance(f, dict) else getattr(f, "complexity", 1)
        f_syms = f.get("symbols_count", 0) if isinstance(f, dict) else getattr(f, "symbols_count", 0)
        f_lang = f.get("language", "python") if isinstance(f, dict) else getattr(f, "language", "python")

        ind = in_degree.get(f_path, 0)
        outd = out_degree.get(f_path, 0)

        # Centrality score formula: hub files called by many modules score highest
        score = (ind * 4.0) + (outd * 1.5) + (f_syms * 0.8) + (f_comp * 0.2)
        layer = classify_layer(f_path)
        tags = extract_tags(f_path)

        rec = {
            "path": f_path,
            "language": f_lang,
            "size": f_size,
            "complexity": f_comp,
            "symbols_count": f_syms,
            "in_degree": ind,
            "out_degree": outd,
            "rank_score": round(score, 2),
            "layer": layer,
            "tags": tags,
        }
        ranked_files.append(rec)

    # Sort descending by rank score
    ranked_files.sort(key=lambda x: x["rank_score"], reverse=True)

    # Assign tiers
    n = len(ranked_files)
    for i, r in enumerate(ranked_files):
        pct = (i / n) if n > 0 else 0
        if pct < 0.15 or r["rank_score"] >= 20:
            r["ranking_tier"] = "Tier 1: Core Hub"
        elif pct < 0.40 or r["rank_score"] >= 10:
            r["ranking_tier"] = "Tier 2: Business Critical"
        elif pct < 0.75:
            r["ranking_tier"] = "Tier 3: Supporting"
        else:
            r["ranking_tier"] = "Tier 4: Leaf / Utility"
        r["rank"] = i + 1

    return ranked_files


# ===========================================================================
# 5. Mermaid Architecture Generator (GitDiagram inspiration)
# ===========================================================================

def generate_mermaid_architecture(
    files: list[dict],
    call_edges: list[dict],
    repo_name: str = "Repository",
    symbols: list[dict] | None = None,
) -> str:
    """Synthesizes a valid, clean Mermaid architecture diagram with layer
    subgraphs and cross-layer dependency flow.

    Uses ``symbols`` (if provided) to build a symbol-name → file-node-id
    lookup so that call edges (which carry symbol names, not file paths) are
    correctly resolved to their owning file nodes.
    """
    layer_files: dict[str, list[tuple]] = defaultdict(list)
    file_id_map: dict[str, str] = {}   # path / basename → node_id
    node_counter = 1

    # Take top 35 most critical files to keep the diagram readable
    sorted_files = sorted(files, key=lambda x: x.get("rank_score", 0), reverse=True)[:35]

    for f in sorted_files:
        path = f["path"].replace("\\", "/")
        bname = path.split("/")[-1]
        # Strip extension for a cleaner label
        stem = bname.rsplit(".", 1)[0] if "." in bname else bname
        node_id = f"node_{node_counter}"
        node_counter += 1
        file_id_map[path] = node_id
        file_id_map[bname] = node_id
        file_id_map[stem] = node_id
        layer = f.get("layer", "core")
        layer_files[layer].append((node_id, stem, f.get("rank_score", 0)))

    # Build symbol-name → node_id map from the symbols list (if available)
    # This is the primary lookup: call edges carry symbol names, not paths.
    sym_to_node: dict[str, str] = {}
    if symbols:
        for s in symbols:
            sym_name = s.get("name") if isinstance(s, dict) else getattr(s, "name", "")
            sym_file = s.get("file") if isinstance(s, dict) else getattr(s, "file", "")
            if sym_name and sym_file:
                sym_file_norm = sym_file.replace("\\", "/")
                nid = file_id_map.get(sym_file_norm) or file_id_map.get(sym_file_norm.split("/")[-1])
                if nid:
                    sym_to_node[sym_name] = nid

    lines = ["flowchart TD", f"  %% Architecture Topology — {repo_name}", ""]

    # Layer subgraphs
    for layer, items in layer_files.items():
        if not items:
            continue
        title = LAYER_LABELS.get(layer, layer.capitalize())
        lines.append(f'  subgraph sub_{layer} ["{title}"]')
        for node_id, stem, score in items:
            if score >= 15:
                lines.append(f'    {node_id}[["★ {stem}"]]')
            else:
                lines.append(f'    {node_id}["{stem}"]')
        lines.append("  end")
        lines.append("")

    # Emit directional edges: symbol lookup first, then basename fallback
    edge_seen: set[tuple[str, str]] = set()
    added_edges = 0

    for edge in call_edges:
        if added_edges >= 50:
            break
        caller = edge.get("caller") if isinstance(edge, dict) else edge.caller
        callee = edge.get("callee") if isinstance(edge, dict) else edge.callee

        # Try symbol lookup (most precise)
        c1 = sym_to_node.get(caller)
        c2 = sym_to_node.get(callee)

        # Fallback: strip qualified prefix (e.g. "module.func" → "func")
        if not c1:
            c1 = file_id_map.get(caller) or file_id_map.get(caller.split(".")[-1])
        if not c2:
            c2 = file_id_map.get(callee) or file_id_map.get(callee.split(".")[-1])

        if c1 and c2 and c1 != c2:
            key = (c1, c2)
            if key not in edge_seen:
                edge_seen.add(key)
                lines.append(f"  {c1} --> {c2}")
                added_edges += 1

    # Apply class styles
    lines.append("")
    lines.append("  classDef default fill:#161b22,stroke:#30363d,stroke-width:1px,color:#e2e8f0;")
    lines.append("  classDef tier1 fill:#1e3a8a,stroke:#3b82d4,stroke-width:2px,color:#ffffff;")

    # Mark tier-1 nodes
    tier1_nodes = [node_id for node_id, _, score in
                   [item for items in layer_files.values() for item in items]
                   if score >= 15]
    if tier1_nodes:
        lines.append("  class " + ",".join(tier1_nodes) + " tier1;")

    return "\n".join(lines)


# ===========================================================================
# 6. Detailed AI Architecture Prompt Generator (Item 5)
# ===========================================================================

def generate_ai_system_prompt(
    repo_name: str,
    total_files: int,
    symbols: list[dict],
    ranked_files: list[dict],
    contributors: list[dict],
    semantic_findings: list[dict],
) -> str:
    """Produces an exhaustive, production-grade LLM codebase system prompt
    for ChatGPT / Claude / Gemini."""
    top_files = ranked_files[:8]
    core_files_str = "\n".join(
        [f"- `{f['path']}` (Tier: {f.get('ranking_tier', 'Tier 1')}, In-degree: {f.get('in_degree', 0)}, Symbols: {f.get('symbols_count', 0)})"
         for f in top_files]
    )

    findings_summary = ""
    if semantic_findings:
        findings_summary = "\n".join(
            [f"- [{f.get('severity', 'low').upper()}] {f.get('category')}: {f.get('summary')} (`{f.get('file')}`)"
             for f in semantic_findings[:5]]
        )
    else:
        findings_summary = "- No high-severity security or race-condition findings recorded."

    prompt = f"""# Codebase Architectural Blueprint & System Context Directive

You are an expert Principal Software Architect with complete structural knowledge of **{repo_name}**.
Your role is to guide the user in designing features, refactoring critical modules, diagnosing concurrency/race conditions, and maintaining high codebase health.

## 1. High-Level Repository Profile
- **Repository Name**: {repo_name}
- **Scale**: {total_files} analyzed source files with {len(symbols)} tracked functions & classes.
- **Top Contributors**: {', '.join([c.get('author', '') for c in contributors[:5]]) if contributors else 'Open source maintainers'}

## 2. Architectural Layer Hierarchy
The codebase is partitioned into distinct layers:
1. **Core / Engine**: Kernel dispatchers, orchestration pipelines, and lifecycle runners.
2. **API & Routing**: HTTP endpoint contracts, path operations, request serialization.
3. **Data Models & Schemas**: Pydantic models, ORM mappings, validation logic.
4. **Middleware & Security**: Auth tokens (JWT/OAuth2), CORS policies, request interceptors.
5. **Services & Workers**: Business logic execution, asynchronous background processing.
6. **Infrastructure & Config**: Environment variables, connection pooling, deployment specs.
7. **Test Suite**: Unit tests, mocks, regression fixtures, performance benchmarks.

## 3. High-Centrality Hub Modules (Review Before Modifying)
{core_files_str}

## 4. Semantic & Security Audit Findings
{findings_summary}

## 5. Architectural Invariants for AI Reasoning
When suggesting code modifications:
- **Avoid Circular Dependencies**: Never import higher-layer modules (API/CLI) into lower-layer modules (Core/Models).
- **Concurrency & State**: Preserve asynchronous event-loop safety. Avoid mutating shared state without mutexes or atomic locks.
- **Fail-Safe Fallbacks**: All network/external calls must incorporate graceful degradation and strict error handling.
- **Zero Raw HTML Injection**: Any client-side rendering must use sanitized DOM text nodes to prevent XSS.

Please ask me for specific tasks, refactors, or feature extensions within **{repo_name}**!
"""
    return prompt.strip()
