/** Strip only accidental edge whitespace from a pasted approval code.
 * No logging, case-folding, Unicode normalization, or changes to internal
 * characters. Both entered code and environment secret are compared by the
 * existing constant-time digest check after this normalisation.
 */
export function normalizeApprovalInput(value) {
  return typeof value === "string" ? value.trim() : "";
}
