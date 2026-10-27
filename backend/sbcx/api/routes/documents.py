import re

from fastapi import APIRouter, BackgroundTasks, File, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from sbcx.api.schemas import DocumentDetail, DocumentList, DocumentSummary, Provenance
from sbcx.config import get_settings
from sbcx.domain.benefits import BenefitsDocument
from sbcx.errors import AppError, not_found
from sbcx.infra.storage import pdf_path
from sbcx.services import documents as svc

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentSummary,
    status_code=status.HTTP_202_ACCEPTED,
    responses={200: {"model": DocumentSummary}, 413: {}, 422: {}},
    summary="Upload an SBC PDF",
)
async def upload_document(background: BackgroundTasks, response: Response, file: UploadFile = File(...)):
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError("E_TOO_LARGE", f"The file is larger than {get_settings().max_upload_mb} MB.", 413)
    row, needs_extraction = await run_in_threadpool(svc.upload, file.filename or "plan.pdf", data)
    if needs_extraction:
        background.add_task(svc.extract_document, row.id)
    else:
        response.status_code = status.HTTP_200_OK
    return svc.to_summary(svc.get(row.id))


@router.get("", response_model=DocumentList, summary="List uploaded plans")
def list_documents():
    return DocumentList(items=svc.list_uploads())


@router.get("/{doc_id}", response_model=DocumentDetail, summary="Get a plan with its extracted benefits")
def get_document(doc_id: str):
    return svc.to_detail(svc.get(doc_id))


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an uploaded plan")
def delete_document(doc_id: str):
    svc.delete(doc_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{doc_id}/reprocess", response_model=DocumentSummary, status_code=202, summary="Re-run extraction"
)
def reprocess_document(doc_id: str, background: BackgroundTasks):
    row = svc.get(doc_id)
    svc._set(row.id, status="queued", error_code=None, error_message=None)
    background.add_task(svc.extract_document, row.id)
    return svc.to_summary(svc.get(doc_id))


@router.post(
    "/{doc_id}/summaries",
    response_model=DocumentSummary,
    status_code=202,
    summary="Generate (or regenerate) the section summaries",
)
def generate_summaries(doc_id: str, background: BackgroundTasks):
    from sbcx.services.summaries import generate_summaries as run

    row = svc.get(doc_id)
    if row.status != "ready":
        raise AppError("E_NOT_READY", "The plan hasn't finished processing yet.", 409)
    if row.summaries_status != "running":
        svc._set(row.id, summaries_status="running")
        background.add_task(run, row.id)
    return svc.to_summary(svc.get(doc_id))


@router.get("/{doc_id}/provenance", response_model=Provenance, summary="Where a value came from")
def get_provenance(
    doc_id: str, path: str = Query(..., examples=["services.specialist_visit.in_network.copay"])
):
    row = svc.get(doc_id)
    if not row.benefits:
        raise AppError("E_NOT_READY", "The plan hasn't finished processing yet.", 409)
    doc = BenefitsDocument.model_validate(row.benefits)
    value: object = doc.benefits.model_dump(mode="json")
    for part in re.findall(r"[^.\[\]]+", path):
        if isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise not_found("Field", path)
    return Provenance(path=path, value=value, meta=doc.provenance.get(path))


@router.get("/{doc_id}/pdf", response_class=FileResponse, summary="Download the original PDF")
def get_pdf(doc_id: str):
    row = svc.get(doc_id)
    p = pdf_path(row.sha256)
    if not p.exists():
        raise not_found("PDF", doc_id)
    return FileResponse(p, media_type="application/pdf", filename=row.filename)
