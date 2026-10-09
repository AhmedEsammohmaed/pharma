import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api";

describe("typed API error handling", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("includes safe Pydantic field errors without rejected values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: {
        code: "validation_error",
        message: "Request validation failed",
        details: [{ location: ["body", "items", 0, "quantity"], message: "Input should be greater than 0", type: "greater_than" }],
      },
    }), { status: 422, headers: { "Content-Type": "application/json" } })));

    await expect(apiFetch("/api/v1/orders", "test-token", { method: "POST" })).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "Request validation failed: items.0.quantity: Input should be greater than 0",
    });
  });

  it("keeps server errors structured and safe", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: "internal_error", message: "An unexpected error occurred", details: null },
    }), { status: 500, headers: { "Content-Type": "application/json" } })));

    await expect(apiFetch("/api/v1/orders", "test-token")).rejects.toMatchObject({
      status: 500,
      code: "internal_error",
      message: "An unexpected error occurred",
    });
  });
});
