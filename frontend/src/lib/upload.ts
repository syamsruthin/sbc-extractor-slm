import type { FileRejection } from "react-dropzone";

export const MAX_MB = 10;

export function rejectionMessage(r: FileRejection): string {
  const code = r.errors[0]?.code;
  if (code === "file-too-large") return `${r.file.name} is larger than ${MAX_MB} MB.`;
  if (code === "file-invalid-type") return `${r.file.name} isn't a PDF.`;
  return `${r.file.name} can't be uploaded.`;
}
