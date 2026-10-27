import clsx from "clsx";
import { FileUp } from "lucide-react";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";

import { Spinner } from "@/components/ui";
import { useUpload } from "@/hooks/api";
import { MAX_MB, rejectionMessage } from "@/lib/upload";

export function UploadDropzone() {
  const upload = useUpload();
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { "application/pdf": [".pdf"] },
    maxSize: MAX_MB * 1024 * 1024,
    multiple: true,
    onDropAccepted: (files) => files.forEach((f) => upload.mutate(f)),
    onDropRejected: (rs) => rs.forEach((r) => toast.error(rejectionMessage(r))),
  });
  return (
    <div
      {...getRootProps()}
      className={clsx(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition",
        isDragActive ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-white hover:border-brand-500 hover:bg-slate-50",
      )}
    >
      <input {...getInputProps()} aria-label="Upload SBC PDFs" />
      <FileUp className="h-8 w-8 text-brand-500" aria-hidden />
      <p className="font-medium text-slate-800">{isDragActive ? "Drop the PDFs here" : "Drop SBC PDFs here, or click to choose"}</p>
      <p className="text-sm text-slate-500">
        Summary of Benefits and Coverage documents, up to {MAX_MB} MB each. Text-based PDFs only (no scans).
      </p>
      {upload.isPending && <Spinner label="Uploading…" />}
    </div>
  );
}
