from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.api.routes import router
from app.api.v5_routes import router as v5_router
from app.core.config import get_settings
from app.core.observability import install_observability
from app.core.rate_limit import RateLimitMiddleware

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.2.0")
install_observability(app)
app.add_middleware(RateLimitMiddleware)
app.include_router(router)
app.include_router(v5_router)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def index():
    # Never cache the HTML entry point so versioned asset links (?v=N) are
    # always seen; the assets themselves cache normally under their version.
    return FileResponse(
        static_dir / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )
