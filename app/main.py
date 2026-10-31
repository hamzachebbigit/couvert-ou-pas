"""L'API et la page. Une seule application, un seul processus."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.pipeline.cache import Cache
from app.pipeline.index import Index
from app.pipeline.models import AnalyseResponse, Clause, ContractRow
from app.pipeline.providers import router
from app.pipeline.settings import settings
from app.pipeline.verdict import MAX_QUESTION_CHARS, AnalysisError, analyse
from app.security import access_middleware

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Couvert ou pas", docs_url=None, redoc_url=None, openapi_url=None)
app.middleware("http")(access_middleware)

index = Index().load() if (settings.data_dir / "index.db").exists() else Index()
cache = Cache()


class AnalyseRequest(BaseModel):
    contract_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


def _sources() -> list[dict]:
    return json.loads((settings.data_dir / "sources.json").read_text(encoding="utf-8"))["contracts"]


def _row(contract_id: str) -> ContractRow | None:
    path = settings.data_dir / "parsed" / contract_id / "row.json"
    if not path.exists():
        return None
    return ContractRow(**json.loads(path.read_text(encoding="utf-8")))


def _client_ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "contracts": index.contracts(), "llm": settings.has_llm}


@app.get("/")
def home() -> FileResponse:
    response = FileResponse(STATIC / "index.html")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.get("/api/contracts")
def contracts() -> list[dict]:
    out = []
    for source in _sources():
        contract_id = source["id"]
        if contract_id not in index.units:
            continue
        row = _row(contract_id)
        out.append(
            {
                **source,
                "clauses": len({u.clause_id for u in index.units[contract_id] if u.kind == "clause"}),
                "table_rows": sum(1 for u in index.units[contract_id] if u.kind == "table_row"),
                "row": row.model_dump() if row else None,
            }
        )
    return out


@app.get("/api/examples")
def examples() -> list[dict]:
    path = settings.data_dir / "eval" / "questions.jsonl"
    if not path.exists():
        return []
    seen: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        seen.setdefault(item["question"], {"id": item["id"].split("_")[0], "question": item["question"]})
    return list(seen.values())


@app.post("/api/analyse", response_model=AnalyseResponse)
def analyse_route(payload: AnalyseRequest, request: Request) -> AnalyseResponse:
    try:
        return analyse(
            router,
            index,
            cache,
            payload.contract_id,
            payload.question,
            daily_cap=settings.daily_cap,
            client_ip=_client_ip(request),
            per_ip_cap=settings.per_ip_per_minute,
        )
    except AnalysisError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/clause/{contract_id}/{clause_id}", response_model=Clause)
def clause(contract_id: str, clause_id: str) -> Clause:
    lookup = index.clause_lookup(contract_id) if contract_id in index.units else {}
    if clause_id not in lookup:
        raise HTTPException(status_code=404, detail="Clause inconnue.")
    return lookup[clause_id]


@app.get("/api/eval")
def eval_results() -> JSONResponse:
    path = settings.data_dir / "eval" / "results.json"
    if not path.exists():
        return JSONResponse({"summary": None, "items": []})
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
