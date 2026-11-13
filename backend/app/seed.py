"""Demo data: the scenario from the project brief (30 apps, 15 APIs, 4 databases, 5 third-party services)
plus caches, a queue and a few workers - with hidden relationships planted on purpose.

    python -m app.seed            # create demo user + project if missing
    login: demo@ghostinfra.dev / demo1234
"""
import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import Base, SessionLocal, engine
from .security import hash_password
from .services.health import reconcile_incidents

DEMO_EMAIL = "demo@ghostinfra.dev"
DEMO_PASSWORD = "demo1234"

# name -> (criticality, owner)
APIS = {
    "auth-api": (5, "identity"), "user-api": (4, "identity"), "catalog-api": (4, "catalog"),
    "search-api": (4, "catalog"), "cart-api": (4, "checkout"), "orders-api": (5, "checkout"),
    "payments-api": (5, "payments"), "inventory-api": (4, "supply"), "shipping-api": (3, "supply"),
    "notifications-api": (3, "platform"), "pricing-api": (4, "catalog"), "recommendations-api": (2, "data"),
    "reviews-api": (2, "community"), "analytics-api": (2, "data"), "loyalty-api": (3, "growth"),
}
APPS = {
    "web-storefront": (5, "web"), "mobile-bff": (5, "mobile"), "checkout-ui": (5, "checkout"),
    "admin-portal": (3, "platform"), "seller-portal": (3, "marketplace"), "warehouse-dashboard": (3, "supply"),
    "support-console": (3, "support"), "marketing-site": (2, "web"), "email-composer": (2, "growth"),
    "report-builder": (2, "data"), "fraud-review-tool": (3, "payments"), "returns-portal": (3, "support"),
    "store-locator": (1, "web"), "gift-card-app": (2, "payments"), "subscription-manager": (3, "growth"),
    "partner-portal": (2, "marketplace"), "b2b-ordering": (3, "marketplace"), "driver-app": (3, "supply"),
    "picking-app": (3, "supply"), "pricing-console": (3, "catalog"), "promo-manager": (2, "growth"),
    "content-cms": (2, "web"), "search-tuner": (1, "catalog"), "bi-dashboard": (2, "data"),
    "finance-recon": (3, "finance"), "hr-portal": (1, "people"), "it-helpdesk": (1, "it"),
    "data-explorer": (1, "data"), "feature-flag-ui": (2, "platform"), "status-page": (2, "platform"),
}
DATABASES = {"pg-core": (5, "platform"), "pg-users": (5, "identity"), "pg-analytics": (3, "data"), "mongo-catalog": (4, "catalog")}
OTHERS = {  # name -> (type, criticality, owner)
    "redis-cache": ("cache", 4, "platform"), "rabbitmq": ("queue", 4, "platform"),
    "stripe-api": ("external", 5, ""), "twilio-sms": ("external", 3, ""), "sendgrid-email": ("external", 3, ""),
    "algolia-search": ("external", 4, ""), "taxjar-tax": ("external", 3, ""),
    "order-sync-worker": ("worker", 4, "checkout"), "email-queue-worker": ("worker", 3, "growth"),
    "inventory-reconciler": ("worker", 3, "supply"), "legacy-report-cron": ("worker", 2, ""),
}

# source -> targets (documented)
DOCUMENTED = {
    "auth-api": ["pg-users", "redis-cache"], "user-api": ["pg-users", "auth-api"],
    "catalog-api": ["mongo-catalog", "redis-cache", "pricing-api"], "search-api": ["algolia-search", "catalog-api"],
    "cart-api": ["redis-cache", "catalog-api", "pricing-api", "auth-api"],
    "orders-api": ["pg-core", "cart-api", "payments-api", "inventory-api", "rabbitmq", "taxjar-tax", "auth-api"],
    "payments-api": ["stripe-api", "pg-core", "auth-api"], "inventory-api": ["pg-core", "redis-cache"],
    "shipping-api": ["orders-api", "twilio-sms"], "notifications-api": ["sendgrid-email", "twilio-sms", "rabbitmq"],
    "pricing-api": ["pg-core", "redis-cache"], "recommendations-api": ["pg-analytics", "catalog-api"],
    "reviews-api": ["mongo-catalog", "user-api"], "analytics-api": ["pg-analytics"],
    "loyalty-api": ["user-api", "pg-users"],
    "order-sync-worker": ["rabbitmq", "orders-api", "pg-core"], "email-queue-worker": ["rabbitmq", "notifications-api"],
    "inventory-reconciler": ["inventory-api", "pg-core"],
    "web-storefront": ["catalog-api", "search-api", "cart-api", "auth-api", "recommendations-api", "reviews-api"],
    "mobile-bff": ["catalog-api", "search-api", "cart-api", "auth-api", "orders-api", "loyalty-api"],
    "checkout-ui": ["cart-api", "orders-api", "payments-api", "shipping-api", "auth-api"],
    "admin-portal": ["user-api", "orders-api", "catalog-api", "auth-api"],
    "seller-portal": ["catalog-api", "inventory-api", "auth-api"], "warehouse-dashboard": ["inventory-api", "orders-api"],
    "support-console": ["user-api", "orders-api", "shipping-api"], "marketing-site": ["catalog-api"],
    "email-composer": ["notifications-api", "user-api"], "report-builder": ["analytics-api"],
    "fraud-review-tool": ["payments-api", "orders-api"], "returns-portal": ["orders-api", "payments-api"],
    "store-locator": ["catalog-api"], "gift-card-app": ["payments-api", "user-api"],
    "subscription-manager": ["payments-api", "user-api", "notifications-api"],
    "partner-portal": ["catalog-api", "auth-api"], "b2b-ordering": ["orders-api", "pricing-api", "auth-api"],
    "driver-app": ["shipping-api", "auth-api"], "picking-app": ["inventory-api", "orders-api"],
    "pricing-console": ["pricing-api"], "promo-manager": ["pricing-api", "loyalty-api"],
    "content-cms": ["catalog-api"], "search-tuner": ["search-api"], "bi-dashboard": ["analytics-api"],
    "finance-recon": ["payments-api", "orders-api"], "hr-portal": ["auth-api"], "it-helpdesk": ["auth-api"],
    "data-explorer": ["pg-analytics"], "feature-flag-ui": ["auth-api", "redis-cache"], "status-page": ["auth-api"],
}
# the ghosts: real runtime dependencies nobody wrote down
GHOSTS = [
    ("reviews-api", "pg-users", "database"),        # reaches around user-api straight into its database
    ("search-api", "pg-core", "database"),          # "temporary" fallback that became permanent
    ("analytics-api", "pg-core", "database"),       # analytics reading the primary instead of the replica
    ("legacy-report-cron", "pg-core", "database"),  # forgotten worker, still hitting production
    ("legacy-report-cron", "pg-analytics", "database"),
    ("loyalty-api", "orders-api", "http"),          # together with the documented edge below -> cycle
    ("orders-api", "loyalty-api", "http"),
    ("shipping-api", "stripe-api", "http"),         # shipping quietly calls Stripe for refunds
    ("web-storefront", "redis-cache", "cache"),
    ("notifications-api", "pg-users", "database"),
]


