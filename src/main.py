import argparse
import os
import sys
import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from src.api.routes import index as controller
from src.api.schemas import StandardResponse
from src.config import is_development
from src.services.daily_data_write_service import daily_data_write_service

port = int(os.environ.get("PORT", 8080))

# Create the FastAPI app
app = FastAPI(
    title="Stock Analysis API",
    description="An API to perform technical analysis on stock symbols.",
    version="1.0.0",
)

origins = [
    "http://localhost:3000",
    "https://ryanpromax.github.io",
    "https://ryanai.dev",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # 允许的域名列表
    allow_credentials=True,  # 是否允许携带 Cookie 等凭证
    allow_methods=["*"],  # 允许的方法 (GET, POST, OPTIONS 等)
    allow_headers=["*"],  # 允许的 Header (Content-Type, Authorization 等)
)


# Validation error handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=StandardResponse(
            status_code=400,
            data=None,
            err_msg=f"请求参数验证失败: {str(exc)}",
        ).model_dump(),
    )


# General error handler
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=StandardResponse(
            status_code=500,
            data=None,
            err_msg=f"服务器内部错误: {str(exc)}",
        ).model_dump(),
    )


# Routers
app.include_router(controller.router)


@app.get("/", tags=["Root"])
def read_root():
    return StandardResponse(
        status_code=200,
        data={"message": "Welcome to the Stock Analysis API. Go to /docs for API documentation."},
        err_msg=None,
    )


@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint to verify server availability."""
    return _health_payload()


def _health_payload() -> StandardResponse:
    return StandardResponse(
        status_code=200,
        data={"message": "ok", "status": "healthy"},
        err_msg=None,
    )


def start():
    uvicorn.run("src.main:app", host="0.0.0.0", port=port, reload=is_development())


def sync_market_data():
    def _print_progress(update: dict) -> None:
        processed = update["processed_count"]
        total = update["total_symbols"]
        skipped = update.get("skipped_count", 0)
        success = update["success_count"]
        failure = update["failure_count"]
        rows_written = update.get("rows_written", 0)
        symbol = update["symbol"]
        item_status = update["item_status"]
        source = update.get("source")
        source_suffix = f" source={source}" if source else ""
        print(
            f"[{processed}/{total}] skipped={skipped} success={success} failure={failure} rows={rows_written} symbol={symbol} status={item_status}{source_suffix}",
            flush=True,
        )

    parser = argparse.ArgumentParser(description="Sync market data into the local SQLite warehouse.")
    parser.add_argument("--market", choices=["cn", "us"], required=True)
    parser.add_argument("--scope", choices=["all", "symbol"], default="all")
    parser.add_argument("--symbol")
    parser.add_argument("--days", type=int)
    parser.add_argument("--years", type=int)
    parser.add_argument("--start-date")
    args = parser.parse_args(sys.argv[1:])

    if sum(value is not None for value in (args.days, args.years, args.start_date)) > 1:
        raise SystemExit("`--days`、`--years` 和 `--start-date` 只能三选一")
    if args.scope == "symbol" and not args.symbol:
        raise SystemExit("`scope=symbol` 时必须提供 `--symbol`")

    summary = daily_data_write_service.sync_market_data(
        market=args.market,
        scope=args.scope,
        symbol=args.symbol,
        days=args.days or (None if args.years or args.start_date else 30),
        years=args.years,
        start_date=args.start_date,
        progress_callback=_print_progress,
    )
    print(summary)


def main():
    start()


if __name__ == "__main__":
    start()