def seed_demo(db: Session) -> None:
    if db.scalar(select(models.User).where(models.User.email == DEMO_EMAIL)):
        return
    rng = random.Random(42)
    now = models.utcnow()

    user = models.User(email=DEMO_EMAIL, name="Demo Engineer", password_hash=hash_password(DEMO_PASSWORD))
    db.add(user)
    db.flush()
    project = models.Project(
        name="Acme Commerce Platform",
        description="30 applications, 15 APIs, 4 databases and a pile of third-party services. Nobody has the full picture.",
        owner_id=user.id,
    )
    db.add(project)
    db.flush()

    svcs: dict[str, models.Service] = {}

    def add(name, typ, crit, owner):
        s = models.Service(project_id=project.id, name=name, type=typ, criticality=crit, owner=owner, status="healthy",
                           last_checked_at=now, description=f"{typ} · demo")
        db.add(s)
        svcs[name] = s

    for n, (c, o) in APPS.items():
        add(n, "application", c, o)
    for n, (c, o) in APIS.items():
        add(n, "api", c, o)
    for n, (c, o) in DATABASES.items():
        add(n, "database", c, o)
    for n, (t, c, o) in OTHERS.items():
        add(n, t, c, o)
    db.flush()

    kind_for = {"database": "database", "cache": "cache", "queue": "queue", "api": "http", "external": "http", "application": "http"}
    ghost_pairs = {(s, t) for s, t, _ in GHOSTS}
    for src, targets in DOCUMENTED.items():
        for tgt in targets:
            if (src, tgt) in ghost_pairs:
                continue
            db.add(models.Dependency(project_id=project.id, source_id=svcs[src].id, target_id=svcs[tgt].id,
                                     kind=kind_for.get(svcs[tgt].type, "http"), documented=True, discovered_by="manual"))
    for src, tgt, kind in GHOSTS:
        db.add(models.Dependency(project_id=project.id, source_id=svcs[src].id, target_id=svcs[tgt].id, kind=kind,
                                 documented=False, discovered_by="trace", observed_count=rng.randint(40, 4000),
                                 last_seen_at=now - timedelta(minutes=rng.randint(1, 90))))
    # one documented edge that closes the loyalty <-> orders cycle is the undocumented pair above

    # 24h of health history per service (every 30 minutes)
    for name, s in svcs.items():
        base = rng.uniform(15, 80) if s.type != "external" else rng.uniform(80, 220)
        for i in range(48, 0, -1):
            db.add(models.HealthCheck(service_id=s.id, status="healthy", latency_ms=round(base * rng.uniform(0.7, 1.5), 1),
                                      status_code=200, source="seed", checked_at=now - timedelta(minutes=30 * i)))

    # deployments (legacy-report-cron was last touched over a year ago; two have no owner & no deploys)
    for name, s in svcs.items():
        if name == "legacy-report-cron":
            db.add(models.Deployment(project_id=project.id, service_id=s.id, version="v0.9.3", deployed_by="former-employee",
                                     deployed_at=now - timedelta(days=430), notes="Quarterly finance report job"))
            continue
        if s.type == "external":
            continue
        for k in range(rng.randint(1, 3)):
            db.add(models.Deployment(project_id=project.id, service_id=s.id, version=f"v{rng.randint(1, 4)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}",
                                     deployed_by=rng.choice(["ana", "kofi", "li", "sam", "ci-bot"]),
                                     deployed_at=now - timedelta(days=rng.randint(1, 60), hours=rng.randint(0, 23))))
    db.flush()

    # A live incident so the dashboard is interesting on first load: the search provider is down.
    algolia = svcs["algolia-search"]
    algolia.status = "down"
    db.add(models.HealthCheck(service_id=algolia.id, status="down", latency_ms=None, error="ConnectTimeout: upstream timed out",
                              source="seed", checked_at=now - timedelta(minutes=2)))
    db.add(models.Alert(project_id=project.id, service_id=algolia.id, kind="status", level="critical",
                        message="algolia-search is down (ConnectTimeout: upstream timed out)"))
    db.flush()
    reconcile_incidents(db, project.id)
    db.commit()


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_demo(db)
    print(f"Seeded. Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
